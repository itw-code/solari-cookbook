#!/usr/bin/env python3
"""ModernBERT Full Monitor Training Runner for ARC (Phase 6).

Trains ModernBERT-base sequence classification models for Stuck and Milestone
perception monitors using trajectory datasets collected across all phases:
- Scans and windows all trajectory logs from artifacts/
- Auto-labels datasets using deterministic Phase 3B rules
- Trains PyTorch/HuggingFace model with class balancing and early stopping
- Saves weights to artifacts/phase6/models/
- CRITICAL: If torch/transformers or GPU are missing, gracefully writes
  artifacts/phase6/models/TRAINING_SKIPPED.md and exits with status 0.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "src"))

from arc_cua.monitors.training_pipeline import (
    ModernBERTTrainingPipeline,
    TrainingConfig,
    check_training_environment,
    write_training_skipped_notice,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("train_monitors_full")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Full ModernBERT Monitor Training Runner (Phase 6)"
    )
    parser.add_argument(
        "--artifacts-dir",
        type=str,
        default="artifacts",
        help="Root artifacts directory containing trajectory logs",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="artifacts/phase6/models",
        help="Directory to save trained model artifacts",
    )
    parser.add_argument(
        "--model-name",
        type=str,
        default="answerdotai/ModernBERT-base",
        help="HuggingFace model identifier (e.g. answerdotai/ModernBERT-base, microsoft/deberta-v3-small)",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=3,
        help="Number of fine-tuning epochs",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=8,
        help="Training batch size",
    )
    parser.add_argument(
        "--allow-cpu",
        action="store_true",
        help="Allow training on CPU if GPU is not detected (for small smoke runs)",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    artifacts_dir = Path(args.artifacts_dir)

    config = TrainingConfig(
        model_name=args.model_name,
        artifacts_dir=artifacts_dir,
        output_dir=output_dir,
        epochs=args.epochs,
        batch_size=args.batch_size,
        require_gpu=not args.allow_cpu,
    )

    logger.info("Initializing ModernBERT Monitor Training Pipeline...")
    pipeline = ModernBERTTrainingPipeline(config=config)

    result = pipeline.run()

    if result.get("status") == "TRAINING_SKIPPED":
        reason = result.get("reason", "ML dependencies or GPU unavailable")
        notice_path = result.get("notice_path", str(output_dir / "TRAINING_SKIPPED.md"))
        print("\n" + "=" * 70)
        print("MONITOR TRAINING SKIPPED")
        print(f"Reason: {reason}")
        print(f"Policy: Recorded notice at {notice_path}")
        print("Runtime will continue using deterministic heuristic monitors.")
        print("=" * 70 + "\n")
        return 0

    print("\n" + "=" * 70)
    print("MONITOR TRAINING COMPLETE")
    print(f"Artifacts saved to {output_dir}")
    print("=" * 70 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
