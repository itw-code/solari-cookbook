"""Deterministic Mock Cortex Client for ARC (Phase 3A).

Provides deterministic recovery plans without network access for:
- LOCATOR_NOT_FOUND: Scroll into view, wait, retry with fallback locator.
- STATE_NOT_CHANGED: Wait for stability, retry action, assert visibility.
- ACTION_TIMEOUT: Extend timeout, wait for page idle, retry action.
- READINESS_TIMEOUT: Wait for stability, retry action.
- ESCALATION_REQUIRED: Dismiss blockers (Escape), refresh state, retry.

Fulfills Task 5 Requirements.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from ..schemas import (
    CortexResponse,
    EscalationPayload,
    EscalationReason,
    PlanSource,
    RecoveryPlan,
)
from .cortex_interface import CortexClient

logger = logging.getLogger("arc_cua.cortex.mock_cortex")


class MockCortexClient(CortexClient):
    """Deterministic, zero-network mock Cortex generating typed recovery action plans."""

    def __init__(self, model_name: str = "mock-cortex-v1"):
        self.model_name = model_name

    def recover(self, payload: EscalationPayload) -> CortexResponse:
        """Process an escalation payload and return a typed RecoveryPlan deterministically."""
        start_time = time.perf_counter()
        plan_id = f"plan-{payload.reason.value.lower()}-{uuid.uuid4().hex[:6]}"

        reason = payload.reason
        failure_details = payload.failure_details or {}
        step_history = payload.step_history or []
        last_action = step_history[-1] if step_history else None
        last_verb = last_action.verb if last_action else "CLICK"
        last_target = (last_action.target_selector if last_action else None) or failure_details.get("target") or "button"
        last_value = last_action.value if last_action else failure_details.get("value")

        actions: List[Dict[str, Any]] = []
        expected_outcome = ""
        stop_condition = ""
        confidence = 0.85

        if reason == EscalationReason.LOCATOR_NOT_FOUND:
            target = failure_details.get("target") or last_target or "button"
            fallback_target = failure_details.get("fallback_target") or f"text={target}"
            actions = [
                {"verb": "SCROLL", "target": "body", "value": "down"},
                {"verb": "WAIT", "target": None, "value": "500"},
                {"verb": last_verb, "target": fallback_target, "value": last_value},
            ]
            expected_outcome = f"Target '{target}' brought into view via scroll and activated using fallback locator"
            stop_condition = "target_found_and_action_succeeded"
            confidence = 0.88

        elif reason == EscalationReason.STATE_NOT_CHANGED:
            actions = [
                {"verb": "WAIT", "target": None, "value": "1000"},
                {"verb": last_verb, "target": last_target, "value": last_value},
                {"verb": "ASSERT_VISIBLE", "target": last_target or "body", "value": None},
            ]
            expected_outcome = "State change produced after waiting for async settling and retrying action"
            stop_condition = "state_delta_verified"
            confidence = 0.80

        elif reason == EscalationReason.ACTION_TIMEOUT:
            actions = [
                {"verb": "WAIT", "target": None, "value": "1500"},
                {"verb": last_verb, "target": last_target, "value": last_value, "timeout_ms": 10000},
            ]
            expected_outcome = "Action succeeds after extending execution timeout and waiting for page idle"
            stop_condition = "action_executed_successfully"
            confidence = 0.85

        elif reason == EscalationReason.READINESS_TIMEOUT:
            actions = [
                {"verb": "WAIT", "target": None, "value": "2000"},
                {"verb": last_verb, "target": last_target, "value": last_value},
            ]
            expected_outcome = "Session readiness restored after awaiting network stability"
            stop_condition = "session_ready_and_action_executed"
            confidence = 0.82

        elif reason == EscalationReason.ESCALATION_REQUIRED:
            actions = [
                {"verb": "PRESS_KEY", "target": "body", "value": "Escape"},
                {"verb": "WAIT", "target": None, "value": "500"},
                {"verb": last_verb, "target": last_target, "value": last_value},
            ]
            expected_outcome = "Dismiss potential modal/blocker with Escape and retry target action"
            stop_condition = "blocker_cleared"
            confidence = 0.78

        elif reason == EscalationReason.CYCLIC_LOOP:
            actions = [
                {"verb": "PRESS_KEY", "target": "body", "value": "Escape"},
                {"verb": "WAIT", "target": None, "value": "1000"},
                {"verb": "SCROLL", "target": "body", "value": "up"},
            ]
            expected_outcome = "Break cyclic loop by clearing overlays and resetting scroll position"
            stop_condition = "loop_broken"
            confidence = 0.75

        else:
            # Generic fallback plan for other reasons (e.g. CANVAS_OCCLUSION, PROCESS_CRASH, etc.)
            actions = [
                {"verb": "WAIT", "target": None, "value": "1000"},
                {"verb": "NOOP", "target": None, "value": None},
            ]
            expected_outcome = f"Generic recovery fallback for {reason.value}"
            stop_condition = "recovery_noop_complete"
            confidence = 0.60

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        plan = RecoveryPlan(
            plan_id=plan_id,
            source=PlanSource.MOCK,
            actions=actions,
            expected_outcome=expected_outcome,
            stop_condition=stop_condition,
            confidence=confidence,
            metadata={"escalation_reason": reason.value, "model": self.model_name},
        )

        return CortexResponse(
            plan=plan,
            raw_response=None,
            model=self.model_name,
            latency_ms=latency_ms,
            tokens_used=0,  # Zero LLM tokens for mock Cortex
            cost_usd=0.0,
            success=True,
            metadata={"plan_id": plan_id},
        )
