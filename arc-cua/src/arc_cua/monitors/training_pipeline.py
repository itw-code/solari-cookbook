"""ModernBERT Monitor Model Training Pipeline for ARC (Phase 6).

Coordinates the training of ModernBERT-base sequence classification models
for local Stuck and Milestone perception monitors:
1. Ingests all trajectory_logs.jsonl datasets from the artifacts/ directory.
2. Applies the deterministic Phase 3B AutoLabeler to construct balanced ground truth.
3. Formats sliding trajectory windows into rich contextual representations.
4. Performs an 80/20 train/test split with class-imbalance reweighting.
5. Executes PyTorch/HuggingFace training loop with validation F1-based early stopping.
6. Saves trained model artifacts to artifacts/phase6/models/.
7. Gracefully skips and writes TRAINING_SKIPPED.md if torch/transformers or GPU are missing.
"""

from __future__ import annotations

import collections
import copy
import dataclasses
import json
import logging
import os
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from ..datasets.labeler import AutoLabeler, LabelResult
from ..datasets.trajectory_collector import TrajectoryCollector
from ..schemas import ActionStep, TrajectoryRecord, TrajectoryWindow

logger = logging.getLogger("arc_cua.monitors.training_pipeline")


@dataclasses.dataclass
class TrainingConfig:
    """Hyperparameters and configuration for ModernBERT monitor training."""

    model_name: str = "answerdotai/ModernBERT-base"
    artifacts_dir: Path = Path("artifacts")
    output_dir: Path = Path("artifacts/phase6/models")
    train_split: float = 0.8
    early_stopping_patience: int = 3
    batch_size: int = 8
    epochs: int = 3
    learning_rate: float = 2e-5
    max_length: int = 128
    require_gpu: bool = True
    random_seed: int = 42

    def __post_init__(self) -> None:
        self.artifacts_dir = Path(self.artifacts_dir)
        self.output_dir = Path(self.output_dir)


def check_training_environment(require_gpu: bool = True) -> Tuple[bool, str]:
    """Verify presence of optional ML libraries (torch, transformers) and GPU.

    Returns:
        (is_ready, explanation_string)
    """
    try:
        import torch
    except ImportError as e:
        return False, f"PyTorch is not installed ({e})"

    try:
        import transformers
    except ImportError as e:
        return False, f"HuggingFace Transformers is not installed ({e})"

    if require_gpu and not torch.cuda.is_available():
        return False, "Host lacks CUDA-capable GPU (GPU acceleration required for ModernBERT training)"

    return True, "Environment ready: PyTorch, Transformers, and GPU available"


