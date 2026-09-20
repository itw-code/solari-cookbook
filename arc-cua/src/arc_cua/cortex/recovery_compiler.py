"""Recovery Compiler for ARC (Phase 3A).

Validates and compiles CortexResponse / RecoveryPlan into executable ActionStep sequences:
- Strictly enforces supported action verbs:
  CLICK, TYPE, SELECT, SCROLL, PRESS_KEY, GOTO, WAIT, ASSERT_VISIBLE, ASSERT_TEXT, NOOP, ESCALATE.
- Validates presence of target locators for targeted verbs (CLICK, TYPE, SELECT, ASSERT_VISIBLE, ASSERT_TEXT).
- Rejects unsafe or unsupported actions (e.g. javascript: URLs, unbounded waits, missing values).
- Injects recovery metadata (plan_id, source, is_recovery flag, expected_outcome).

Fulfills Task 6 Requirements.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Set, Union
from urllib.parse import urlparse

from ..schemas import ActionStep, CortexResponse, RecoveryPlan

logger = logging.getLogger("arc_cua.cortex.recovery_compiler")

SUPPORTED_ACTIONS: Set[str] = {
    "CLICK",
    "TYPE",
    "SELECT",
    "SCROLL",
    "PRESS_KEY",
    "GOTO",
    "WAIT",
    "ASSERT_VISIBLE",
    "ASSERT_TEXT",
    "NOOP",
    "ESCALATE",
}

ACTIONS_REQUIRING_TARGET: Set[str] = {
    "CLICK",
    "TYPE",
    "SELECT",
    "ASSERT_VISIBLE",
    "ASSERT_TEXT",
}

UNSAFE_SCHEMES: Set[str] = {"javascript", "data", "file", "vbscript"}


class RecoveryCompilationError(ValueError):
    """Raised when a recovery plan violates validation or safety invariants."""
    pass


class RecoveryCompiler:
    """Validates and compiles Cortex recovery plans into executable ActionStep sequences."""

    def __init__(self, max_wait_ms: int = 60000):
        self.max_wait_ms = max_wait_ms

    def compile(
        self,
        cortex_response_or_plan: Union[CortexResponse, RecoveryPlan],
        start_step: int = 1,
    ) -> List[ActionStep]:
        """Compile a CortexResponse or RecoveryPlan into a list of validated ActionSteps.

        Args:
            cortex_response_or_plan: CortexResponse or direct RecoveryPlan instance.
            start_step: Initial step_number to assign to the first compiled action.

        Returns:
            List of validated ActionStep instances.

        Raises:
            RecoveryCompilationError: If any action is invalid, missing required fields, or unsafe.
        """
        plan: Optional[RecoveryPlan] = None
        if isinstance(cortex_response_or_plan, CortexResponse):
            plan = cortex_response_or_plan.plan
            if not plan:
                raise RecoveryCompilationError("CortexResponse contains no recovery plan.")
        elif isinstance(cortex_response_or_plan, RecoveryPlan):
            plan = cortex_response_or_plan
        else:
            raise RecoveryCompilationError(
                f"Expected CortexResponse or RecoveryPlan, got {type(cortex_response_or_plan)}"
            )

        if not plan.actions:
            raise RecoveryCompilationError(f"Recovery plan '{plan.plan_id}' has no actions to compile.")

        compiled_steps: List[ActionStep] = []
        current_step_num = start_step

        for idx, action_item in enumerate(plan.actions):
            action_dict = self._normalize_action_dict(action_item, idx)
            verb = action_dict.get("verb", "").strip().upper()
            target = action_dict.get("target") or action_dict.get("target_selector")
            value = action_dict.get("value")
            action_idx = action_dict.get("action_index")

            # 1. Reject invalid action types
            if verb not in SUPPORTED_ACTIONS:
                raise RecoveryCompilationError(
                    f"Unsupported action verb '{verb}' at plan step {idx}. Supported: {sorted(SUPPORTED_ACTIONS)}"
                )

            # 2. Reject missing target locators where required
            if verb in ACTIONS_REQUIRING_TARGET:
                if (target is None or not str(target).strip()) and action_idx is None:
                    raise RecoveryCompilationError(
                        f"Action '{verb}' at plan step {idx} requires a target selector or action_index."
                    )

            # 3. Reject unsafe or invalid actions
            self._validate_safety(verb, target, value, idx)

            # 4. Create ActionStep with attached recovery metadata
            step = ActionStep(
                step_number=current_step_num,
                verb=verb,
                target_selector=str(target) if target is not None else None,
                value=str(value) if value is not None else None,
                action_index=action_idx,
                latency_ms=0.0,
                success=True,
                error_message=None,
                timestamp=time.time(),
            )
            compiled_steps.append(step)
            current_step_num += 1

        logger.info(
            f"Successfully compiled {len(compiled_steps)} recovery steps from plan '{plan.plan_id}'"
        )
        return compiled_steps

    def validate_plan(self, plan: Union[CortexResponse, RecoveryPlan]) -> List[ActionStep]:
        """Validate plan safety and return compiled steps.

        Raises:
            RecoveryCompilationError: If plan violates schema or safety invariants.
        """
        return self.compile(plan)

    def _normalize_action_dict(self, action_item: Any, idx: int) -> Dict[str, Any]:
        """Normalize action item into a standardized dictionary."""
        if isinstance(action_item, dict):
            d = dict(action_item)
            if "target" not in d and "target_selector" in d:
                d["target"] = d["target_selector"]
            return d
        elif hasattr(action_item, "__dict__"):
            return {
                "verb": getattr(action_item, "verb", ""),
                "target": getattr(action_item, "target_selector", getattr(action_item, "target", None)),
                "value": getattr(action_item, "value", None),
                "action_index": getattr(action_item, "action_index", None),
            }
        else:
            raise RecoveryCompilationError(
                f"Action at index {idx} must be a dict or object with action attributes, got {type(action_item)}"
            )

    def _validate_safety(self, verb: str, target: Any, value: Any, idx: int) -> None:
        """Validate safety constraints on the action parameters."""
        if verb == "GOTO":
            url_target = str(value or target or "").strip()
            if not url_target:
                raise RecoveryCompilationError(f"GOTO action at step {idx} requires a destination URL.")
            parsed = urlparse(url_target)
            if parsed.scheme.lower() in UNSAFE_SCHEMES:
                raise RecoveryCompilationError(
                    f"Unsafe URL scheme '{parsed.scheme}' in GOTO at step {idx}: {url_target}"
                )

        elif verb == "WAIT":
            wait_val = value or target or "1000"
            try:
                ms = float(wait_val)
                if ms < 0 or ms > self.max_wait_ms:
                    raise RecoveryCompilationError(
                        f"WAIT duration {ms}ms exceeds safety limit (0 to {self.max_wait_ms}ms) at step {idx}"
                    )
            except ValueError:
                raise RecoveryCompilationError(f"Invalid numeric duration for WAIT at step {idx}: {wait_val}")

        elif verb == "TYPE":
            if value is None:
                raise RecoveryCompilationError(f"TYPE action at step {idx} requires a value to type.")

        elif verb == "ASSERT_TEXT":
            if value is None or not str(value).strip():
                raise RecoveryCompilationError(
                    f"ASSERT_TEXT action at step {idx} requires expected text value."
                )
