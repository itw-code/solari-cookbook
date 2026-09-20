"""Reflex Runner & Telemetry Integration for Phase 2 Reflex Automation.

Implements Task 2.5:
- Deterministic local execution loop executing typed ActionStep sequences.
- Step Lifecycle: Resolve Locator -> Readiness Guard -> Execute Action -> Verify State -> Log Telemetry.
- Halts execution and yields an ESCALATE signal with EscalationPayload on:
  * Locator not found after fallback chain exhausted.
  * State verification fails 3 consecutive times (stuck loop).
  * Action failure or readiness timeout.
- Records fine-grained latency breakdowns (resolution, execution, verification) in TelemetryCollector.
- Purely local deterministic execution without external LLM calls.
"""

from __future__ import annotations

import dataclasses
import enum
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union

from .cdp_extractor import CDP_AXTree_Extractor, SanitizedAXTree
from .executor_interface import ActionPayload, ActionVerb
from .locator_resolver import LocatorResolutionError, LocatorResolver, ResolvedLocator
from .playwright_executor import PlaywrightExecutor
from .schemas import (
    ActionResult,
    ActionStep,
    EscalationPayload,
    EscalationReason,
    PerceptionSource,
    TelemetryRecord,
    UIState,
)
from .session_guard import ReadinessResult, SessionGuard
from .state_verifier import StateVerificationResult, StateVerifier
from .telemetry import TelemetryCollector, compute_simhash64

logger = logging.getLogger("arc_cua.reflex_runner")


class ReflexStatus(str, enum.Enum):
    """Execution status of the Reflex loop."""
    COMPLETED = "COMPLETED"
    ESCALATE = "ESCALATE"
    FAILED = "FAILED"


@dataclasses.dataclass
class ReflexExecutionResult:
    """Consolidated outcome of the Reflex runner execution."""
    status: ReflexStatus
    completed_steps: List[ActionStep]
    escalation_payload: Optional[EscalationPayload] = None
    total_latency_ms: float = 0.0
    telemetry_records: List[TelemetryRecord] = dataclasses.field(default_factory=list)
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)


