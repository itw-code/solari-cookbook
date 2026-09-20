"""Heuristic Monitor Model Adapters for ARC (Phase 3B Task 3).

Wraps existing deterministic Phase 3A StuckMonitor and MilestoneMonitor:
- Implements MonitorModel interface.
- Converts TrajectoryWindows and StepTelemetries.
- Provides sub-10ms deterministic baseline predictions.
- No external model dependencies.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Sequence, Union

from ..schemas import TrajectoryRecord, TrajectoryWindow
from .milestone_monitor import MilestoneMonitor
from .model_interface import (
    MonitorModel,
    MonitorPrediction,
    MonitorWindow,
    to_step_telemetry,
)
from .stuck_monitor import StepTelemetry, StuckMonitor

logger = logging.getLogger("arc_cua.monitors.heuristic_adapter")


class HeuristicStuckModelAdapter(MonitorModel):
    """Adapter wrapping deterministic StuckMonitor into MonitorModel interface."""

    def __init__(self, stuck_monitor: Optional[StuckMonitor] = None):
        self._monitor = stuck_monitor or StuckMonitor()

    @property
    def model_name(self) -> str:
        return "heuristic-stuck-v1"

    def predict(self, window: Union[MonitorWindow, TrajectoryWindow]) -> MonitorPrediction:
        """Evaluate a window of steps and return stuck prediction."""
        # Convert to steps
        if isinstance(window, TrajectoryWindow):
            steps = window.steps
        else:
            steps = window.steps

        # Create a clean monitor instance to evaluate this window deterministically
        temp_monitor = StuckMonitor(
            window_size=self._monitor.window_size,
            stuck_threshold=self._monitor.stuck_threshold,
        )

        last_sig = None
        for step in steps:
            telemetry = to_step_telemetry(step)
            last_sig = temp_monitor.evaluate_step(telemetry)

        if not last_sig:
            return MonitorPrediction(
                score=0.0,
                reason="empty_window",
                evidence={},
                model_name=self.model_name,
                is_positive=False,
            )

        return MonitorPrediction(
            score=last_sig.stuck_score,
            reason=last_sig.reason,
            evidence=last_sig.evidence,
            model_name=self.model_name,
            is_positive=last_sig.is_stuck,
            confidence=1.0,
        )


class HeuristicMilestoneModelAdapter(MonitorModel):
    """Adapter wrapping deterministic MilestoneMonitor into MonitorModel interface."""

    def __init__(self, milestone_monitor: Optional[MilestoneMonitor] = None):
        self._monitor = milestone_monitor or MilestoneMonitor()

    @property
    def model_name(self) -> str:
        return "heuristic-milestone-v1"

    def predict(self, window: Union[MonitorWindow, TrajectoryWindow]) -> MonitorPrediction:
        """Evaluate the current step in window and return milestone prediction."""
        current_step = window.current_step
        telemetry = to_step_telemetry(current_step)

        goal = getattr(window, "task_goal", "") or (
            current_step.task_id if isinstance(current_step, TrajectoryRecord) else ""
        )

        milestone_sig = self._monitor.evaluate(telemetry, goal=goal)

        return MonitorPrediction(
            score=milestone_sig.milestone_score,
            reason=milestone_sig.milestone_type,
            evidence=milestone_sig.evidence,
            model_name=self.model_name,
            is_positive=milestone_sig.is_milestone,
            confidence=1.0,
            metadata={"goal": goal},
        )
