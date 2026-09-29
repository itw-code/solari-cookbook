"""Deterministic Sliding-Window Stuck Monitor for ARC (Phase 3A).

Detects failure patterns from recent Reflex Engine telemetry across a sliding window of 5 steps:
1. Repeated action with no state change.
2. Same locator failing multiple times.
3. Alternating between two identical state hashes (cyclic oscillation).
4. Repeated readiness timeouts.
5. Repeated action exceptions.
6. Mechanical success but zero state delta.
7. Three consecutive STATE_NOT_CHANGED results.

Fulfills Task 2 Requirements:
- Purely deterministic; no external APIs.
- Sub-10ms p95 latency.
- Uses state verification and telemetry results.
- No screenshot dependencies.
"""

from __future__ import annotations

import collections
import dataclasses
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from ..schemas import ActionResult, ActionStep, StuckSignal
from ..state_verifier import StateVerificationResult

logger = logging.getLogger("arc_cua.monitors.stuck_monitor")


@dataclasses.dataclass
class StepTelemetry:
    """Snapshot of a single execution step for monitor evaluation."""
    step_id: int
    verb: str = ""
    target: Optional[str] = None
    value: Optional[str] = None
    success: bool = True
    error_message: Optional[str] = None
    state_changed: bool = False
    state_hash: int = 0
    previous_state_hash: int = 0
    hamming_distance: int = 0
    url_changed: bool = False
    url: Optional[str] = None
    readiness_ok: bool = True
    readiness_reason: Optional[str] = None
    verification_is_stuck: bool = False
    action_exception: bool = False
    is_neutral: bool = False
    latency_ms: float = 0.0
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

    @classmethod
    def from_step(
        cls,
        step_id: int,
        action_result: Optional[ActionResult] = None,
        verification_result: Optional[StateVerificationResult] = None,
        readiness_ok: bool = True,
        readiness_reason: Optional[str] = None,
        action_step: Optional[ActionStep] = None,
        **kwargs: Any,
    ) -> StepTelemetry:
        """Construct StepTelemetry from existing Phase 2 results."""
        verb = ""
        target = None
        value = None
        success = True
        error_msg = None
        lat = 0.0

        if action_result:
            verb = action_result.verb or ""
            target = action_result.target_selector
            value = action_result.value
            success = action_result.success
            error_msg = action_result.error_message
            lat = action_result.latency_ms
        elif action_step:
            verb = action_step.verb or ""
            target = action_step.target_selector
            value = action_step.value
            success = action_step.success
            error_msg = action_step.error_message
            lat = action_step.latency_ms

        state_changed = False
        state_hash = 0
        prev_hash = 0
        hamming = 0
        url_changed = False
        is_stuck_indicator = False

        if verification_result:
            state_changed = verification_result.state_changed
            state_hash = verification_result.simhash_after
            prev_hash = verification_result.simhash_before
            hamming = verification_result.hamming_distance
            url_changed = verification_result.url_changed
            is_stuck_indicator = verification_result.is_stuck_indicator

        is_neutral = verb.upper() in {"WAIT", "WAIT_FOR_SELECTOR", "NOOP", "SLEEP"}
        has_exception = not success or bool(error_msg)

        return cls(
            step_id=step_id,
            verb=verb,
            target=target,
            value=value,
            success=success,
            error_message=error_msg,
            state_changed=state_changed,
            state_hash=state_hash,
            previous_state_hash=prev_hash,
            hamming_distance=hamming,
            url_changed=url_changed,
            readiness_ok=readiness_ok,
            readiness_reason=readiness_reason,
            verification_is_stuck=is_stuck_indicator,
            action_exception=has_exception,
            is_neutral=is_neutral,
            latency_ms=lat,
            metadata=kwargs,
        )


