"""Auto-Labeling Pipeline for ARC (Phase 3B Task 2).

Generates deterministic, offline labels for stuck and milestone events:
- Evaluates TrajectoryWindows against rule-based operational heuristics.
- Generates stuck labels: consecutive no-change, locator repeat failure, cyclic oscillation,
  readiness timeouts, and action exceptions.
- Generates milestone labels: state change verification, target URL reached, text appearance,
  and clean progress state transitions.
- Exports structured outputs to artifacts/phase3b/labeled/ (stuck.jsonl, milestone.jsonl, summary.json).
"""

from __future__ import annotations

import collections
import dataclasses
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from ..schemas import TrajectoryRecord, TrajectoryWindow

logger = logging.getLogger("arc_cua.datasets.labeler")


@dataclasses.dataclass
class LabelResult:
    """Label prediction for a single TrajectoryWindow."""
    window_id: str
    stuck: bool
    milestone: bool
    stuck_reason: Optional[str] = None
    milestone_reason: Optional[str] = None
    label_source: str = "heuristic"
    confidence: float = 1.0
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class WindowLabelSummary:
    """Aggregated summary of labeled trajectory dataset."""
    total_windows: int
    stuck_positive: int
    stuck_negative: int
    milestone_positive: int
    milestone_negative: int
    label_source: str = "heuristic"
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


