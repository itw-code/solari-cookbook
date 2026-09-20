#!/usr/bin/env python3
"""Optional Monitor Training Script for ARC (Phase 3B Task 5).

Trains a lightweight sequence classification encoder on Phase 3B labeled trajectory datasets:
- Checks for optional dependencies (torch, transformers).
- If dependencies are missing or GPU unavailable, writes TRAINING_SKIPPED.md and exits cleanly.
- If dependencies are present, fine-tunes on artifacts/phase3b/labeled/stuck.jsonl.
- Outputs artifacts to artifacts/phase3b/models/.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Ensure package is on sys.path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "src"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("train_monitors")


def write_skipped_notice(models_dir: Path, reason: str) -> Path:
    """Write artifacts/phase3b/models/TRAINING_SKIPPED.md documenting why training was skipped."""
    models_dir.mkdir(parents=True, exist_ok=True)
    notice_path = models_dir / "TRAINING_SKIPPED.md"
    content = f"""# Monitor Model Training Notice

**Status:** SKIPPED
**Reason:** {reason}

## Policy Conformance
- Phase 3B strictly enforces zero mandatory heavy ML dependencies (PyTorch / HuggingFace Transformers).
- Standard testing, continuous integration, and baseline runtime operate on deterministic heuristic monitors.
- To enable training:
  1. Install optional dependencies: `pip install torch transformers datasets accelerate`
  2. Re-run `python scripts/train_monitors.py --smoke`
"""
    with open(notice_path, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info(f"Wrote training skip notice to {notice_path}")
    return notice_path


def main():
    parser = argparse.ArgumentParser(description="Train learned monitor model for Phase 3B")
    parser.add_argument(
        "--data-dir",
        type=str,
        default="artifacts/phase3b/labeled",
        help="Directory containing labeled jsonl files",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="artifacts/phase3b/models",
        help="Directory to export trained model artifacts",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run tiny smoke training test (1 epoch, minimal batch size)",
    )
    args = parser.parse_args()

    models_dir = Path(args.output_dir)
    models_dir.mkdir(parents=True, exist_ok=True)

    # Check for optional dependencies
    try:
        import torch
        import transformers
        has_deps = True
    except ImportError as e:
        has_deps = False
        missing_dep = str(e)

    if not has_deps:
        logger.info(f"Required ML dependencies (torch/transformers) not found: {missing_dep}")
        write_skipped_notice(models_dir, f"Missing optional dependencies: {missing_dep}")
        print("\n" + "=" * 50)
        print("MONITOR TRAINING SKIPPED: torch/transformers not available.")
        print(f"Recorded notice at {models_dir / 'TRAINING_SKIPPED.md'}")
        print("=" * 50)
        return 0

    # Dependencies exist: train model
    logger.info("PyTorch and Transformers detected. Initializing training pipeline...")
    data_dir = Path(args.data_dir)
    stuck_file = data_dir / "stuck.jsonl"
    if not stuck_file.exists():
        logger.warning(f"Labeled data file {stuck_file} not found. Running labeler first...")
        import subprocess
        subprocess.run([sys.executable, "scripts/label_phase3.py"], check=True)

    # Load dataset
    samples = []
    labels = []
    with open(stuck_file, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            w = item["window"]
            curr = w["current_step"]
            txt = f"Action: {curr.get('action_type')} Target: {curr.get('target_locator')} StateChanged: {curr.get('state_changed')}"
            samples.append(txt)
            labels.append(1 if item["stuck"] else 0)

    logger.info(f"Loaded {len(samples)} training samples. Initializing model...")

    from transformers import AutoModelForSequenceClassification, AutoTokenizer, Trainer, TrainingArguments
    from datasets import Dataset

    model_name = "distilbert-base-uncased"
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSequenceClassification.from_pretrained(model_name, num_labels=2)

    encodings = tokenizer(samples, truncation=True, padding=True, max_length=64)
    ds = Dataset.from_dict({
        "input_ids": encodings["input_ids"],
        "attention_mask": encodings["attention_mask"],
        "label": labels,
    })

    training_args = TrainingArguments(
        output_dir=str(models_dir / "checkpoints"),
        num_train_epochs=1 if args.smoke else 3,
        per_device_train_batch_size=2,
        logging_steps=5,
        save_strategy="no",
        use_cpu=True,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=ds,
    )

    trainer.train()
    model.save_pretrained(str(models_dir / "saved_monitor"))
    tokenizer.save_pretrained(str(models_dir / "saved_monitor"))
    logger.info(f"Model successfully saved to {models_dir / 'saved_monitor'}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