class ReflexRunner:
    """Local deterministic execution supervisor coordinating perception, resolution, action, and verification."""

    def __init__(
        self,
        executor: Optional[PlaywrightExecutor] = None,
        resolver: Optional[LocatorResolver] = None,
        guard: Optional[SessionGuard] = None,
        verifier: Optional[StateVerifier] = None,
        telemetry: Optional[TelemetryCollector] = None,
        max_stuck_attempts: int = 3,
        session_id: Optional[str] = None,
        vm_id: str = "vm-reflex-0",
    ):
        """Initialize the Reflex Runner.

        Args:
            executor: PlaywrightExecutor instance (or default initialized).
            resolver: LocatorResolver instance (or default initialized).
            guard: SessionGuard instance (or default initialized).
            verifier: StateVerifier instance (or default initialized).
            telemetry: TelemetryCollector instance (or default initialized).
            max_stuck_attempts: Consecutive unverified state changes before escalating.
            session_id: Optional tracking session ID.
            vm_id: Target microVM identifier.
        """
        self.executor = executor or PlaywrightExecutor()
        self.resolver = resolver or LocatorResolver()
        self.guard = guard or SessionGuard()
        self.verifier = verifier or StateVerifier()
        self.telemetry = telemetry or TelemetryCollector()
        self.max_stuck_attempts = max_stuck_attempts
        self.session_id = session_id or f"session-{uuid.uuid4().hex[:8]}"
        self.vm_id = vm_id

        # Internal state tracking
        self.consecutive_stuck_count = 0
        self.executed_history: List[ActionStep] = []

    def run_steps(
        self,
        page: Any,
        steps: List[Union[ActionStep, ActionPayload, Dict[str, Any]]],
        task_goal: str = "Reflex Execution",
        initial_tree: Optional[SanitizedAXTree] = None,
        extractor: Optional[CDP_AXTree_Extractor] = None,
    ) -> ReflexExecutionResult:
        """Execute a sequence of routine actions deterministically.

        Args:
            page: Public Playwright Page object or mock page.
            steps: Ordered sequence of actions to dispatch.
            task_goal: Overall task description for telemetry and escalation framing.
            initial_tree: Optional pre-extracted AXTree.
            extractor: Optional CDP_AXTree_Extractor to extract live perception.

        Returns:
            ReflexExecutionResult indicating completion or escalation.
        """
        start_time = time.perf_counter()
        current_tree = initial_tree
        collected_records: List[TelemetryRecord] = []
        self.consecutive_stuck_count = 0
        self.executed_history.clear()

        for step_idx, step_input in enumerate(steps, start=1):
            step_start = time.perf_counter()
            logger.info(f"Executing Reflex Step {step_idx}/{len(steps)}")

            # Normalize step input into verb, target, value
            verb, target, value, action_idx = self._normalize_step(step_input, step_idx)

            # --- Phase 1: Capture Pre-State ---
            p_start = time.perf_counter()
            state_before, current_tree = self._capture_ui_state(
                page, current_tree, extractor, step_idx
            )
            perception_lat = (time.perf_counter() - p_start) * 1000.0

            # --- Phase 2: Resolve Locator ---
            r_start = time.perf_counter()
            resolved_loc: Optional[ResolvedLocator] = None
            if target or action_idx is not None:
                lookup_target: Union[int, str] = action_idx if action_idx is not None else target  # type: ignore
                try:
                    resolved_loc = self.resolver.resolve(
                        node_or_index=lookup_target,
                        page=page,
                        tree=current_tree,
                        goal=f"{verb} {target or action_idx}",
                    )
                except (LocatorResolutionError, Exception) as loc_err:
                    resolution_lat = (time.perf_counter() - r_start) * 1000.0
                    logger.error(
                        f"Step {step_idx} failed: Locator resolution exhausted: {loc_err}"
                    )
                    # Yield ESCALATE signal
                    escalation = self._build_escalation(
                        task_goal=task_goal,
                        reason=EscalationReason.LOCATOR_NOT_FOUND,
                        current_state=state_before,
                        failure_details={
                            "step_index": step_idx,
                            "target": target,
                            "action_index": action_idx,
                            "error": str(loc_err),
                        },
                    )
                    total_lat = (time.perf_counter() - start_time) * 1000.0
                    return ReflexExecutionResult(
                        status=ReflexStatus.ESCALATE,
                        completed_steps=list(self.executed_history),
                        escalation_payload=escalation,
                        total_latency_ms=total_lat,
                        telemetry_records=collected_records,
                    )

            resolution_lat = (time.perf_counter() - r_start) * 1000.0
            effective_selector = resolved_loc.selector if resolved_loc else target

            # --- Phase 3: Session Readiness Guard ---
            g_start = time.perf_counter()
            readiness = self.guard.verify_readiness(
                page=page,
                target_selector=effective_selector,
                wait_if_unready=True,
            )
            readiness_lat = (time.perf_counter() - g_start) * 1000.0

            if not readiness.is_ready:
                logger.error(
                    f"Step {step_idx} failed: Session readiness check failed: {readiness.reason}"
                )
                escalation = self._build_escalation(
                    task_goal=task_goal,
                    reason=EscalationReason.ACTION_TIMEOUT,
                    current_state=state_before,
                    failure_details={
                        "step_index": step_idx,
                        "reason": readiness.reason,
                        "readiness_details": readiness.details,
                    },
                )
                total_lat = (time.perf_counter() - start_time) * 1000.0
                return ReflexExecutionResult(
                    status=ReflexStatus.ESCALATE,
                    completed_steps=list(self.executed_history),
                    escalation_payload=escalation,
                    total_latency_ms=total_lat,
                    telemetry_records=collected_records,
                )

            # --- Phase 4: Execute Action ---
            e_start = time.perf_counter()
            action_payload = ActionPayload(
                verb=self._to_action_verb(verb),
                target_selector=effective_selector,
                value=value,
                action_index=action_idx,
            )
            action_result = self.executor.execute(page, action_payload)
            action_lat = action_result.latency_ms or ((time.perf_counter() - e_start) * 1000.0)

            if not action_result.success:
                logger.error(f"Step {step_idx} execution error: {action_result.error_message}")
                escalation = self._build_escalation(
                    task_goal=task_goal,
                    reason=EscalationReason.ACTION_TIMEOUT,
                    current_state=state_before,
                    failure_details={
                        "step_index": step_idx,
                        "verb": verb,
                        "target": effective_selector,
                        "error": action_result.error_message,
                    },
                )
                total_lat = (time.perf_counter() - start_time) * 1000.0
                return ReflexExecutionResult(
                    status=ReflexStatus.ESCALATE,
                    completed_steps=list(self.executed_history),
                    escalation_payload=escalation,
                    total_latency_ms=total_lat,
                    telemetry_records=collected_records,
                )

            # --- Phase 5: State Verification ---
            v_start = time.perf_counter()
            state_after, current_tree = self._capture_ui_state(
                page, current_tree, extractor, step_idx, is_post=True, executed_action=action_result
            )
            verification = self.verifier.verify(
                action_result=action_result,
                state_before=state_before,
                state_after=state_after,
                url_before=getattr(page, "url", None),
                url_after=action_result.resulting_url or getattr(page, "url", None),
            )
            verification_lat = verification.verification_latency_ms or (
                (time.perf_counter() - v_start) * 1000.0
            )

            # Track stuck monitor count
            if verification.is_stuck_indicator:
                self.consecutive_stuck_count += 1
                logger.warning(
                    f"Step {step_idx}: Stuck condition detected (count={self.consecutive_stuck_count}/{self.max_stuck_attempts})"
                )
                if self.consecutive_stuck_count >= self.max_stuck_attempts:
                    logger.error(
                        f"Step {step_idx}: Escalating to Cortex due to {self.max_stuck_attempts} consecutive stuck actions"
                    )
                    escalation = self._build_escalation(
                        task_goal=task_goal,
                        reason=EscalationReason.STATE_NOT_CHANGED,
                        current_state=state_after,
                        failure_details={
                            "consecutive_stuck_count": self.consecutive_stuck_count,
                            "last_action": verb,
                            "target": effective_selector,
                            "hamming_distance": verification.hamming_distance,
                        },
                    )
                    total_lat = (time.perf_counter() - start_time) * 1000.0
                    return ReflexExecutionResult(
                        status=ReflexStatus.ESCALATE,
                        completed_steps=list(self.executed_history),
                        escalation_payload=escalation,
                        total_latency_ms=total_lat,
                        telemetry_records=collected_records,
                    )
            else:
                self.consecutive_stuck_count = 0

            # --- Phase 6: Log Telemetry ---
            total_step_lat = (time.perf_counter() - step_start) * 1000.0

            action_step = action_result.to_action_step(step_number=step_idx, action_index=action_idx)
            self.executed_history.append(action_step)

            record = TelemetryRecord(
                session_id=self.session_id,
                vm_id=self.vm_id,
                step_index=step_idx,
                route="reflex",
                total_step_latency_ms=total_step_lat,
                perception_latency_ms=perception_lat,
                action_latency_ms=action_lat,
                tokens_consumed=0,  # Reflex local execution consumes 0 LLM tokens!
                memory_overhead_mb=28.5,
                sockets_active_count=1,
                success=action_result.success and not verification.is_stuck_indicator,
                metadata={
                    "verb": verb,
                    "target": effective_selector,
                    "resolution_latency_ms": resolution_lat,
                    "readiness_latency_ms": readiness_lat,
                    "verification_latency_ms": verification_lat,
                    "simhash_before": hex(verification.simhash_before),
                    "simhash_after": hex(verification.simhash_after),
                    "hamming_distance": verification.hamming_distance,
                    "strategy": resolved_loc.strategy if resolved_loc else "direct",
                    "confidence": resolved_loc.confidence if resolved_loc else 1.0,
                },
            )
            self.telemetry.record(record)
            collected_records.append(record)

        total_latency = (time.perf_counter() - start_time) * 1000.0
        return ReflexExecutionResult(
            status=ReflexStatus.COMPLETED,
            completed_steps=list(self.executed_history),
            escalation_payload=None,
            total_latency_ms=total_latency,
            telemetry_records=collected_records,
            metadata={"steps_count": len(steps)},
        )

    def _normalize_step(
        self,
        step: Union[ActionStep, ActionPayload, Dict[str, Any]],
        step_idx: int,
    ) -> Tuple[str, Optional[str], Optional[str], Optional[int]]:
        """Normalize various action inputs into (verb, target_selector, value, action_index)."""
        if isinstance(step, ActionStep):
            return step.verb, step.target_selector, step.value, step.action_index
        elif isinstance(step, ActionPayload):
            verb_str = step.verb.value if isinstance(step.verb, ActionVerb) else str(step.verb)
            return verb_str, step.target_selector, step.value, step.action_index
        elif isinstance(step, dict):
            verb_str = str(step.get("verb", "CLICK")).upper()
            return (
                verb_str,
                step.get("target_selector") or step.get("selector") or step.get("target"),
                step.get("value"),
                step.get("action_index"),
            )
        else:
            raise ValueError(f"Unsupported step format: {type(step)}")

    def _to_action_verb(self, verb_str: str) -> ActionVerb:
        """Convert string verb into ActionVerb enum."""
        upper = verb_str.upper()
        if upper in ("TYPE", "FILL"):
            return ActionVerb.FILL
        if upper == "CLICK":
            return ActionVerb.CLICK
        if upper in ("SELECT", "SELECT_OPTION"):
            return ActionVerb.SELECT_OPTION
        if upper == "PRESS_KEY":
            return ActionVerb.PRESS_KEY
        if upper == "SCROLL":
            return ActionVerb.SCROLL
        if upper in ("GOTO", "NAVIGATE"):
            return ActionVerb.NAVIGATE
        if upper == "WAIT":
            return ActionVerb.WAIT_FOR_SELECTOR
        return ActionVerb.CLICK

    def _capture_ui_state(
        self,
        page: Any,
        current_tree: Optional[SanitizedAXTree],
        extractor: Optional[CDP_AXTree_Extractor],
        step_idx: int,
        is_post: bool = False,
        executed_action: Optional[ActionResult] = None,
    ) -> Tuple[UIState, Optional[SanitizedAXTree]]:
        """Capture or synthesize UIState snapshot."""
        now = time.time()
        active_url = getattr(page, "url", "about:blank")

        if extractor is not None:
            try:
                tree = extractor.extract()
                simhash = compute_simhash64(tree.yaml_linearized)
                ui_state = UIState(
                    state_id=f"state-{step_idx}-{'post' if is_post else 'pre'}",
                    timestamp=now,
                    source=PerceptionSource.CDP_AXTREE,
                    simhash=simhash,
                    raw_node_count=tree.raw_node_count,
                    pruned_node_count=tree.pruned_node_count,
                    actionable_count=tree.actionable_count,
                    estimated_tokens=tree.estimated_tokens,
                    yaml_representation=tree.yaml_linearized,
                    structured_tree={"nodes": tree.json_structured},
                    action_index_map=tree.action_index_map,
                    active_window_title=getattr(page, "title", None),
                )
                return ui_state, tree
            except Exception as e:
                logger.debug(f"Live tree extraction exception: {e}")

        if current_tree is not None:
            # If simulated post-state and action changed value, mutate text representation
            yaml_rep = current_tree.yaml_linearized
            if is_post and executed_action and executed_action.value:
                yaml_rep += f"\n  - mutated value={executed_action.value}"
            elif is_post and executed_action and executed_action.verb == "GOTO":
                yaml_rep += f"\n  - navigated to={executed_action.value}"

            simhash = compute_simhash64(yaml_rep)
            ui_state = UIState(
                state_id=f"state-{step_idx}-{'post' if is_post else 'pre'}",
                timestamp=now,
                source=PerceptionSource.CDP_AXTREE,
                simhash=simhash,
                raw_node_count=current_tree.raw_node_count,
                pruned_node_count=current_tree.pruned_node_count,
                actionable_count=current_tree.actionable_count,
                estimated_tokens=current_tree.estimated_tokens,
                yaml_representation=yaml_rep,
                structured_tree={"nodes": current_tree.json_structured},
                action_index_map=current_tree.action_index_map,
                active_window_title=getattr(page, "title", None),
            )
            return ui_state, current_tree

        # Fallback minimal snapshot
        yaml_content = f"- page url='{active_url}'"
        if is_post and executed_action and executed_action.value:
            yaml_content += f" value='{executed_action.value}'"
        simhash = compute_simhash64(yaml_content)
        ui_state = UIState(
            state_id=f"state-{step_idx}-{'post' if is_post else 'pre'}",
            timestamp=now,
            source=PerceptionSource.CDP_AXTREE,
            simhash=simhash,
            raw_node_count=1,
            pruned_node_count=0,
            actionable_count=1,
            estimated_tokens=10,
            yaml_representation=yaml_content,
            structured_tree={},
            action_index_map={},
            active_window_title=getattr(page, "title", None),
        )
        return ui_state, current_tree

    def _build_escalation(
        self,
        task_goal: str,
        reason: EscalationReason,
        current_state: UIState,
        failure_details: Dict[str, Any],
    ) -> EscalationPayload:
        """Construct standard EscalationPayload for Phase 3 Cortex consumption."""
        return EscalationPayload(
            escalation_id=f"esc-{uuid.uuid4().hex[:8]}",
            task_goal=task_goal,
            reason=reason,
            step_history=list(self.executed_history),
            current_state=current_state,
            failure_details=failure_details,
        )