class AutoLabeler:
    """Deterministic auto-labeler for TrajectoryWindows."""

    def __init__(self, use_model: bool = False, model_name: Optional[str] = None):
        """Initialize AutoLabeler.

        Args:
            use_model: Whether to use an external/learned model for labeling (default: False).
            model_name: Name of model if use_model is True.
        """
        self.use_model = use_model
        self.model_name = model_name
        self.label_source = f"model:{model_name}" if use_model else "heuristic"

    def label_window(self, window: TrajectoryWindow) -> LabelResult:
        """Label a TrajectoryWindow using deterministic heuristics or model.

        Heuristic stuck conditions:
        1. Three consecutive no-state-change actions.
        2. Same locator failed at least twice.
        3. Cyclic state hash oscillation.
        4. Repeated readiness timeout.
        5. Repeated action exception.

        Heuristic milestone conditions:
        1. Expected state change verified.
        2. URL reached expected target.
        3. Expected visible text appeared.
        4. State changed and no error detected.
        """
        if self.use_model:
            # Placeholder for optional learned labeler if enabled in the future
            return self._label_with_model(window)

        return self._label_heuristic(window)

    def _label_heuristic(self, window: TrajectoryWindow) -> LabelResult:
        steps: List[TrajectoryRecord] = window.steps
        stuck = False
        stuck_reasons: List[str] = []

        milestone = False
        milestone_reasons: List[str] = []

        # ----------------------------------------------------
        # Stuck Heuristic 1: Three consecutive no-state-change actions
        # ----------------------------------------------------
        consecutive_no_change = 0
        for step in steps:
            if not step.state_changed:
                consecutive_no_change += 1
            else:
                consecutive_no_change = 0
        if consecutive_no_change >= 3:
            stuck = True
            stuck_reasons.append(f"consecutive_no_state_change({consecutive_no_change})")

        # ----------------------------------------------------
        # Stuck Heuristic 2: Same locator failed at least twice
        # ----------------------------------------------------
        locator_failures: collections.Counter[str] = collections.Counter()
        for step in steps:
            if (not step.execution_success or step.error_detected) and step.target_locator:
                locator_failures[step.target_locator] += 1
        for loc, count in locator_failures.items():
            if count >= 2:
                stuck = True
                stuck_reasons.append(f"repeated_locator_failure({loc}, count={count})")
                break

        # ----------------------------------------------------
        # Stuck Heuristic 3: Cyclic state hash oscillation
        # ----------------------------------------------------
        # e.g. A -> B -> A, or visited hashes repeated non-consecutively
        hash_history: List[Union[int, str]] = []
        for step in steps:
            h = step.state_hash_after
            if h and h != 0 and h != "0":
                hash_history.append(h)

        if len(hash_history) >= 3:
            for i in range(len(hash_history) - 2):
                if hash_history[i] == hash_history[i + 2] and hash_history[i] != hash_history[i + 1]:
                    stuck = True
                    stuck_reasons.append(f"cyclic_state_oscillation({hash_history[i]}->{hash_history[i+1]}->{hash_history[i+2]})")
                    break

        # ----------------------------------------------------
        # Stuck Heuristic 4: Repeated readiness timeout
        # ----------------------------------------------------
        readiness_timeouts = sum(
            1 for s in steps if not s.readiness_passed or (s.error_type and "readiness" in s.error_type.lower())
        )
        if readiness_timeouts >= 2:
            stuck = True
            stuck_reasons.append(f"repeated_readiness_timeout(count={readiness_timeouts})")

        # ----------------------------------------------------
        # Stuck Heuristic 5: Repeated action exception
        # ----------------------------------------------------
        action_exceptions = sum(
            1 for s in steps if not s.execution_success or s.error_detected
        )
        if action_exceptions >= 2:
            stuck = True
            stuck_reasons.append(f"repeated_action_exception(count={action_exceptions})")

        # ----------------------------------------------------
        # Milestone Heuristics (Evaluated on current step)
        # ----------------------------------------------------
        curr = window.current_step
        meta = curr.metadata or {}

        # 1. Expected state change verified
        if meta.get("expected_state_change_verified") is True:
            milestone = True
            milestone_reasons.append("expected_state_change_verified")

        # 2. URL reached expected target
        if curr.url_changed and curr.execution_success:
            milestone = True
            milestone_reasons.append(f"url_target_reached({curr.url_after})")
        elif meta.get("url_reached_target") is True:
            milestone = True
            milestone_reasons.append("url_reached_target")

        # 3. Expected visible text appeared
        if meta.get("visible_text_appeared") is True or meta.get("expected_text_appeared") is True:
            milestone = True
            milestone_reasons.append("visible_text_appeared")

        # 4. State changed and no error detected
        if curr.state_changed and curr.execution_success and not curr.error_detected:
            # Meaningful progression
            milestone = True
            milestone_reasons.append("clean_state_transition")

        return LabelResult(
            window_id=window.window_id,
            stuck=stuck,
            milestone=milestone,
            stuck_reason="; ".join(stuck_reasons) if stuck_reasons else None,
            milestone_reason="; ".join(milestone_reasons) if milestone_reasons else None,
            label_source=self.label_source,
            confidence=1.0,
            metadata={
                "step_id": curr.step_id,
                "action_type": curr.action_type,
                "target_locator": curr.target_locator,
                "state_changed": curr.state_changed,
            },
        )

    def _label_with_model(self, window: TrajectoryWindow) -> LabelResult:
        """Fallback / stub for learned model labeling if enabled."""
        res = self._label_heuristic(window)
        res.label_source = self.label_source
        return res

    def label_dataset(
        self, windows: Sequence[TrajectoryWindow]
    ) -> Tuple[List[LabelResult], WindowLabelSummary]:
        """Label a sequence of TrajectoryWindows and produce an aggregate summary."""
        results: List[LabelResult] = []
        stuck_pos = 0
        milestone_pos = 0

        for window in windows:
            label = self.label_window(window)
            results.append(label)
            if label.stuck:
                stuck_pos += 1
            if label.milestone:
                milestone_pos += 1

        total = len(windows)
        summary = WindowLabelSummary(
            total_windows=total,
            stuck_positive=stuck_pos,
            stuck_negative=total - stuck_pos,
            milestone_positive=milestone_pos,
            milestone_negative=total - milestone_pos,
            label_source=self.label_source,
        )

        return results, summary

    def export_labeled_dataset(
        self,
        windows: Sequence[TrajectoryWindow],
        output_dir: Union[str, Path] = "artifacts/phase3b/labeled",
    ) -> Dict[str, Path]:
        """Label windows and export stuck.jsonl, milestone.jsonl, and summary.json."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        results, summary = self.label_dataset(windows)

        stuck_path = out / "stuck.jsonl"
        milestone_path = out / "milestone.jsonl"
        summary_path = out / "summary.json"

        # Export stuck.jsonl
        with open(stuck_path, "w", encoding="utf-8") as f:
            for w, r in zip(windows, results):
                row = {
                    "window_id": w.window_id,
                    "stuck": r.stuck,
                    "reason": r.stuck_reason,
                    "label_source": r.label_source,
                    "window": w.to_dict(),
                }
                f.write(json.dumps(row) + "\n")

        # Export milestone.jsonl
        with open(milestone_path, "w", encoding="utf-8") as f:
            for w, r in zip(windows, results):
                row = {
                    "window_id": w.window_id,
                    "milestone": r.milestone,
                    "reason": r.milestone_reason,
                    "label_source": r.label_source,
                    "window": w.to_dict(),
                }
                f.write(json.dumps(row) + "\n")

        # Export summary.json
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary.to_dict(), f, indent=2)

        logger.info(
            f"Labeled {len(windows)} windows: "
            f"stuck (+{summary.stuck_positive}/-{summary.stuck_negative}), "
            f"milestone (+{summary.milestone_positive}/-{summary.milestone_negative}). "
            f"Exported to {out}"
        )

        return {
            "stuck": stuck_path,
            "milestone": milestone_path,
            "summary": summary_path,
        }
