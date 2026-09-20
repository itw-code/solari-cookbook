"""Semantic Milestone Progress Estimator for ARC (Phase 3B Task 6).

Provides pluggable progress estimation towards high-level goals:
- SemanticProgressEstimator: Abstract interface supporting window and state-text evaluation.
- HeuristicProgressEstimator: Fast deterministic token-overlap progress estimator.
- EmbeddingProgressEstimator: Optional dense embedding estimator with silent fallback to heuristic.
- Strictly offline by default; zero remote API calls.
"""

from __future__ import annotations

import abc
import logging
from typing import Any, Dict, List, Optional, Sequence, Set, Union

from ..schemas import TrajectoryRecord, TrajectoryWindow
from .model_interface import MonitorWindow, to_step_telemetry
from .stuck_monitor import StepTelemetry

logger = logging.getLogger("arc_cua.monitors.semantic_progress")


class SemanticProgressEstimator(abc.ABC):
    """Abstract interface for pluggable semantic progress estimation."""

    @abc.abstractmethod
    def estimate(self, goal: str, window: Union[MonitorWindow, TrajectoryWindow, Any]) -> float:
        """Estimate semantic goal progress [0.0 - 1.0] from an execution window."""
        pass

    @abc.abstractmethod
    def score_progression(
        self,
        goal: str,
        state_text_before: str,
        state_text_after: str,
    ) -> float:
        """Estimate semantic progress towards goal between state snapshots (Phase 3A compatibility)."""
        pass


class HeuristicProgressEstimator(SemanticProgressEstimator):
    """Deterministic token-overlap progress estimator."""

    def estimate(self, goal: str, window: Union[MonitorWindow, TrajectoryWindow, Any]) -> float:
        """Estimate goal progress from window telemetry via token alignment."""
        if not goal:
            return 0.0

        goal_tokens = set(goal.lower().split())
        if not goal_tokens:
            return 0.0

        # Extract textual tokens from current and recent steps
        if isinstance(window, (MonitorWindow, TrajectoryWindow)):
            curr = to_step_telemetry(window.current_step)
            steps = [to_step_telemetry(s) for s in window.steps]
        elif isinstance(window, StepTelemetry):
            curr = window
            steps = [window]
        elif isinstance(window, Sequence) and len(window) > 0:
            curr = to_step_telemetry(window[-1])
            steps = [to_step_telemetry(s) for s in window]
        else:
            return 0.0

        # Collect observations from current step
        step_tokens: Set[str] = set()
        if curr.target:
            step_tokens.update(curr.target.lower().replace("#", " ").replace(".", " ").split())
        if curr.value:
            step_tokens.update(str(curr.value).lower().split())
        if curr.verb:
            step_tokens.add(curr.verb.lower())
        if curr.url:
            step_tokens.update(curr.url.lower().replace("/", " ").replace("-", " ").split())

        meta = curr.metadata or {}
        for val in meta.values():
            if isinstance(val, str):
                step_tokens.update(val.lower().split())

        # Match tokens against goal
        overlap = goal_tokens & step_tokens
        base_score = len(overlap) / len(goal_tokens) if goal_tokens else 0.0

        # Verification bonus
        if meta.get("expected_state_change_verified") is True:
            base_score = max(base_score, 0.8)
        elif curr.state_changed and curr.success and not curr.action_exception:
            base_score = max(base_score, 0.5 if overlap else 0.3)

        return min(1.0, round(base_score, 4))

    def score_progression(
        self,
        goal: str,
        state_text_before: str,
        state_text_after: str,
    ) -> float:
        """Calculate token-overlap progression between before and after accessibility text."""
        if not goal or not state_text_after:
            return 0.0

        goal_tokens = set(goal.lower().split())
        if not goal_tokens:
            return 0.0

        after_tokens = set(state_text_after.lower().split())
        before_tokens = set(state_text_before.lower().split()) if state_text_before else set()

        # Newly introduced tokens aligned with goal
        new_tokens = (after_tokens - before_tokens) & goal_tokens
        if new_tokens:
            return min(1.0, len(new_tokens) / len(goal_tokens))

        matched = goal_tokens & after_tokens
        return round(len(matched) / len(goal_tokens), 4)


class EmbeddingProgressEstimator(SemanticProgressEstimator):
    """Dense embedding progress estimator with silent fallback to heuristic."""

    def __init__(
        self,
        model_name_or_path: Optional[str] = None,
        allow_remote: bool = False,
    ):
        """Initialize EmbeddingProgressEstimator.

        Args:
            model_name_or_path: Local path or name of embedding model.
            allow_remote: Whether remote downloading or remote API is allowed (default: False).
        """
        self._model_name_or_path = model_name_or_path
        self._allow_remote = allow_remote
        self._heuristic_fallback = HeuristicProgressEstimator()
        self._model = None

        self._init_embedding_model()

    @property
    def is_available(self) -> bool:
        """Whether local embedding model is ready."""
        return self._model is not None

    def _init_embedding_model(self) -> None:
        """Attempt to load local embedding model silently."""
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            if self._model_name_or_path:
                self._model = SentenceTransformer(
                    self._model_name_or_path,
                    local_files_only=not self._allow_remote,
                )
                logger.info(f"Loaded EmbeddingProgressEstimator from {self._model_name_or_path}")
        except Exception:
            # Fallback silently to heuristic
            self._model = None

    def estimate(self, goal: str, window: Union[MonitorWindow, TrajectoryWindow, Any]) -> float:
        """Estimate goal progress using embeddings if available, else heuristic fallback."""
        if not self.is_available:
            return self._heuristic_fallback.estimate(goal, window)

        try:
            # Dense cosine similarity between goal embedding and window text embedding
            curr = to_step_telemetry(getattr(window, "current_step", window))
            text = f"Action: {curr.verb} Target: {curr.target} Value: {curr.value} StateChanged: {curr.state_changed}"

            import numpy as np  # type: ignore
            embs = self._model.encode([goal, text])
            norm1 = np.linalg.norm(embs[0])
            norm2 = np.linalg.norm(embs[1])
            if norm1 > 0 and norm2 > 0:
                sim = float(np.dot(embs[0], embs[1]) / (norm1 * norm2))
                return max(0.0, min(1.0, round((sim + 1.0) / 2.0, 4)))
            return 0.0
        except Exception as e:
            logger.debug(f"Embedding estimation failed, falling back to heuristic: {e}")
            return self._heuristic_fallback.estimate(goal, window)

    def score_progression(
        self,
        goal: str,
        state_text_before: str,
        state_text_after: str,
    ) -> float:
        """Compute embedding similarity difference between before and after states."""
        if not self.is_available:
            return self._heuristic_fallback.score_progression(goal, state_text_before, state_text_after)

        try:
            import numpy as np  # type: ignore
            embs = self._model.encode([goal, state_text_before, state_text_after])
            sim_before = float(np.dot(embs[0], embs[1]) / (np.linalg.norm(embs[0]) * np.linalg.norm(embs[1])))
            sim_after = float(np.dot(embs[0], embs[2]) / (np.linalg.norm(embs[0]) * np.linalg.norm(embs[2])))
            progression = max(0.0, sim_after - sim_before)
            return min(1.0, round(progression, 4))
        except Exception:
            return self._heuristic_fallback.score_progression(goal, state_text_before, state_text_after)
