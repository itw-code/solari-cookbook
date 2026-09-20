"""Optional Learned Transformer Monitor Adapter for ARC (Phase 3B Task 5).

Provides integration with small local encoder models (e.g. ModernBERT, DeBERTa-v3, DistilBERT):
- Strictly optional: does not require torch or transformers at test/import time.
- If dependencies are missing, safely returns LEARNED_MONITOR_UNAVAILABLE.
- Disables external network downloading by default (local model paths only).
- Integrates with FeatureBuilder or raw trajectory tokenization.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional, Union

from ..schemas import TrajectoryWindow
from .feature_builder import FeatureBuilder
from .model_interface import MonitorModel, MonitorPrediction, MonitorWindow

logger = logging.getLogger("arc_cua.monitors.transformer_adapter")

LEARNED_MONITOR_UNAVAILABLE = "LEARNED_MONITOR_UNAVAILABLE"

# Check optional dependencies safely
try:
    import torch
    import transformers
    HAS_TORCH_TRANSFORMERS = True
except ImportError:
    torch = None  # type: ignore
    transformers = None  # type: ignore
    HAS_TORCH_TRANSFORMERS = False


class TransformerMonitorAdapter(MonitorModel):
    """Pluggable transformer-based monitor adapter for learned anomaly detection."""

    def __init__(
        self,
        model_path: Optional[Union[str, Path]] = None,
        model_name: str = "distilbert-base-uncased",
        allow_download: bool = False,
    ):
        """Initialize TransformerMonitorAdapter.

        Args:
            model_path: Path to local saved model directory.
            model_name: Name/architecture identifier.
            allow_download: Whether downloading from external HuggingFace hub is allowed (default: False).
        """
        self._model_path = Path(model_path) if model_path else None
        self._model_name = model_name
        self._allow_download = allow_download
        self._feature_builder = FeatureBuilder()
        self._model = None
        self._tokenizer = None

        if HAS_TORCH_TRANSFORMERS:
            self._init_model()
        else:
            logger.info("PyTorch / Transformers not installed; learned monitor is unavailable.")

    @property
    def model_name(self) -> str:
        return f"transformer:{self._model_name}"

    @property
    def is_available(self) -> bool:
        """Return True if torch/transformers are installed and model is loaded."""
        return HAS_TORCH_TRANSFORMERS and (self._model is not None or self._model_path is None)

    def _init_model(self) -> None:
        """Initialize local model weights if path exists and torch is present."""
        if not HAS_TORCH_TRANSFORMERS:
            return

        if self._model_path and self._model_path.exists():
            try:
                from transformers import AutoModelForSequenceClassification, AutoTokenizer
                self._tokenizer = AutoTokenizer.from_pretrained(str(self._model_path), local_files_only=True)
                self._model = AutoModelForSequenceClassification.from_pretrained(
                    str(self._model_path), local_files_only=True
                )
                self._model.eval()
                logger.info(f"Loaded learned monitor model from {self._model_path}")
            except Exception as e:
                logger.warning(f"Failed to load local model weights from {self._model_path}: {e}")
                self._model = None
        elif self._allow_download:
            try:
                from transformers import AutoModelForSequenceClassification, AutoTokenizer
                self._tokenizer = AutoTokenizer.from_pretrained(self._model_name)
                self._model = AutoModelForSequenceClassification.from_pretrained(self._model_name)
                self._model.eval()
                logger.info(f"Loaded learned monitor model via download: {self._model_name}")
            except Exception as e:
                logger.warning(f"Failed to download model {self._model_name}: {e}")
                self._model = None

    def predict(self, window: Union[MonitorWindow, TrajectoryWindow]) -> MonitorPrediction:
        """Predict anomaly score for trajectory window using learned encoder."""
        if not HAS_TORCH_TRANSFORMERS or self._model is None:
            return MonitorPrediction(
                score=0.0,
                reason=LEARNED_MONITOR_UNAVAILABLE,
                evidence={
                    "status": LEARNED_MONITOR_UNAVAILABLE,
                    "has_torch": HAS_TORCH_TRANSFORMERS,
                    "model_loaded": self._model is not None,
                },
                model_name=self.model_name,
                is_positive=False,
                confidence=0.0,
            )

        # If model is loaded, format window representation and compute forward pass
        features = self._feature_builder.build_features(window)
        input_text = (
            f"Actions: {' -> '.join(features.action_type_sequence)} | "
            f"Roles: {' -> '.join(features.target_role_sequence)} | "
            f"Repeat: {features.action_repeat_count} | "
            f"NoChange: {features.consecutive_no_state_change} | "
            f"Cycle: {features.state_hash_cycle_detected} | "
            f"Error: {features.error_detected}"
        )

        try:
            inputs = self._tokenizer(input_text, return_tensors="pt", truncation=True, max_length=128)
            with torch.no_grad():
                outputs = self._model(**inputs)
                probs = torch.softmax(outputs.logits, dim=-1)
                stuck_prob = float(probs[0][1].item()) if probs.shape[-1] > 1 else float(probs[0][0].item())

            return MonitorPrediction(
                score=round(stuck_prob, 4),
                reason="learned_transformer_inference",
                evidence={"input_text": input_text, "probabilities": probs.tolist()},
                model_name=self.model_name,
                is_positive=(stuck_prob >= 0.5),
                confidence=round(stuck_prob if stuck_prob >= 0.5 else 1.0 - stuck_prob, 4),
            )
        except Exception as inf_err:
            logger.error(f"Inference error in TransformerMonitorAdapter: {inf_err}")
            return MonitorPrediction(
                score=0.0,
                reason=f"INFERENCE_ERROR: {inf_err}",
                evidence={"error": str(inf_err)},
                model_name=self.model_name,
                is_positive=False,
                confidence=0.0,
            )
