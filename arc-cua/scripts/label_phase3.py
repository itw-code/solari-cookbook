#!/usr/bin/env python3
"""Auto-Labeling CLI script for ARC (Phase 3B Task 2).

Generates deterministic labels (stuck.jsonl, milestone.jsonl, summary.json)
from recorded or generated trajectory windows:
- Evaluates operational heuristics.
- Generates stuck & milestone labels.
- Exports to artifacts/phase3b/labeled/.
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List

# Ensure package is on sys.path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "src"))

from arc_cua.datasets.labeler import AutoLabeler
from arc_cua.datasets.trajectory_collector import TrajectoryCollector
from arc_cua.schemas import TrajectoryRecord, TrajectoryWindow

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("label_phase3")


def generate_synthetic_windows() -> List[TrajectoryWindow]:
    """Generate deterministic synthetic trajectory windows for testing & bootstrapping."""
    collector = TrajectoryCollector(default_window_size=5)

    # 1. Normal progressing run
    for step in range(1, 5):
        collector.record_step(
            run_id="synth-progress-1",
            task_id="submit form",
            step_id=step,
            action_type="CLICK" if step % 2 == 1 else "TYPE",
            target_locator=f"input#field{step}",
            execution_success=True,
            state_hash_before=step * 100,
            state_hash_after=(step + 1) * 100,
            state_changed=True,
            hamming_distance=4,
            url_changed=(step == 4),
            url_after="https://app.local/success" if step == 4 else "https://app.local/form",
        )

    # 2. Stuck run (3 consecutive no-state-change)
    for step in range(1, 5):
        collector.record_step(
            run_id="synth-stuck-nochange",
            task_id="click button",
            step_id=step,
            action_type="CLICK",
            target_locator="button#submit",
            execution_success=True,
            state_hash_before=999,
            state_hash_after=999,
            state_changed=False,
            hamming_distance=0,
        )

    # 3. Repeated locator failure run
    for step in range(1, 4):
        collector.record_step(
            run_id="synth-stuck-locator-fail",
            task_id="find popup",
            step_id=step,
            action_type="CLICK",
            target_locator="div#modal_close",
            execution_success=False,
            error_detected=True,
            error_type="LOCATOR_NOT_FOUND",
            state_changed=False,
        )

    # 4. Cyclic state hash oscillation (A -> B -> A)
    hashes = [101, 202, 101, 202]
    for step, h in enumerate(hashes, 1):
        prev = hashes[step - 2] if step > 1 else 100
        collector.record_step(
            run_id="synth-stuck-oscillation",
            task_id="toggle tab",
            step_id=step,
            action_type="CLICK",
            target_locator=f"tab#{h}",
            execution_success=True,
            state_hash_before=prev,
            state_hash_after=h,
            state_changed=True,
            hamming_distance=3,
        )

    return collector.get_windows()


def load_windows_from_jsonl(path: Path) -> List[TrajectoryWindow]:
    """Load TrajectoryWindows from an existing JSONL export."""
    windows: List[TrajectoryWindow] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            curr = TrajectoryRecord(**data["current_step"])
            hist = [TrajectoryRecord(**s) for s in data.get("history", [])]
            w = TrajectoryWindow(
                window_id=data["window_id"],
                current_step=curr,
                history=hist,
                window_size=data.get("window_size", len(hist) + 1),
                metadata=data.get("metadata", {}),
            )
            windows.append(w)
    return windows


def main():
    parser = argparse.ArgumentParser(description="Auto-label trajectory windows for Phase 3B")
    parser.add_argument(
        "--input",
        type=str,
        default="artifacts/phase3b/trajectory_logs/trajectory_windows.jsonl",
        help="Input path to trajectory windows JSONL",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="artifacts/phase3b/labeled",
        help="Output directory for labeled datasets",
    )
    parser.add_argument(
        "--use-model",
        action="store_true",
        help="Use external/learned model for labeling (offline heuristic by default)",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if input_path.exists():
        logger.info(f"Loading trajectory windows from {input_path}")
        windows = load_windows_from_jsonl(input_path)
    else:
        logger.info(f"No input file found at {input_path}. Generating synthetic trajectory dataset...")
        windows = generate_synthetic_windows()

    logger.info(f"Labeling {len(windows)} windows using {'model' if args.use_model else 'deterministic heuristics'}...")
    labeler = AutoLabeler(use_model=args.use_model)
    paths = labeler.export_labeled_dataset(windows, output_dir=args.output_dir)

    summary_file = paths["summary"]
    with open(summary_file, "r", encoding="utf-8") as f:
        summary_data = json.load(f)

    print("\n" + "=" * 50)
    print("PHASE 3B AUTO-LABELING SUMMARY")
    print("=" * 50)
    print(json.dumps(summary_data, indent=2))
    print(f"\nOutputs saved to:\n  {paths['stuck']}\n  {paths['milestone']}\n  {paths['summary']}")
    print("=" * 50)


if __name__ == "__main__":
    main()
