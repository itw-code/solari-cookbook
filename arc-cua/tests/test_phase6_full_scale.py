"""Comprehensive Test Suite for ARC Phase 6.

Validates all Phase 6 deliverables:
1. Full WebArena runner dataset generation, chunking, and resumption.
2. Full OSWorld runner dataset generation, chunking, resumption, and AT-SPI/FS state capture.
3. ModernBERT monitor training pipeline graceful skip handling and dataset preparation.
4. Final research report generator compilation and required section compliance.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Ensure package is on sys.path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "src"))
sys.path.insert(0, str(repo_root))

from scripts.generate_final_report import compute_dataset_stats, generate_report_markdown, load_json
from scripts.run_full_osworld import (
    generate_full_osworld_tasks,
    read_completed_task_ids as osworld_read_completed,
)
from scripts.run_full_webarena import (
    generate_full_webarena_tasks,
    read_completed_task_ids as webarena_read_completed,
)
from arc_cua.eval.schemas import EvalResult, EvalTask
from arc_cua.monitors.training_pipeline import (
    ModernBERTTrainingPipeline,
    TrainingConfig,
    check_training_environment,
    ingest_trajectory_windows,
    write_training_skipped_notice,
)


def test_webarena_dataset_generation_and_chunking():
    """Verify WebArena tasks generate up to 812 tasks and slice into valid chunks."""
    all_tasks = generate_full_webarena_tasks(count=100)
    assert len(all_tasks) == 100
    assert all_tasks[0].task_id == "webarena_1"
    assert all_tasks[99].task_id == "webarena_100"

    # Chunking verification
    chunk_size = 20
    chunk_0 = all_tasks[0 * chunk_size : 1 * chunk_size]
    chunk_1 = all_tasks[1 * chunk_size : 2 * chunk_size]

    assert len(chunk_0) == 20
    assert len(chunk_1) == 20
    assert chunk_0[0].task_id == "webarena_1"
    assert chunk_0[-1].task_id == "webarena_20"
    assert chunk_1[0].task_id == "webarena_21"
    assert chunk_1[-1].task_id == "webarena_40"

    # Verify zero ID collision across chunks
    chunk_0_ids = {t.task_id for t in chunk_0}
    chunk_1_ids = {t.task_id for t in chunk_1}
    assert chunk_0_ids.isdisjoint(chunk_1_ids)


def test_webarena_resuming_skips_completed(tmp_path: Path):
    """Verify that existing completed task IDs are properly skipped on resumed runs."""
    results_file = tmp_path / "webarena_results.jsonl"
    fake_completed = [
        {"task_id": "webarena_1", "success": True},
        {"task_id": "webarena_2", "success": True},
        {"task_id": "webarena_5", "success": False},
    ]
    with open(results_file, "w", encoding="utf-8") as f:
        for r in fake_completed:
            f.write(json.dumps(r) + "\n")

    completed_ids = webarena_read_completed(results_file)
    assert completed_ids == {"webarena_1", "webarena_2", "webarena_5"}

    all_tasks = generate_full_webarena_tasks(count=10)
    pending = [t for t in all_tasks if str(t.task_id) not in completed_ids]
    pending_ids = [t.task_id for t in pending]

    assert "webarena_1" not in pending_ids
    assert "webarena_2" not in pending_ids
    assert "webarena_5" not in pending_ids
    assert "webarena_3" in pending_ids
    assert "webarena_4" in pending_ids
    assert len(pending) == 7


def test_webarena_runner_script_execution(tmp_path: Path):
    """Verify run_full_webarena.py CLI executes in mock mode and logs expected banner."""
    out_file = tmp_path / "test_webarena_run.jsonl"
    cmd = [
        sys.executable,
        str(repo_root / "scripts" / "run_full_webarena.py"),
        "--max-tasks",
        "2",
        "--output-file",
        str(out_file),
        "--force-mock",
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert res.returncode == 0
    assert "FULL_RUN_REQUIRES_LIVE_INFRA" in res.stdout or "FULL_RUN_REQUIRES_LIVE_INFRA" in res.stderr
    assert out_file.exists()

    with open(out_file, "r", encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]
    assert len(lines) == 2
    assert lines[0]["task_id"] == "webarena_1"
    assert lines[1]["task_id"] == "webarena_2"
    assert lines[0]["success"] is True


def test_osworld_dataset_generation_and_chunking():
    """Verify OSWorld tasks generate up to 369 tasks and chunk without collisions."""
    tasks = generate_full_osworld_tasks(count=60)
    assert len(tasks) == 60
    assert tasks[0].task_id == "osworld_1"
    assert tasks[59].task_id == "osworld_60"

    # Chunking verification
    chunk_size = 25
    chunk_0 = tasks[0:25]
    chunk_1 = tasks[25:50]
    chunk_2 = tasks[50:60]

    assert len(chunk_0) == 25
    assert len(chunk_1) == 25
    assert len(chunk_2) == 10
    assert {t.task_id for t in chunk_0}.isdisjoint({t.task_id for t in chunk_1})


def test_osworld_resuming_skips_completed(tmp_path: Path):
    """Verify OSWorld runner resuming accurately filters out prior completed tasks."""
    results_file = tmp_path / "osworld_results.jsonl"
    fake_completed = [
        {"task_id": "osworld_1", "success": True},
        {"task_id": "osworld_3", "success": True},
    ]
    with open(results_file, "w", encoding="utf-8") as f:
        for r in fake_completed:
            f.write(json.dumps(r) + "\n")

    completed_ids = osworld_read_completed(results_file)
    assert completed_ids == {"osworld_1", "osworld_3"}

    tasks = generate_full_osworld_tasks(count=5)
    pending = [t for t in tasks if str(t.task_id) not in completed_ids]
    pending_ids = [t.task_id for t in pending]

    assert pending_ids == ["osworld_2", "osworld_4", "osworld_5"]


def test_osworld_runner_captures_fs_and_at_spi(tmp_path: Path):
    """Verify run_full_osworld.py captures file system diffs and AT-SPI desktop states."""
    out_file = tmp_path / "test_osworld_run.jsonl"
    cmd = [
        sys.executable,
        str(repo_root / "scripts" / "run_full_osworld.py"),
        "--max-tasks",
        "2",
        "--output-file",
        str(out_file),
        "--force-mock",
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert res.returncode == 0
    assert "FULL_RUN_REQUIRES_LIVE_INFRA" in res.stdout or "FULL_RUN_REQUIRES_LIVE_INFRA" in res.stderr
    assert out_file.exists()

    with open(out_file, "r", encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]

    assert len(lines) == 2
    task1_meta = lines[0]["metadata"]
    assert "fs_diff" in task1_meta
    assert "at_spi_state" in task1_meta

    # Check structure of fs_diff
    diff = task1_meta["fs_diff"]
    assert "added" in diff
    assert "removed" in diff
    assert "modified" in diff
    assert "total_changes" in diff

    # Check structure of at_spi_state
    at_spi = task1_meta["at_spi_state"]
    assert "before" in at_spi
    assert "after" in at_spi
    assert "active_window" in at_spi["after"]
    assert "focused_widget" in at_spi["after"]


def test_modernbert_training_pipeline_skip_handling(tmp_path: Path):
    """Verify ModernBERT training pipeline cleanly skips and writes TRAINING_SKIPPED.md."""
    models_dir = tmp_path / "models"
    config = TrainingConfig(
        output_dir=models_dir,
        artifacts_dir=Path("artifacts"),
        require_gpu=True,
    )
    pipeline = ModernBERTTrainingPipeline(config=config)

    # In standard environment without torch/transformers/GPU, run() must skip gracefully
    res = pipeline.run()
    assert res["status"] == "TRAINING_SKIPPED"
    assert "reason" in res

    skip_file = models_dir / "TRAINING_SKIPPED.md"
    assert skip_file.exists()
    content = skip_file.read_text(encoding="utf-8")
    assert "TRAINING_SKIPPED" in content
    assert "Policy Conformance" in content


def test_modernbert_training_pipeline_data_preparation(tmp_path: Path):
    """Verify ingestion of trajectory logs and dataset preparation with class balancing."""
    config = TrainingConfig(
        output_dir=tmp_path / "models",
        artifacts_dir=Path("artifacts"),
    )
    pipeline = ModernBERTTrainingPipeline(config=config)

    # Ingest existing or synthesized trajectory windows
    windows = ingest_trajectory_windows(Path("artifacts"))
    assert len(windows) >= 10

    dataset = pipeline.prepare_dataset(windows)
    assert "stuck" in dataset
    assert "milestone" in dataset
    assert "summary" in dataset

    # Check train/val split proportions (~80/20)
    stuck_train = dataset["stuck"]["train"]
    stuck_val = dataset["stuck"]["val"]
    total = len(stuck_train) + len(stuck_val)
    assert total == len(windows)
    assert len(stuck_train) >= len(stuck_val)

    # Check class weights
    assert len(dataset["stuck"]["class_weights"]) == 2
    assert all(w > 0 for w in dataset["stuck"]["class_weights"])


def test_final_report_generator(tmp_path: Path):
    """Verify generate_final_report.py produces compliant Markdown with all required sections."""
    out_md = tmp_path / "FINAL_REPORT.md"
    cmd = [
        sys.executable,
        str(repo_root / "scripts" / "generate_final_report.py"),
        "--scorecard",
        "artifacts/production/final_scorecard.json",
        "--webarena-results",
        "webarena_results.jsonl",
        "--osworld-results",
        "osworld_results.jsonl",
        "--output",
        str(out_md),
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert res.returncode == 0
    assert out_md.exists()

    report_text = out_md.read_text(encoding="utf-8")

    # Verify all 6 mandatory sections from instructions_06.md
    assert "## 1. Executive Summary" in report_text
    assert "## 2. Architecture Overview" in report_text
    assert "## 3. Benchmark Results" in report_text
    assert "## 4. Cost & Latency Analysis" in report_text
    assert "## 5. Monitor Efficacy" in report_text
    assert "## 6. Conclusion & Future Work" in report_text

    # Verify status notice
    assert "PROJECTED_BASED_ON_MOCK_EXECUTION" in report_text
    # Verify core value proposition claims
    assert "99." in report_text
    assert "Reflex" in report_text
    assert "WebArena" in report_text
    assert "OSWorld" in report_text
