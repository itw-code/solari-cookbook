"""Hybrid Runner for ARC (Phase 3A).

Orchestrates Phase 2 Reflex Automation with Phase 3 Deterministic Monitors & Escalation:
- Dispatches routine steps through ReflexRunner.
- Updates StuckMonitor and MilestoneMonitor after every step.
- EscalationController evaluates signals and dictates:
  * CONTINUE: normal progression or post-recovery cooldown
  * RECOVER_LOCALLY: attempt immediate low-overhead local recovery
  * ESCALATE: construct EscalationPayload, query Cortex, compile typed plan, execute
  * ABORT: budget exhausted or fatal condition
- Pure mock mode by default; zero external network or LLM calls unless CORTEX_MODE=real.
- Emits structured HybridRunResult with complete telemetry and monitor summaries.

Fulfills Task 7 Requirements.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Union

from .cdp_extractor import CDP_AXTree_Extractor, SanitizedAXTree
from .cortex.cortex_interface import CortexClient
from .cortex.http_cortex import HttpCortexClient
from .cortex.mock_cortex import MockCortexClient
from .cortex.recovery_compiler import RecoveryCompiler
from .executor_interface import ActionPayload
from .monitors.escalation_controller import EscalationController
from .monitors.milestone_monitor import MilestoneMonitor
from .monitors.stuck_monitor import StepTelemetry, StuckMonitor
from .reflex_runner import ReflexExecutionResult, ReflexRunner, ReflexStatus
from .schemas import (
    ActionStep,
    DecisionType,
    EscalationPayload,
    EscalationReason,
    HybridRunResult,
    PerceptionSource,
    PlanSource,
    RecoveryPlan,
    TelemetryRecord,
    UIState,
)
from .telemetry import TelemetryCollector

logger = logging.getLogger("arc_cua.hybrid_runner")


class HybridRunner:
    """Orchestrator combining fast-reflex local automation with reasoning escalation."""

    def __init__(
        self,
        reflex_runner: Optional[ReflexRunner] = None,
        stuck_monitor: Optional[StuckMonitor] = None,
        milestone_monitor: Optional[MilestoneMonitor] = None,
        escalation_controller: Optional[EscalationController] = None,
        cortex_client: Optional[CortexClient] = None,
        recovery_compiler: Optional[RecoveryCompiler] = None,
        telemetry: Optional[TelemetryCollector] = None,
        cortex_mode: Optional[str] = None,
        session_id: Optional[str] = None,
    ):
        """Initialize the Hybrid Runner.

        Args:
            reflex_runner: ReflexRunner instance for executing steps.
            stuck_monitor: StuckMonitor instance for detecting loops and stagnation.
            milestone_monitor: MilestoneMonitor instance for detecting task advancement.
            escalation_controller: EscalationController instance for governing decisions.
            cortex_client: CortexClient instance (defaults to MockCortexClient).
            recovery_compiler: RecoveryCompiler instance.
            telemetry: TelemetryCollector instance.
            cortex_mode: Mode ('mock' or 'real', default from env CORTEX_MODE or 'mock').
            session_id: Session identifier.
        """
        self.session_id = session_id or f"hybrid-{uuid.uuid4().hex[:8]}"
        self.telemetry = telemetry or TelemetryCollector(session_id=self.session_id)
        self.reflex_runner = reflex_runner or ReflexRunner(telemetry=self.telemetry, session_id=self.session_id)
        self.stuck_monitor = stuck_monitor or StuckMonitor()
        self.milestone_monitor = milestone_monitor or MilestoneMonitor()
        self.escalation_controller = escalation_controller or EscalationController()
        self.recovery_compiler = recovery_compiler or RecoveryCompiler()

        # Resolve cortex mode
        self.cortex_mode = (cortex_mode or os.getenv("CORTEX_MODE", "mock")).lower()
        if cortex_client:
            self.cortex_client = cortex_client
        else:
            self.cortex_client = HttpCortexClient(
                mode=self.cortex_mode,
                recovery_compiler=self.recovery_compiler,
            )

    def run(
        self,
        page: Any,
        steps: List[Union[ActionStep, ActionPayload, Dict[str, Any]]],
        task_goal: str = "Hybrid Execution",
        initial_tree: Optional[SanitizedAXTree] = None,
        extractor: Optional[CDP_AXTree_Extractor] = None,
    ) -> HybridRunResult:
        """Execute a plan of actions through the Hybrid Reflex/Cortex loop.

        Args:
            page: Public Playwright Page object or mock page.
            steps: Sequence of planned steps to dispatch.
            task_goal: High-level task instruction.
            initial_tree: Optional initial accessibility tree snapshot.
            extractor: Optional CDP extractor for live accessibility.

        Returns:
            HybridRunResult summarizing execution, escalations, recoveries, and telemetry.
        """
        total_steps = 0
        reflex_steps = 0
        escalations = 0
        recoveries_attempted = 0
        recoveries_succeeded = 0
        milestones_detected = 0
        aborted = False
        abort_reason: Optional[str] = None
        completed_steps: List[ActionStep] = []
        final_state_hash = 0

        queue = list(steps)
        current_tree = initial_tree

        # Reset monitors for new run
        self.stuck_monitor.reset()
        self.milestone_monitor.reset()
        self.escalation_controller.reset()

        logger.info(f"Starting Hybrid Execution: {len(queue)} initial steps, goal='{task_goal}'")

        while queue and not aborted:
            current_step = queue.pop(0)
            total_steps += 1
            reflex_steps += 1

            step_idx = total_steps
            verb, target, value, _ = self.reflex_runner._normalize_step(current_step, step_idx)
            logger.info(f"[Hybrid Step {step_idx}] Dispatching Reflex Action: {verb} {target or ''}")

            # 1. Execute Reflex step
            res: ReflexExecutionResult = self.reflex_runner.run_steps(
                page=page,
                steps=[current_step],
                task_goal=task_goal,
                initial_tree=current_tree,
                extractor=extractor,
            )

            # 2. Extract step observations & verifications
            if res.status == ReflexStatus.ESCALATE:
                esc_payload = res.escalation_payload
                failure_reason = esc_payload.reason.value if esc_payload else "UNKNOWN_FAILURE"
                step_telemetry = StepTelemetry(
                    step_id=step_idx,
                    verb=verb,
                    target=target,
                    value=value,
                    success=False,
                    error_message=failure_reason,
                    readiness_ok=(esc_payload.reason != EscalationReason.READINESS_TIMEOUT if esc_payload else False),
                    readiness_reason=failure_reason if esc_payload and esc_payload.reason == EscalationReason.READINESS_TIMEOUT else None,
                    action_exception=True,
                )
                is_hard = True
                hard_reason = failure_reason
            else:
                executed_step = res.completed_steps[-1] if res.completed_steps else None
                if executed_step:
                    completed_steps.append(executed_step)

                rec = res.telemetry_records[-1] if res.telemetry_records else None
                meta = rec.metadata if rec else {}

                simhash_before = int(meta.get("simhash_before", "0"), 16) if isinstance(meta.get("simhash_before"), str) else meta.get("simhash_before", 0)
                simhash_after = int(meta.get("simhash_after", "0"), 16) if isinstance(meta.get("simhash_after"), str) else meta.get("simhash_after", 0)
                hamming = meta.get("hamming_distance", 0)
                final_state_hash = simhash_after or final_state_hash

                url_after = executed_step.resulting_url if executed_step else getattr(page, "url", None)
                url_changed = bool(url_after and url_after != getattr(page, "url", None))
                state_changed = (hamming > 0 or url_changed)

                step_telemetry = StepTelemetry(
                    step_id=step_idx,
                    verb=verb,
                    target=target,
                    value=value,
                    success=executed_step.success if executed_step else True,
                    error_message=executed_step.error_message if executed_step else None,
                    state_changed=state_changed,
                    state_hash=simhash_after,
                    previous_state_hash=simhash_before,
                    hamming_distance=hamming,
                    url_changed=url_changed,
                    url=url_after,
                    readiness_ok=True,
                    is_neutral=(verb.upper() in {"WAIT", "NOOP"}),
                    verification_is_stuck=(not state_changed and verb.upper() not in {"WAIT", "NOOP"}),
                )
                is_hard = False
                hard_reason = None

            # 3. Update Monitors
            stuck_sig = self.stuck_monitor.evaluate_step(step_telemetry)
            milestone_sig = self.milestone_monitor.evaluate(step_telemetry, goal=task_goal)

            if milestone_sig.is_milestone:
                milestones_detected += 1
                logger.info(f"Milestone Detected! Type={milestone_sig.milestone_type} Score={milestone_sig.milestone_score}")

            # 4. Escalation Controller Decision
            decision = self.escalation_controller.decide(
                stuck_signal=stuck_sig,
                milestone_signal=milestone_sig,
                step=step_telemetry,
                hard_failure=hard_reason,
                is_hard_failure=is_hard,
                failure_reason=hard_reason,
            )

            logger.info(f"Monitor Decision: {decision.decision.value} (reason: {decision.reason})")

            # 5. Attach monitor metrics to telemetry
            if res.telemetry_records:
                last_rec = res.telemetry_records[-1]
                last_rec.monitor_stuck_score = stuck_sig.stuck_score
                last_rec.monitor_milestone_score = milestone_sig.milestone_score
                last_rec.escalation_decision = decision.decision.value
                last_rec.escalation_reason = decision.reason
                last_rec.cooldown_active = (self.escalation_controller.cooldown_remaining > 0)
                last_rec.recoveries_used = self.escalation_controller.recoveries_used
                last_rec.escalations_used = self.escalation_controller.escalations_used


            # Record into TrajectoryCollector
            try:
                self.telemetry.record_trajectory_step(
                    run_id=self.session_id,
                    task_id=task_goal,
                    step_id=step_idx,
                    action_type=verb,
                    target_locator=target,
                    locator_strategy=target.split(":", 1)[0] if target and ":" in target else "generic",
                    readiness_passed=step_telemetry.readiness_ok,
                    execution_success=step_telemetry.success,
                    state_hash_before=step_telemetry.previous_state_hash,
                    state_hash_after=step_telemetry.state_hash,
                    state_changed=step_telemetry.state_changed,
                    hamming_distance=step_telemetry.hamming_distance,
                    url_before=getattr(page, "url", None) if not step_telemetry.url_changed else None,
                    url_after=step_telemetry.url,
                    url_changed=step_telemetry.url_changed,
                    error_detected=(not step_telemetry.success or is_hard),
                    error_type=hard_reason or step_telemetry.error_message,
                    monitor_stuck_score=stuck_sig.stuck_score,
                    monitor_milestone_score=milestone_sig.milestone_score,
                    escalation_decision=decision.decision.value,
                    recovery_attempted=(decision.decision in {DecisionType.RECOVER_LOCALLY, DecisionType.ESCALATE}),
                    recovery_success=None,
                    integration_mode=self.cortex_mode,
                )
            except Exception as traj_err:
                logger.warning(f"Failed to record trajectory step: {traj_err}")
            # 6. Branch on Controller Decision
            if decision.decision == DecisionType.ABORT:
                aborted = True
                abort_reason = decision.reason
                logger.error(f"Execution Aborted by Controller: {abort_reason}")
                break

            elif decision.decision == DecisionType.CONTINUE:
                # Progress or cooldown, proceed to next step
                continue

            elif decision.decision == DecisionType.RECOVER_LOCALLY:
                recoveries_attempted += 1
                logger.info(f"Initiating Local Recovery attempt #{recoveries_attempted}...")
                local_plan = RecoveryPlan(
                    plan_id=f"local-{step_idx}-{uuid.uuid4().hex[:4]}",
                    source=PlanSource.LOCAL_RECOVERY,
                    actions=[
                        {"verb": "WAIT", "target": None, "value": "1000"},
                    ],
                    expected_outcome="Local settling delay before continuing",
                    stop_condition="delay_completed",
                )
                try:
                    local_steps = self.recovery_compiler.compile(local_plan, start_step=total_steps + 1)
                    loc_res = self.reflex_runner.run_steps(page, local_steps, task_goal=f"Local Recovery for step {step_idx}")
                    total_steps += len(local_steps)
                    if loc_res.status == ReflexStatus.COMPLETED:
                        recoveries_succeeded += 1
                        logger.info("Local recovery executed successfully")
                        self.escalation_controller.activate_cooldown()
                        completed_steps.extend(loc_res.completed_steps)
                    else:
                        logger.warning("Local recovery failed to settle state")
                except Exception as loc_err:
                    logger.error(f"Local recovery error: {loc_err}")

            elif decision.decision == DecisionType.ESCALATE:
                escalations += 1
                recoveries_attempted += 1
                logger.warning(f"Escalation #{escalations} Initiated: {decision.reason}")

                # Build or reuse EscalationPayload
                if res.status == ReflexStatus.ESCALATE and res.escalation_payload:
                    payload = res.escalation_payload
                else:
                    reason_enum = EscalationReason.STATE_NOT_CHANGED if stuck_sig.is_stuck else EscalationReason.ESCALATION_REQUIRED
                    payload = self.reflex_runner._build_escalation(
                        task_goal=task_goal,
                        reason=reason_enum,
                        current_state=UIState(
                            state_id=f"state-{step_idx}",
                            timestamp=time.time(),
                            source=PerceptionSource.CDP_AXTREE,
                            simhash=final_state_hash,
                            raw_node_count=10,
                            pruned_node_count=5,
                            actionable_count=3,
                            estimated_tokens=50,
                            yaml_representation="",
                            structured_tree={},
                            action_index_map={},
                        ),
                        failure_details={"reason": decision.reason, "stuck_evidence": stuck_sig.evidence},
                    )

                # Query Cortex Client (mock by default)
                cortex_resp = self.cortex_client.recover(payload)
                logger.info(
                    f"Cortex generated plan '{cortex_resp.plan.plan_id if cortex_resp.plan else 'none'}' "
                    f"via {cortex_resp.model} ({cortex_resp.latency_ms:.2f}ms)"
                )

                if not cortex_resp.success or not cortex_resp.plan:
                    logger.error("Cortex failed to produce recovery plan")
                    if self.escalation_controller.escalations_used >= self.escalation_controller.max_escalations_per_task:
                        aborted = True
                        abort_reason = "cortex_plan_failed_budget_exhausted"
                        break
                    continue

                # Compile recovery plan
                try:
                    recovery_steps = self.recovery_compiler.compile(cortex_resp, start_step=total_steps + 1)
                except Exception as comp_err:
                    logger.error(f"Recovery compilation error: {comp_err}")
                    aborted = True
                    abort_reason = f"recovery_compilation_error: {comp_err}"
                    break

                # Execute recovery plan
                logger.info(f"Executing {len(recovery_steps)} compiled recovery actions...")
                rec_res = self.reflex_runner.run_steps(
                    page=page,
                    steps=recovery_steps,
                    task_goal=f"Recovery from {decision.reason}",
                )
                total_steps += len(recovery_steps)

                if rec_res.status == ReflexStatus.COMPLETED:
                    recoveries_succeeded += 1
                    logger.info("Cortex recovery execution SUCCEEDED")
                    completed_steps.extend(rec_res.completed_steps)
                    self.escalation_controller.activate_cooldown()
                else:
                    logger.warning(f"Recovery actions failed or escalated: {rec_res.status.value}")

        summary = self.telemetry.get_summary()
        success = not aborted and (res.status == ReflexStatus.COMPLETED if 'res' in locals() else True)

        logger.info(
            f"Hybrid Run Finished: success={success}, total_steps={total_steps}, "
            f"reflex_steps={reflex_steps}, escalations={escalations}, recoveries={recoveries_succeeded}/{recoveries_attempted}"
        )

        return HybridRunResult(
            success=success,
            total_steps=total_steps,
            reflex_steps=reflex_steps,
            escalations=escalations,
            recoveries_attempted=recoveries_attempted,
            recoveries_succeeded=recoveries_succeeded,
            milestones_detected=milestones_detected,
            aborted=aborted,
            abort_reason=abort_reason,
            final_state_hash=final_state_hash,
            telemetry_summary=summary,
            completed_steps=completed_steps,
            metadata={
                "task_goal": task_goal,
                "cortex_mode": self.cortex_mode,
                "session_id": self.session_id,
            },
        )
