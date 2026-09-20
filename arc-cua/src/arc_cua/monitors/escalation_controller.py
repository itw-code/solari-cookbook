"""Escalation Controller for ARC (Phase 3A).

Governs execution transition between Reflex execution, local recovery, and Cortex escalation:
- Requires at least 2 consecutive high stuck scores before escalating (no escalation on single noise).
- Immediate escalation on hard failures (locator exhaustion, page crash, disconnected browser, explicit ESCALATE).
- Enforces post-recovery cooldown of at least 3 Reflex steps.
- Tracks per-task escalation budget (max 3) and recovery budget (max 2).
- Aborts gracefully if budget is exhausted.

Fulfills Task 4 Requirements.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, Dict, List, Optional, Set, Union

from ..schemas import DecisionType, EscalationDecision, MilestoneSignal, StuckSignal
from .stuck_monitor import StepTelemetry

logger = logging.getLogger("arc_cua.monitors.escalation_controller")

HARD_FAILURE_REASONS: Set[str] = {
    "LOCATOR_NOT_FOUND",
    "PAGE_CRASH",
    "PROCESS_CRASH",
    "BROWSER_DISCONNECTED",
    "REPEATED_MODAL",
    "MODAL_BLOCKER",
    "EXPLICIT_ESCALATE",
    "ESCALATE",
    "ESCALATION_REQUIRED",
}


class EscalationController:
    """Policy governor determining whether to continue reflex steps, attempt local recovery, escalate to Cortex, or abort."""

    def __init__(
        self,
        stuck_threshold: float = 0.75,
        consecutive_stuck_required: int = 2,
        cooldown_steps: int = 3,
        max_escalations_per_task: int = 3,
        max_recovery_attempts: int = 2,
        local_recovery_enabled: bool = True,
    ):
        """Initialize the Escalation Controller.

        Args:
            stuck_threshold: Minimum stuck score to count as a stuck event (default: 0.75).
            consecutive_stuck_required: Number of back-to-back stuck events before escalating (default: 2).
            cooldown_steps: Minimum healthy reflex steps enforced after a recovery (default: 3).
            max_escalations_per_task: Maximum permitted escalations before aborting (default: 3).
            max_recovery_attempts: Maximum local recovery attempts before escalating (default: 2).
            local_recovery_enabled: Whether local recovery should be attempted before Cortex escalation.
        """
        self.stuck_threshold = stuck_threshold
        self.consecutive_stuck_required = consecutive_stuck_required
        self.cooldown_steps = cooldown_steps
        self.max_escalations_per_task = max_escalations_per_task
        self.max_recovery_attempts = max_recovery_attempts
        self.local_recovery_enabled = local_recovery_enabled

        # Dynamic state
        self.consecutive_high_stuck: int = 0
        self.cooldown_remaining: int = 0
        self.escalations_used: int = 0
        self.recoveries_used: int = 0
        self.history: List[EscalationDecision] = []

    def reset(self) -> None:
        """Reset internal controller counters and tracking."""
        self.consecutive_high_stuck = 0
        self.cooldown_remaining = 0
        self.escalations_used = 0
        self.recoveries_used = 0
        self.history.clear()

    def activate_cooldown(self, steps: Optional[int] = None) -> None:
        """Enforce cooldown after executing a recovery sequence."""
        self.cooldown_remaining = steps if steps is not None else self.cooldown_steps
        self.consecutive_high_stuck = 0
        logger.info(f"Activated escalation cooldown for {self.cooldown_remaining} steps")

    def decide(
        self,
        stuck_signal: StuckSignal,
        milestone_signal: Optional[MilestoneSignal] = None,
        step: Optional[StepTelemetry] = None,
        hard_failure: Optional[str] = None,
        is_hard_failure: bool = False,
        failure_reason: Optional[str] = None,
    ) -> EscalationDecision:
        """Evaluate signals and make an escalation decision.

        Args:
            stuck_signal: Output from StuckMonitor.
            milestone_signal: Optional output from MilestoneMonitor.
            step: Optional StepTelemetry record.
            hard_failure: Optional hard failure indicator string.
            is_hard_failure: Boolean flag explicitly flagging a hard failure.
            failure_reason: Detailed failure reason string.

        Returns:
            EscalationDecision enum and metadata.
        """
        effective_hard_reason = hard_failure or failure_reason
        normalized_reason = (effective_hard_reason or "").upper()
        hard_detected = (
            is_hard_failure
            or any(h in normalized_reason for h in HARD_FAILURE_REASONS)
            or (step is not None and step.verb.upper() == "ESCALATE")
        )

        # 1. Hard failures escalate immediately (Rule 3)
        if hard_detected:
            if self.escalations_used >= self.max_escalations_per_task:
                decision = EscalationDecision(
                    decision=DecisionType.ABORT,
                    reason=f"max_escalations_exceeded ({self.escalations_used}/{self.max_escalations_per_task}) on hard failure: {effective_hard_reason}",
                    confidence=1.0,
                    metadata={"hard_failure": True, "escalations_used": self.escalations_used},
                )
                self.history.append(decision)
                return decision

            self.escalations_used += 1
            self.consecutive_high_stuck = 0
            decision = EscalationDecision(
                decision=DecisionType.ESCALATE,
                reason=f"hard_failure: {effective_hard_reason or 'unrecoverable_failure'}",
                confidence=1.0,
                required_action="cortex_escalation",
                cooldown_steps=self.cooldown_steps,
                metadata={
                    "hard_failure": True,
                    "escalations_used": self.escalations_used,
                    "reason": effective_hard_reason,
                },
            )
            self.history.append(decision)
            return decision

        # 2. Check Cooldown (Rule 4)
        if self.cooldown_remaining > 0:
            self.cooldown_remaining -= 1
            self.consecutive_high_stuck = 0  # Reset consecutive stuck during cooldown
            decision = EscalationDecision(
                decision=DecisionType.CONTINUE,
                reason=f"cooldown_active (remaining: {self.cooldown_remaining})",
                confidence=1.0,
                cooldown_steps=self.cooldown_remaining,
                metadata={"cooldown_active": True},
            )
            self.history.append(decision)
            return decision

        # 3. Evaluate Stuck Signal
        if stuck_signal.stuck_score >= self.stuck_threshold:
            self.consecutive_high_stuck += 1
            logger.info(
                f"Stuck signal observed: score={stuck_signal.stuck_score} "
                f"({self.consecutive_high_stuck}/{self.consecutive_stuck_required})"
            )

            # Rule 1 & 2: Require at least consecutive_stuck_required before taking action
            if self.consecutive_high_stuck >= self.consecutive_stuck_required:
                # Check if local recovery is eligible
                if self.local_recovery_enabled and self.recoveries_used < self.max_recovery_attempts:
                    self.recoveries_used += 1
                    decision = EscalationDecision(
                        decision=DecisionType.RECOVER_LOCALLY,
                        reason=f"consecutive_stuck ({stuck_signal.reason}) - local recovery attempt {self.recoveries_used}/{self.max_recovery_attempts}",
                        confidence=0.85,
                        required_action="local_recovery",
                        metadata={
                            "recoveries_used": self.recoveries_used,
                            "stuck_score": stuck_signal.stuck_score,
                            "stuck_reason": stuck_signal.reason,
                        },
                    )
                    self.history.append(decision)
                    return decision

                # Local recovery exhausted or disabled -> Escalate to Cortex
                if self.escalations_used >= self.max_escalations_per_task:
                    decision = EscalationDecision(
                        decision=DecisionType.ABORT,
                        reason=f"max_escalations_exceeded ({self.escalations_used}/{self.max_escalations_per_task})",
                        confidence=1.0,
                        metadata={"escalations_used": self.escalations_used},
                    )
                    self.history.append(decision)
                    return decision

                self.escalations_used += 1
                self.consecutive_high_stuck = 0
                decision = EscalationDecision(
                    decision=DecisionType.ESCALATE,
                    reason=f"consecutive_stuck_escalation: {stuck_signal.reason}",
                    confidence=0.95,
                    required_action="cortex_escalation",
                    cooldown_steps=self.cooldown_steps,
                    metadata={
                        "escalations_used": self.escalations_used,
                        "recoveries_used": self.recoveries_used,
                        "stuck_score": stuck_signal.stuck_score,
                    },
                )
                self.history.append(decision)
                return decision

            else:
                # Rule 1: Do not escalate on one noisy failure
                decision = EscalationDecision(
                    decision=DecisionType.CONTINUE,
                    reason=f"single_stuck_observed ({stuck_signal.reason}) - below consecutive threshold",
                    confidence=0.70,
                    metadata={
                        "consecutive_high_stuck": self.consecutive_high_stuck,
                        "stuck_score": stuck_signal.stuck_score,
                    },
                )
                self.history.append(decision)
                return decision

        # 4. Healthy / progressing step
        self.consecutive_high_stuck = 0
        decision = EscalationDecision(
            decision=DecisionType.CONTINUE,
            reason="healthy_progress",
            confidence=1.0,
            metadata={"stuck_score": stuck_signal.stuck_score},
        )
        self.history.append(decision)
        return decision
