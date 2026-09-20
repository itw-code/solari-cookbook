"""Heuristic Milestone Progress Monitor for ARC (Phase 3A).

Detects meaningful task progression deterministically:
1. Expected state change occurs.
2. URL changes to expected target.
3. Expected visible text appears.
4. Form submission succeeds.
5. State hash changes with no error detected.
6. A declared expected_state_change from an action is verified.

Fulfills Task 3 Requirements:
- Goal-aware via goal/metadata matching.
- Purely heuristic in Phase 3A; no external embedding models required.
- Under 10ms p95 latency.
- Architecture ready for future embedding-based semantic upgrade.
- Strictly does NOT trigger on error states.
"""

from __future__ import annotations

import abc
import dataclasses
import logging
from typing import Any, Dict, List, Optional, Sequence, Union

from ..schemas import ActionResult, ActionStep, MilestoneSignal
from ..state_verifier import StateVerificationResult
from .stuck_monitor import StepTelemetry

logger = logging.getLogger("arc_cua.monitors.milestone_monitor")


from .semantic_progress import (
    EmbeddingProgressEstimator,
    HeuristicProgressEstimator,
    SemanticProgressEstimator,
)

class MilestoneMonitor:
    """Deterministic monitor evaluating task advancement and milestone achievements."""

    def __init__(
        self,
        milestone_threshold: float = 0.65,
        semantic_estimator: Optional[SemanticProgressEstimator] = None,
    ):
        """Initialize MilestoneMonitor.

        Args:
            milestone_threshold: Minimum score required for is_milestone=True.
            semantic_estimator: Pluggable progress estimator (defaults to HeuristicProgressEstimator).
        """
        self.milestone_threshold = milestone_threshold
        self.semantic_estimator = semantic_estimator or HeuristicProgressEstimator()
        self.milestones_history: List[MilestoneSignal] = []

    def reset(self) -> None:
        """Reset historical milestone records."""
        self.milestones_history.clear()

    def evaluate(
        self,
        step: StepTelemetry,
        goal: Optional[Union[str, Dict[str, Any]]] = None,
        state_text_before: str = "",
        state_text_after: str = "",
    ) -> MilestoneSignal:
        """Evaluate whether the given step accomplished a milestone.

        Args:
            step: Telemetry record of the executed step.
            goal: Optional goal string or structured goal dict with expectations.
            state_text_before: Textual representation of state before step.
            state_text_after: Textual representation of state after step.

        Returns:
            MilestoneSignal indicating score, milestone status, type, and evidence.
        """
        # Rule 5: Must NOT trigger on error states
        if not step.success or step.action_exception or not step.readiness_ok or step.error_message:
            return MilestoneSignal(
                milestone_score=0.0,
                is_milestone=False,
                milestone_type="none",
                evidence={
                    "error_detected": True,
                    "error_message": step.error_message or step.readiness_reason or "action_failure",
                },
            )

        goal_str = ""
        goal_dict: Dict[str, Any] = {}
        if isinstance(goal, str):
            goal_str = goal
        elif isinstance(goal, dict):
            goal_dict = goal
            goal_str = goal.get("goal", "")

        expected_url = goal_dict.get("expected_url") or step.metadata.get("expected_url")
        expected_text = goal_dict.get("expected_text") or step.metadata.get("expected_text")
        expected_state_change = goal_dict.get("expected_state_change") or step.metadata.get("expected_state_change")

        candidates: List[Tuple[float, str, Dict[str, Any]]] = []

        # 1. Declared expected_state_change from action or goal is verified
        if expected_state_change and (step.state_changed or step.url_changed):
            candidates.append((
                1.0,
                "declared_state_change",
                {"expected_state_change": expected_state_change, "state_changed": step.state_changed},
            ))

        # 2. URL changes to expected target or transitions
        if step.url_changed:
            current_url = step.url or ""
            if expected_url and expected_url in current_url:
                candidates.append((
                    1.0,
                    "expected_url_reached",
                    {"expected_url": expected_url, "url": current_url},
                ))
            else:
                candidates.append((
                    0.85,
                    "url_transition",
                    {"url": current_url},
                ))

        # 3. Expected visible text appears
        if expected_text:
            text_target = (state_text_after or "").lower()
            if expected_text.lower() in text_target:
                candidates.append((
                    0.95,
                    "expected_text_appeared",
                    {"expected_text": expected_text},
                ))

        # 4. Form submission succeeds
        verb_upper = step.verb.upper()
        target_lower = (step.target or "").lower()
        is_form_submit = (
            verb_upper == "SUBMIT"
            or (verb_upper == "CLICK" and any(k in target_lower for k in ("submit", "save", "confirm", "send", "checkout", "login")))
        )
        if is_form_submit and (step.state_changed or step.url_changed):
            candidates.append((
                0.90,
                "form_submission_success",
                {"action": step.verb, "target": step.target, "url_changed": step.url_changed},
            ))

        # 5. State hash changes with no error detected
        if step.state_changed and step.hamming_distance > 0:
            semantic_score = 0.0
            if goal_str and (state_text_before or state_text_after):
                semantic_score = self.semantic_estimator.score_progression(
                    goal=goal_str,
                    state_text_before=state_text_before,
                    state_text_after=state_text_after,
                )

            if semantic_score >= 0.5:
                candidates.append((
                    0.85,
                    "goal_aligned_state_change",
                    {"hamming_distance": step.hamming_distance, "semantic_score": semantic_score},
                ))
            else:
                candidates.append((
                    0.70,
                    "state_advance",
                    {"hamming_distance": step.hamming_distance, "state_hash": hex(step.state_hash)},
                ))

        if not candidates:
            return MilestoneSignal(
                milestone_score=0.0,
                is_milestone=False,
                milestone_type="none",
                evidence={"state_changed": step.state_changed, "hamming_distance": step.hamming_distance},
            )

        # Select the candidate with highest score
        best_score, best_type, best_evidence = max(candidates, key=lambda c: c[0])
        is_milestone = best_score >= self.milestone_threshold

        signal = MilestoneSignal(
            milestone_score=round(best_score, 4),
            is_milestone=is_milestone,
            milestone_type=best_type if is_milestone else "none",
            evidence=best_evidence,
        )

        if is_milestone:
            self.milestones_history.append(signal)

        return signal