def write_training_skipped_notice(output_dir: Path, reason: str) -> Path:
    """Write artifacts/phase6/models/TRAINING_SKIPPED.md documenting why training was skipped."""
    output_dir.mkdir(parents=True, exist_ok=True)
    notice_path = output_dir / "TRAINING_SKIPPED.md"
    content = f"""# ModernBERT Monitor Model Training Notice

**Status:** TRAINING_SKIPPED
**Reason:** {reason}

## Policy Conformance
- Phase 6 requires production GPU acceleration and deep learning frameworks (`torch`, `transformers`) to fine-tune ModernBERT-base.
- Host environment: Windows/CI without active CUDA GPU or ML libraries.
- The ARC system defaults to deterministic heuristic monitors (`HeuristicMonitorAdapter`), maintaining full operational capability.
- To execute live model training:
  1. Deploy to a Linux host equipped with an NVIDIA GPU and CUDA drivers.
  2. Install deep learning dependencies: `pip install torch transformers datasets accelerate scikit-learn`
  3. Re-run: `python scripts/train_monitors_full.py`
"""
    with open(notice_path, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info(f"Recorded training skip notice to {notice_path}")
    return notice_path


def parse_record_from_dict(d: Dict[str, Any]) -> TrajectoryRecord:
    """Safely construct a TrajectoryRecord from serialized JSON dictionary."""
    return TrajectoryRecord(
        run_id=d.get("run_id", "eval-run"),
        task_id=d.get("task_id", "task-default"),
        step_id=d.get("step_id", 1),
        timestamp=d.get("timestamp", 0.0),
        action_type=d.get("action_type", "CLICK"),
        target_locator=d.get("target_locator"),
        locator_strategy=d.get("locator_strategy"),
        readiness_passed=bool(d.get("readiness_passed", True)),
        execution_success=bool(d.get("execution_success", True)),
        state_hash_before=d.get("state_hash_before", 100),
        state_hash_after=d.get("state_hash_after", 100),
        state_changed=bool(d.get("state_changed", False)),
        hamming_distance=d.get("hamming_distance", 0),
        url_before=d.get("url_before"),
        url_after=d.get("url_after"),
        url_changed=bool(d.get("url_changed", False)),
        error_detected=bool(d.get("error_detected", False)),
        error_type=d.get("error_type"),
        monitor_stuck_score=float(d.get("monitor_stuck_score", 0.0)),
        monitor_milestone_score=float(d.get("monitor_milestone_score", 0.0)),
        escalation_decision=d.get("escalation_decision"),
        recovery_attempted=bool(d.get("recovery_attempted", False)),
        recovery_success=d.get("recovery_success"),
        integration_mode=d.get("integration_mode", "mock"),
        metadata=d.get("metadata", {}),
    )


def ingest_trajectory_windows(artifacts_dir: Path) -> List[TrajectoryWindow]:
    """Scan artifacts directory for all trajectory logs and window them."""
    collector = TrajectoryCollector()
    found_files = []

    if artifacts_dir.exists():
        for p in artifacts_dir.glob("**/*trajectory*.jsonl"):
            found_files.append(p)
        for p in artifacts_dir.glob("**/*results.jsonl"):
            # Results file may contain completed_steps
            pass

    records_count = 0
    for file_path in found_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line_str = line.strip()
                    if not line_str:
                        continue
                    data = json.loads(line_str)
                    if "action_type" in data:
                        rec = parse_record_from_dict(data)
                        collector.add_record(rec)
                        records_count += 1
        except Exception as e:
            logger.debug(f"Error parsing trajectory file {file_path}: {e}")

    windows = collector.get_windows()
    logger.info(
        f"Ingested {records_count} records from {len(found_files)} files into {len(windows)} sliding windows."
    )

    # Ensure baseline synthetic windows if disk logs are empty or sparse
    if len(windows) < 10:
        logger.info("Augmenting trajectory windows with standard synthetic transitions...")
        synthesize_baseline_windows(collector)
        windows = collector.get_windows()

    return windows


def synthesize_baseline_windows(collector: TrajectoryCollector) -> None:
    """Generate representative sliding windows covering stuck and milestone events."""
    # 1. Healthy progress sequence leading to milestone
    run_prog = "synth-train-progress"
    for i in range(1, 5):
        collector.add_record(
            TrajectoryRecord(
                run_id=run_prog,
                task_id="checkout",
                step_id=i,
                timestamp=100.0 + i,
                action_type="TYPE" if i % 2 == 1 else "CLICK",
                target_locator=f"#input-step-{i}",
                locator_strategy="css",
                readiness_passed=True,
                execution_success=True,
                state_hash_before=1000 + i * 10,
                state_hash_after=1000 + (i + 1) * 10,
                state_changed=True,
                hamming_distance=4,
                url_before="http://app/form",
                url_after="http://app/form" if i < 4 else "http://app/success",
                url_changed=(i == 4),
            )
        )

    # 2. Stuck sequence (mechanical clicks with zero delta)
    run_stuck = "synth-train-stuck"
    for i in range(1, 4):
        collector.add_record(
            TrajectoryRecord(
                run_id=run_stuck,
                task_id="broken_button",
                step_id=i,
                timestamp=200.0 + i,
                action_type="CLICK",
                target_locator="button#submit-action",
                locator_strategy="css",
                readiness_passed=True,
                execution_success=True,
                state_hash_before=5000,
                state_hash_after=5000,
                state_changed=False,
                hamming_distance=0,
                url_before="http://app/stuck",
                url_after="http://app/stuck",
                url_changed=False,
            )
        )

    # 3. Repeated locator failure sequence
    run_fail = "synth-train-locator-fail"
    for i in range(1, 4):
        collector.add_record(
            TrajectoryRecord(
                run_id=run_fail,
                task_id="missing_elem",
                step_id=i,
                timestamp=300.0 + i,
                action_type="CLICK",
                target_locator="#ghost-element",
                locator_strategy="css",
                readiness_passed=False,
                execution_success=False,
                state_hash_before=6000,
                state_hash_after=6000,
                state_changed=False,
                error_detected=True,
                error_type="locator_timeout",
            )
        )


def format_window_text(w: TrajectoryWindow) -> str:
    """Format a TrajectoryWindow into a rich contextual string for ModernBERT."""
    curr = w.current_step
    hist_parts = []
    for h in w.history:
        hist_parts.append(f"{h.action_type}({h.target_locator or 'none'})[chg={h.state_changed}]")
    history_str = " -> ".join(hist_parts) if hist_parts else "START"
    return (
        f"Goal: {curr.task_id} | "
        f"Current: {curr.action_type} target='{curr.target_locator or ''}' "
        f"success={curr.execution_success} state_chg={curr.state_changed} "
        f"url_chg={curr.url_changed} err={curr.error_detected} ({curr.error_type or 'none'}) | "
        f"History: {history_str}"
    )


class ModernBERTTrainingPipeline:
    """End-to-end training and evaluation pipeline for ModernBERT monitors."""

    def __init__(self, config: Optional[TrainingConfig] = None):
        self.config = config or TrainingConfig()
        self.labeler = AutoLabeler(use_model=False)

    def check_environment(self) -> Tuple[bool, str]:
        """Check whether ML dependencies and GPU are available."""
        return check_training_environment(require_gpu=self.config.require_gpu)

    def prepare_dataset(
        self,
        windows: List[TrajectoryWindow],
    ) -> Dict[str, Any]:
        """Auto-label windows and partition into train/val splits with class balancing.

        Returns:
            Dictionary containing 'stuck_dataset' and 'milestone_dataset' splits and weights.
        """
        results, summary = self.labeler.label_dataset(windows)
        rng = random.Random(self.config.random_seed)

        stuck_samples: List[Dict[str, Any]] = []
        milestone_samples: List[Dict[str, Any]] = []

        for w, r in zip(windows, results):
            text = format_window_text(w)
            stuck_samples.append({
                "text": text,
                "label": 1 if r.stuck else 0,
                "window_id": w.window_id,
                "reason": r.stuck_reason,
            })
            milestone_samples.append({
                "text": text,
                "label": 1 if r.milestone else 0,
                "window_id": w.window_id,
                "reason": r.milestone_reason,
            })

        # Shuffle deterministically
        rng.shuffle(stuck_samples)
        rng.shuffle(milestone_samples)

        # 80/20 train/test split
        split_idx = max(1, int(len(stuck_samples) * self.config.train_split))

        stuck_train = stuck_samples[:split_idx]
        stuck_val = stuck_samples[split_idx:]

        milestone_train = milestone_samples[:split_idx]
        milestone_val = milestone_samples[split_idx:]

        # Calculate class balancing weights for rare positive events
        def _calc_class_weights(data: List[Dict[str, Any]]) -> Tuple[float, float]:
            pos = sum(1 for x in data if x["label"] == 1)
            neg = len(data) - pos
            if pos == 0 or neg == 0:
                return 1.0, 1.0
            # Weight inversely proportional to class frequencies
            w0 = len(data) / (2.0 * neg)
            w1 = len(data) / (2.0 * pos)
            return w0, w1

        stuck_w0, stuck_w1 = _calc_class_weights(stuck_train)
        mile_w0, mile_w1 = _calc_class_weights(milestone_train)

        return {
            "summary": summary.to_dict(),
            "stuck": {
                "train": stuck_train,
                "val": stuck_val,
                "class_weights": [stuck_w0, stuck_w1],
                "pos_count": sum(1 for x in stuck_train if x["label"] == 1),
                "total_count": len(stuck_train),
            },
            "milestone": {
                "train": milestone_train,
                "val": milestone_val,
                "class_weights": [mile_w0, mile_w1],
                "pos_count": sum(1 for x in milestone_train if x["label"] == 1),
                "total_count": len(milestone_train),
            },
        }

    def train_with_ml(self, dataset: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the actual PyTorch / HuggingFace fine-tuning loop."""
        import torch
        from torch.utils.data import DataLoader, Dataset
        from transformers import AutoModelForSequenceClassification, AutoTokenizer, get_linear_schedule_with_warmup

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        tokenizer = AutoTokenizer.from_pretrained(self.config.model_name)

        trained_models: Dict[str, Any] = {}

        class TextDataset(Dataset):
            def __init__(self, samples: List[Dict[str, Any]], max_len: int):
                self.samples = samples
                self.max_len = max_len

            def __len__(self) -> int:
                return len(self.samples)

            def __getitem__(self, idx: int) -> Dict[str, Any]:
                item = self.samples[idx]
                encoding = tokenizer(
                    item["text"],
                    truncation=True,
                    padding="max_length",
                    max_length=self.max_len,
                    return_tensors="pt",
                )
                return {
                    "input_ids": encoding["input_ids"].squeeze(0),
                    "attention_mask": encoding["attention_mask"].squeeze(0),
                    "label": torch.tensor(item["label"], dtype=torch.long),
                }

        for monitor_name in ["stuck", "milestone"]:
            m_data = dataset[monitor_name]
            train_loader = DataLoader(
                TextDataset(m_data["train"], self.config.max_length),
                batch_size=self.config.batch_size,
                shuffle=True,
            )
            val_loader = DataLoader(
                TextDataset(m_data["val"], self.config.max_length),
                batch_size=self.config.batch_size,
                shuffle=False,
            )

            # Class balanced loss function
            weights_tensor = torch.tensor(m_data["class_weights"], dtype=torch.float, device=device)
            criterion = torch.nn.CrossEntropyLoss(weight=weights_tensor)

            model = AutoModelForSequenceClassification.from_pretrained(
                self.config.model_name,
                num_labels=2,
            ).to(device)

            optimizer = torch.optim.AdamW(model.parameters(), lr=self.config.learning_rate)
            total_steps = len(train_loader) * self.config.epochs
            scheduler = get_linear_schedule_with_warmup(
                optimizer,
                num_warmup_steps=int(total_steps * 0.1),
                num_training_steps=total_steps,
            )

            best_f1 = -1.0
            patience_counter = 0
            best_state = None

            for epoch in range(1, self.config.epochs + 1):
                model.train()
                for batch in train_loader:
                    optimizer.zero_grad()
                    input_ids = batch["input_ids"].to(device)
                    attention_mask = batch["attention_mask"].to(device)
                    labels = batch["label"].to(device)

                    outputs = model(input_ids=input_ids, attention_mask=attention_mask)
                    loss = criterion(outputs.logits, labels)
                    loss.backward()
                    optimizer.step()
                    scheduler.step()

                # Validation step with F1 calculation
                model.eval()
                all_preds = []
                all_labels = []
                with torch.no_grad():
                    for batch in val_loader:
                        input_ids = batch["input_ids"].to(device)
                        attention_mask = batch["attention_mask"].to(device)
                        labels = batch["label"].to(device)

                        outputs = model(input_ids=input_ids, attention_mask=attention_mask)
                        preds = torch.argmax(outputs.logits, dim=1).cpu().tolist()
                        all_preds.extend(preds)
                        all_labels.extend(labels.cpu().tolist())

                # Compute macro F1
                tp = sum(1 for p, l in zip(all_preds, all_labels) if p == 1 and l == 1)
                fp = sum(1 for p, l in zip(all_preds, all_labels) if p == 1 and l == 0)
                fn = sum(1 for p, l in zip(all_preds, all_labels) if p == 0 and l == 1)
                prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
                rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
                val_f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0

                logger.info(f"[{monitor_name}] Epoch {epoch}/{self.config.epochs} Val F1={val_f1:.4f}")

                if val_f1 > best_f1:
                    best_f1 = val_f1
                    patience_counter = 0
                    best_state = copy.deepcopy(model.state_dict())
                else:
                    patience_counter += 1
                    if patience_counter >= self.config.early_stopping_patience:
                        logger.info(f"[{monitor_name}] Early stopping triggered at epoch {epoch}")
                        break

            # Save model
            model_save_dir = self.config.output_dir / f"{monitor_name}_monitor"
            model_save_dir.mkdir(parents=True, exist_ok=True)
            if best_state is not None:
                model.load_state_dict(best_state)
            model.save_pretrained(str(model_save_dir))
            tokenizer.save_pretrained(str(model_save_dir))
            trained_models[monitor_name] = {
                "save_dir": str(model_save_dir),
                "best_f1": best_f1,
            }

        return trained_models

    def run(self) -> Dict[str, Any]:
        """Execute full training pipeline or document skip gracefully."""
        is_ready, reason = self.check_environment()
        if not is_ready:
            logger.info(f"Training prerequisite check: {reason}")
            notice_path = write_training_skipped_notice(self.config.output_dir, reason)
            return {
                "status": "TRAINING_SKIPPED",
                "reason": reason,
                "notice_path": str(notice_path),
            }

        logger.info("ML environment verified. Ingesting trajectory logs...")
        windows = ingest_trajectory_windows(self.config.artifacts_dir)
        dataset = self.prepare_dataset(windows)

        logger.info(f"Prepared dataset: {len(windows)} windows labeled.")
        trained_info = self.train_with_ml(dataset)

        return {
            "status": "TRAINING_COMPLETE",
            "models": trained_info,
            "dataset_summary": dataset["summary"],
        }
