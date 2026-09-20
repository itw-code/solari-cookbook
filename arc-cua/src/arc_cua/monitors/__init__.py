"""Monitors and Escalation Subsystem for ARC (Phase 3A & 3B).

Provides:
- StuckMonitor: Sliding-window deterministic failure and loop detector.
- MilestoneMonitor: Heuristic goal progression and state advance detector.
- EscalationController: Policy governor managing local recovery vs Cortex escalation and budgets.
- MonitorModel, MonitorPrediction, MonitorWindow: Abstract prediction contracts.
- HeuristicStuckModelAdapter, HeuristicMilestoneModelAdapter: Pluggable model wrappers.
- FeatureBuilder, WindowFeatures: Deterministic telemetry feature extractor.
- SemanticProgressEstimator, HeuristicProgressEstimator, EmbeddingProgressEstimator: Goal progression estimators.
- TransformerMonitorAdapter, LEARNED_MONITOR_UNAVAILABLE: Optional learned monitor support.
"""

from .escalation_controller import EscalationController
from .feature_builder import FeatureBuilder, WindowFeatures
from .heuristic_adapter import (
    HeuristicMilestoneModelAdapter,
    HeuristicStuckModelAdapter,
    to_step_telemetry,
)
from .milestone_monitor import MilestoneMonitor
from .model_interface import MonitorModel, MonitorPrediction, MonitorWindow
from .semantic_progress import (
    EmbeddingProgressEstimator,
    HeuristicProgressEstimator,
    SemanticProgressEstimator,
)
from .stuck_monitor import StepTelemetry, StuckMonitor
from .transformer_adapter import (
    LEARNED_MONITOR_UNAVAILABLE,
    TransformerMonitorAdapter,
)

__all__ = [
    "StuckMonitor",
    "StepTelemetry",
    "MilestoneMonitor",
    "EscalationController",
    "MonitorModel",
    "MonitorPrediction",
    "MonitorWindow",
    "HeuristicStuckModelAdapter",
    "HeuristicMilestoneModelAdapter",
    "FeatureBuilder",
    "WindowFeatures",
    "SemanticProgressEstimator",
    "HeuristicProgressEstimator",
    "EmbeddingProgressEstimator",
    "TransformerMonitorAdapter",
    "LEARNED_MONITOR_UNAVAILABLE",
    "to_step_telemetry",
]
