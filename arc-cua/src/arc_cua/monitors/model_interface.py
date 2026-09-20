"""Monitor Model Interface for ARC (Phase 3B Task 3).

Defines standard pluggable contracts for both heuristic and learned monitor predictors:
- MonitorModel base class
- MonitorPrediction container (score, reason, evidence, model_name)
- MonitorWindow container supporting TrajectoryWindow conversion
"""

from __future__ import annotations

import abc
import dataclasses
from typing import Any, Dict, List, Optional, Union

from ..schemas import TrajectoryRecord, TrajectoryWindow
from .stuck_monitor import StepTelemetry


@dataclasses.dataclass
class MonitorPrediction:
    """Standardized output from any monitor model (heuristic, transformer, or LLM)."""
    score: float
    reason: str
    evidence: Dict[str, Any] = dataclasses.field(default_factory=dict)
    model_name: str = "unknown"
    is_positive: bool = False
    confidence: float = 1.0
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class MonitorWindow:
    """Window of execution context provided to monitor models for prediction."""
    window_id: str
    current_step: Any  # TrajectoryRecord or StepTelemetry
    history: List[Any] = dataclasses.field(default_factory=list)
    task_goal: str = ""
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

    @classmethod
    def from_trajectory_window(
        cls, trajectory_window: TrajectoryWindow, task_goal: str = ""
    ) -> MonitorWindow:
        """Create a MonitorWindow from an existing TrajectoryWindow."""
        goal = task_goal or trajectory_window.current_step.task_id or ""
        return cls(
            window_id=trajectory_window.window_id,
            current_step=trajectory_window.current_step,
            history=list(trajectory_window.history),
            task_goal=goal,
            metadata=dict(trajectory_window.metadata),
        )

    @property
    def steps(self) -> List[Any]:
        """Return full sequential window of steps (history + current)."""
        return self.history + [self.current_step]


class MonitorModel(abc.ABC):
    """Abstract base class for all pluggable monitor predictors."""

    @property
    @abc.abstractmethod
    def model_name(self) -> str:
        """Human-readable identifier of the model."""
        pass

    @abc.abstractmethod
    def predict(self, window: Union[MonitorWindow, TrajectoryWindow]) -> MonitorPrediction:
        """Evaluate a window of execution steps and return a MonitorPrediction."""
        pass


def to_step_telemetry(item: Any) -> StepTelemetry:
    """Convert a TrajectoryRecord, dict, or StepTelemetry into StepTelemetry."""
    if isinstance(item, StepTelemetry):
        return item

    if isinstance(item, TrajectoryRecord):
        return StepTelemetry(
            step_id=item.step_id,
            verb=item.action_type,
            target=item.target_locator,
            value=item.metadata.get("value") if item.metadata else None,
            success=item.execution_success,
            error_message=item.error_type if item.error_detected else None,
            state_changed=item.state_changed,
            state_hash=int(item.state_hash_after) if str(item.state_hash_after).isdigit() else 0,
            previous_state_hash=int(item.state_hash_before) if str(item.state_hash_before).isdigit() else 0,
            hamming_distance=item.hamming_distance,
            url_changed=item.url_changed,
            url=item.url_after,
            readiness_ok=item.readiness_passed,
            action_exception=(not item.execution_success or item.error_detected),
            is_neutral=(item.action_type.upper() in {"WAIT", "NOOP"}),
            verification_is_stuck=(not item.state_changed and item.action_type.upper() not in {"WAIT", "NOOP"}),
            metadata=item.metadata or {},
        )

    if isinstance(item, dict):
        return StepTelemetry(
            step_id=item.get("step_id", 0),
            verb=item.get("action_type", item.get("verb", "")),
            target=item.get("target_locator", item.get("target")),
            value=item.get("value"),
            success=item.get("execution_success", item.get("success", True)),
            error_message=item.get("error_type", item.get("error_message")),
            state_changed=item.get("state_changed", False),
            state_hash=int(item.get("state_hash_after", item.get("state_hash", 0)) or 0),
            previous_state_hash=int(item.get("state_hash_before", item.get("previous_state_hash", 0)) or 0),
            hamming_distance=item.get("hamming_distance", 0),
            url_changed=item.get("url_changed", False),
            url=item.get("url_after", item.get("url")),
            readiness_ok=item.get("readiness_passed", item.get("readiness_ok", True)),
            action_exception=bool(item.get("error_detected") or not item.get("execution_success", True)),
            metadata=item.get("metadata", {}),
        )

    # Fallback default
    return StepTelemetry(step_id=1)
