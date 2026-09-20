"""Datasets module for ARC (Phase 3B).

Provides trajectory collection, windowing, redaction, and auto-labeling pipelines.
"""

from .labeler import AutoLabeler, LabelResult, WindowLabelSummary
from .trajectory_collector import TrajectoryCollector

__all__ = [
    "TrajectoryCollector",
    "AutoLabeler",
    "LabelResult",
    "WindowLabelSummary",
]