class StuckMonitor:
    """Sliding-window monitor evaluating whether the agent is stuck in an unrecoverable local trap."""

    def __init__(
        self,
        window_size: int = 5,
        stuck_threshold: float = 0.75,
    ):
        """Initialize StuckMonitor.

        Args:
            window_size: Number of recent steps retained in sliding window (default: 5).
            stuck_threshold: Threshold above which is_stuck triggers True (default: 0.75).
        """
        self.window_size = window_size
        self.stuck_threshold = stuck_threshold
        self._window: collections.deque[StepTelemetry] = collections.deque(maxlen=window_size)
        self.consecutive_no_change_count: int = 0

    def reset(self) -> None:
        """Clear sliding window history and counters."""
        self._window.clear()
        self.consecutive_no_change_count = 0

    def evaluate_step(
        self,
        step: StepTelemetry,
    ) -> StuckSignal:
        """Append a single step and evaluate stuck heuristics.

        Args:
            step: Telemetry record of the executed step.

        Returns:
            StuckSignal containing stuck_score, is_stuck, reason, and evidence.
        """
        # Update consecutive no-change counter
        if not step.state_changed and not step.url_changed and not step.is_neutral:
            self.consecutive_no_change_count += 1
        elif step.state_changed or step.url_changed:
            self.consecutive_no_change_count = 0

        self._window.append(step)
        return self.evaluate_window()

    def evaluate_window(self) -> StuckSignal:
        """Evaluate the current sliding window for stuck conditions."""
        if not self._window:
            return StuckSignal(
                stuck_score=0.0,
                is_stuck=False,
                reason="empty_history",
                evidence={},
            )

        patterns_detected: Dict[str, float] = {}
        evidence: Dict[str, Any] = {
            "window_size": len(self._window),
            "consecutive_no_change": self.consecutive_no_change_count,
        }

        # 1. Three consecutive STATE_NOT_CHANGED results
        if self.consecutive_no_change_count >= 3:
            patterns_detected["three_consecutive_no_change"] = 1.0
            evidence["three_consecutive_no_change"] = True

        # 2. Alternating between two identical state hashes (cyclic oscillation)
        oscillation_score, oscillation_detail = self._detect_oscillation()
        if oscillation_score > 0.0:
            patterns_detected["cyclic_state_oscillation"] = oscillation_score
            evidence["oscillation"] = oscillation_detail

        # 3. Repeated action with no state change
        repeated_action_score, repeated_action_detail = self._detect_repeated_action_no_change()
        if repeated_action_score > 0.0:
            patterns_detected["repeated_action_no_state_change"] = repeated_action_score
            evidence["repeated_action"] = repeated_action_detail

        # 4. Same locator failing multiple times
        locator_fail_score, locator_fail_detail = self._detect_repeated_locator_failures()
        if locator_fail_score > 0.0:
            patterns_detected["repeated_locator_failure"] = locator_fail_score
            evidence["locator_failures"] = locator_fail_detail

        # 5. Repeated readiness timeouts
        readiness_score, readiness_detail = self._detect_repeated_readiness_timeouts()
        if readiness_score > 0.0:
            patterns_detected["repeated_readiness_timeout"] = readiness_score
            evidence["readiness_timeouts"] = readiness_detail

        # 6. Repeated action exceptions
        exception_score, exception_detail = self._detect_repeated_action_exceptions()
        if exception_score > 0.0:
            patterns_detected["repeated_action_exception"] = exception_score
            evidence["action_exceptions"] = exception_detail

        # 7. Mechanical success but zero state delta
        zero_delta_score, zero_delta_detail = self._detect_mechanical_success_zero_delta()
        if zero_delta_score > 0.0:
            patterns_detected["mechanical_success_zero_delta"] = zero_delta_score
            evidence["zero_delta"] = zero_delta_detail

        # 8. Verifier-flagged no-op: a mutating verb that reported success but produced
        # no state transition. The StateVerifier already computes this per step; without
        # this pattern the signal was recorded and then discarded, so the loop had no rule
        # treating a successful action with zero state change as a stall (audit F-05).
        noop_score, noop_detail = self._detect_verifier_noop_streak()
        if noop_score > 0.0:
            patterns_detected["verifier_noop_streak"] = noop_score
            evidence["verifier_noop"] = noop_detail

        if not patterns_detected:
            return StuckSignal(
                stuck_score=0.0,
                is_stuck=False,
                reason="healthy_progress",
                evidence=evidence,
            )

        # Primary reason is the pattern with highest score
        primary_pattern, max_score = max(patterns_detected.items(), key=lambda item: item[1])
        evidence["patterns"] = patterns_detected

        is_stuck = max_score >= self.stuck_threshold

        return StuckSignal(
            stuck_score=round(max_score, 4),
            is_stuck=is_stuck,
            reason=primary_pattern,
            evidence=evidence,
        )

    def _detect_oscillation(self) -> Tuple[float, Dict[str, Any]]:
        """Detect cyclic state hash oscillation (e.g. A -> B -> A -> B or A -> B -> A)."""
        history = list(self._window)
        if len(history) < 3:
            return 0.0, {}

        hashes = [s.state_hash for s in history if s.state_hash != 0]
        if len(hashes) < 3:
            return 0.0, {}

        # Check 4-step 2-cycle: A -> B -> A -> B
        if len(hashes) >= 4:
            if hashes[-1] == hashes[-3] and hashes[-2] == hashes[-4] and hashes[-1] != hashes[-2]:
                return 0.95, {
                    "pattern": "4_step_2_cycle",
                    "hash_a": hex(hashes[-1]),
                    "hash_b": hex(hashes[-2]),
                }

        # Check 3-step ping-pong: A -> B -> A with identical non-neutral action
        if len(hashes) >= 3:
            if hashes[-1] == hashes[-3] and hashes[-1] != hashes[-2]:
                # If actions also match or are back-and-forth
                return 0.85, {
                    "pattern": "3_step_ping_pong",
                    "hash_a": hex(hashes[-1]),
                    "hash_b": hex(hashes[-2]),
                }

        return 0.0, {}

    def _detect_repeated_action_no_change(self) -> Tuple[float, Dict[str, Any]]:
        """Detect repeated action execution with no resulting state change."""
        history = [s for s in self._window if not s.is_neutral]
        if len(history) < 2:
            return 0.0, {}

        # Group actions by (verb, target, value)
        action_keys = collections.Counter()
        action_no_change = collections.Counter()

        for s in history:
            key = (s.verb.upper(), s.target or "")
            action_keys[key] += 1
            if not s.state_changed and not s.url_changed:
                action_no_change[key] += 1

        for key, count in action_no_change.items():
            if count >= 3:
                return 1.0, {"action": key, "no_change_count": count}
            elif count == 2 and action_keys[key] == 2:
                return 0.80, {"action": key, "no_change_count": count}

        return 0.0, {}

    def _detect_repeated_locator_failures(self) -> Tuple[float, Dict[str, Any]]:
        """Detect the same locator repeatedly failing across the window."""
        locator_failures = collections.Counter()
        for s in self._window:
            if not s.success and s.target:
                locator_failures[s.target] += 1

        for target, fails in locator_failures.items():
            if fails >= 3:
                return 1.0, {"target": target, "failures": fails}
            elif fails == 2:
                return 0.85, {"target": target, "failures": fails}

        return 0.0, {}

    def _detect_repeated_readiness_timeouts(self) -> Tuple[float, Dict[str, Any]]:
        """Detect repeated session readiness timeouts."""
        timeouts = sum(1 for s in self._window if not s.readiness_ok)
        if timeouts >= 3:
            return 1.0, {"readiness_timeouts": timeouts}
        elif timeouts >= 2:
            return 0.85, {"readiness_timeouts": timeouts}
        return 0.0, {}

    def _detect_repeated_action_exceptions(self) -> Tuple[float, Dict[str, Any]]:
        """Detect repeated exceptions or unhandled action failures."""
        exceptions = sum(1 for s in self._window if s.action_exception or (not s.success and s.error_message))
        if exceptions >= 3:
            return 1.0, {"exceptions": exceptions}
        elif exceptions >= 2:
            return 0.80, {"exceptions": exceptions}
        return 0.0, {}

    def _detect_mechanical_success_zero_delta(self) -> Tuple[float, Dict[str, Any]]:
        """Detect actions returning success=True but resulting in 0 state delta."""
        zero_delta_streak = 0
        for s in reversed(self._window):
            if s.is_neutral:
                continue
            if s.success and not s.state_changed and not s.url_changed and s.hamming_distance == 0:
                zero_delta_streak += 1
            else:
                break

        if zero_delta_streak >= 3:
            return 1.0, {"zero_delta_streak": zero_delta_streak}
        elif zero_delta_streak == 2:
            return 0.80, {"zero_delta_streak": zero_delta_streak}
        elif zero_delta_streak == 1:
            return 0.40, {"zero_delta_streak": zero_delta_streak}

        return 0.0, {}

    def _detect_verifier_noop_streak(self) -> Tuple[float, Dict[str, Any]]:
        """Detect a trailing run of verifier-flagged no-op actions.

        Consumes the StateVerifier's own judgement (`verification_is_stuck`: a mutating
        verb reported success but the state hash, URL, and DOM node counts were unchanged)
        rather than re-deriving it, so an action that succeeds mechanically while changing
        nothing escalates instead of being accepted as progress.

        Returns:
            Tuple of (score, evidence). A single no-op scores 0.40 so it is recorded but
            below the default 0.75 threshold; two consecutive no-ops reach 0.80.
        """
        streak = 0
        targets: List[str] = []
        for s in reversed(self._window):
            if s.is_neutral:
                continue
            if s.verification_is_stuck:
                streak += 1
                if s.target:
                    targets.append(s.target)
            else:
                break

        if streak == 0:
            return 0.0, {}

        detail: Dict[str, Any] = {"verifier_noop_streak": streak}
        if targets:
            detail["targets"] = targets[:5]

        if streak >= 3:
            return 1.0, detail
        if streak == 2:
            return 0.80, detail
        return 0.40, detail
