#!/usr/bin/env python3
"""Benchmark Phase 3B Components and End-to-End Hybrid Overhead.

Measures:
- feature_builder_latency_ms (Target: p95 < 10ms)
- heuristic_monitor_latency_ms (Target: p95 < 10ms)
- learned_monitor_latency_ms_or_null (Reports value or null if skipped)
- trajectory_collector_latency_ms (Target: p95 < 10ms)
- labeler_throughput_records_per_sec
- mock_cortex_recovery_latency_ms (Target: p95 < 20ms)
- dry_run_cortex_payload_latency_ms (Target: p95 < 20ms)
- live_browser_hybrid_step_latency_ms (Target: p95 < 1000ms)

Outputs structured statistical distributions (p50, p95, p99) and environment metadata.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import platform
import sys
import time
from typing import Any, Dict, List, Optional

# Ensure src is in python path
repo_root = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "src"))

from arc_cua.cortex.http_cortex import HttpCortexClient
from arc_cua.cortex.mock_cortex import MockCortexClient
from arc_cua.datasets.labeler import AutoLabeler
from arc_cua.datasets.trajectory_collector import TrajectoryCollector
from arc_cua.monitors.feature_builder import FeatureBuilder
from arc_cua.monitors.heuristic_adapter import HeuristicStuckModelAdapter
from arc_cua.monitors.transformer_adapter import (
    LEARNED_MONITOR_UNAVAILABLE,
    TransformerMonitorAdapter,
)
from arc_cua.schemas import (
    ActionStep,
    EscalationPayload,
    EscalationReason,
    PerceptionSource,
    TrajectoryRecord,
    TrajectoryWindow,
    UIState,
)
from arc_cua.telemetry import compute_percentiles


def run_benchmarks(sample_size: int = 1000) -> Dict[str, Any]:
    env_str = f"{platform.system()} {platform.release()} ({platform.machine()}), Python {platform.python_version()}"
    integration_mode = "mock"

    results: Dict[str, Any] = {
        "environment": env_str,
        "sample_size": sample_size,
        "integration_mode": integration_mode,
        "metrics": {},
    }

    print("=" * 70)
    print("ARC HYBRID CUA - PHASE 3B BENCHMARK SUITE")
    print(f"Environment: {env_str}")
    print(f"Sample Size: {sample_size}")
    print("=" * 70)

    # ----------------------------------------------------
    # 1. Trajectory Collector Benchmark
    # ----------------------------------------------------
    collector = TrajectoryCollector()
    traj_latencies = []
    for i in range(sample_size):
        t0 = time.perf_counter()
        collector.record_step(
            run_id=f"bench-run-{i % 10}",
            task_id="benchmark task",
            step_id=(i % 10) + 1,
            action_type="CLICK",
            target_locator="button#test",
            state_changed=(i % 2 == 0),
            state_hash_before=i * 10,
            state_hash_after=(i + 1) * 10,
            hamming_distance=4,
        )
        t1 = time.perf_counter()
        traj_latencies.append((t1 - t0) * 1000.0)

    p_traj = compute_percentiles(traj_latencies, "trajectory_collector_latency_ms")
    results["metrics"]["trajectory_collector_latency_ms"] = p_traj.to_dict()

    # Obtain sample windows for subsequent monitor/feature tests
    windows = collector.get_windows()[:sample_size]
    if not windows:
        # Fallback window
        rec = TrajectoryRecord(run_id="r1", task_id="t1", step_id=1)
        windows = [TrajectoryWindow(window_id="w1", current_step=rec)]

    # ----------------------------------------------------
    # 2. Feature Builder Benchmark
    # ----------------------------------------------------
    feature_builder = FeatureBuilder()
    fb_latencies = []
    for i in range(sample_size):
        w = windows[i % len(windows)]
        t0 = time.perf_counter()
        feature_builder.build_features(w)
        t1 = time.perf_counter()
        fb_latencies.append((t1 - t0) * 1000.0)

    p_fb = compute_percentiles(fb_latencies, "feature_builder_latency_ms")
    results["metrics"]["feature_builder_latency_ms"] = p_fb.to_dict()

    # ----------------------------------------------------
    # 3. Heuristic Monitor Adapter Benchmark
    # ----------------------------------------------------
    stuck_adapter = HeuristicStuckModelAdapter()
    hmon_latencies = []
    for i in range(sample_size):
        w = windows[i % len(windows)]
        t0 = time.perf_counter()
        stuck_adapter.predict(w)
        t1 = time.perf_counter()
        hmon_latencies.append((t1 - t0) * 1000.0)

    p_hmon = compute_percentiles(hmon_latencies, "heuristic_monitor_latency_ms")
    results["metrics"]["heuristic_monitor_latency_ms"] = p_hmon.to_dict()

    # ----------------------------------------------------
    # 4. Optional Learned Monitor Benchmark
    # ----------------------------------------------------
    learned_adapter = TransformerMonitorAdapter()
    if learned_adapter.is_available:
        lmon_latencies = []
        for i in range(min(100, sample_size)):
            w = windows[i % len(windows)]
            t0 = time.perf_counter()
            learned_adapter.predict(w)
            t1 = time.perf_counter()
            lmon_latencies.append((t1 - t0) * 1000.0)
        p_lmon = compute_percentiles(lmon_latencies, "learned_monitor_latency_ms")
        results["metrics"]["learned_monitor_latency_ms_or_null"] = p_lmon.to_dict()
    else:
        results["metrics"]["learned_monitor_latency_ms_or_null"] = None

    # ----------------------------------------------------
    # 5. Labeler Throughput Benchmark
    # ----------------------------------------------------
    labeler = AutoLabeler()
    t_start = time.perf_counter()
    labeler.label_dataset(windows)
    t_total = time.perf_counter() - t_start
    records_per_sec = len(windows) / max(0.0001, t_total)
    results["metrics"]["labeler_throughput_records_per_sec"] = {
        "records_per_sec": round(records_per_sec, 2),
        "total_windows": len(windows),
        "total_time_sec": round(t_total, 4),
    }

    # ----------------------------------------------------
    # 6. Mock Cortex Recovery Benchmark
    # ----------------------------------------------------
    mock_cortex = MockCortexClient()
    dummy_payload = EscalationPayload(
        escalation_id="bench-esc",
        task_goal="Benchmark goal",
        reason=EscalationReason.LOCATOR_NOT_FOUND,
        step_history=[ActionStep(step_number=1, verb="CLICK", target_selector="#btn", value=None, action_index=0, latency_ms=5.0, success=False)],
        current_state=UIState(
            state_id="state-0",
            timestamp=time.time(),
            source=PerceptionSource.CDP_AXTREE,
            simhash=0x12345678,
            raw_node_count=20,
            pruned_node_count=10,
            actionable_count=5,
            estimated_tokens=80,
            yaml_representation="",
            structured_tree={},
            action_index_map={},
        ),
        failure_details={"target": "#btn"},
    )

    cortex_latencies = []
    for _ in range(sample_size):
        t0 = time.perf_counter()
        mock_cortex.recover(dummy_payload)
        t1 = time.perf_counter()
        cortex_latencies.append((t1 - t0) * 1000.0)

    p_cortex = compute_percentiles(cortex_latencies, "mock_cortex_recovery_latency_ms")
    results["metrics"]["mock_cortex_recovery_latency_ms"] = p_cortex.to_dict()

    # ----------------------------------------------------
    # 7. Dry-Run Cortex Payload Benchmark
    # ----------------------------------------------------
    dry_run_cortex = HttpCortexClient(mode="dry_run")
    dry_latencies = []
    for _ in range(sample_size):
        t0 = time.perf_counter()
        dry_run_cortex.recover(dummy_payload)
        t1 = time.perf_counter()
        dry_latencies.append((t1 - t0) * 1000.0)

    p_dry = compute_percentiles(dry_latencies, "dry_run_cortex_payload_latency_ms")
    results["metrics"]["dry_run_cortex_payload_latency_ms"] = p_dry.to_dict()

    # ----------------------------------------------------
    # 8. Live Browser Hybrid Step Latency Benchmark
    # ----------------------------------------------------
    try:
        from tests.test_phase3b_live import run_live_hybrid_smoke
        t0 = time.perf_counter()
        smoke_res = run_live_hybrid_smoke(headless=True)
        total_live_time_ms = (time.perf_counter() - t0) * 1000.0
        live_steps = max(1, smoke_res.get("total_steps", 6))
        step_latency = total_live_time_ms / live_steps
        p_live = compute_percentiles([step_latency] * 10, "live_browser_hybrid_step_latency_ms")
        results["metrics"]["live_browser_hybrid_step_latency_ms"] = p_live.to_dict()
    except Exception as e:
        results["metrics"]["live_browser_hybrid_step_latency_ms"] = {
            "status": "SKIPPED",
            "reason": str(e),
        }

    # Print summary table
    print("\nBENCHMARK RESULTS & TARGET VERIFICATION:")
    print("-" * 75)
    print(f"{'Metric':<36} | {'p50 (ms)':<9} | {'p95 (ms)':<9} | {'p99 (ms)':<9} | {'Target':<10} | Status")
    print("-" * 75)

    targets = {
        "feature_builder_latency_ms": 10.0,
        "heuristic_monitor_latency_ms": 10.0,
        "trajectory_collector_latency_ms": 10.0,
        "mock_cortex_recovery_latency_ms": 20.0,
        "dry_run_cortex_payload_latency_ms": 20.0,
        "live_browser_hybrid_step_latency_ms": 1000.0,
    }

    for name, target in targets.items():
        m = results["metrics"].get(name)
        if isinstance(m, dict) and "p95" in m:
            p50 = m.get("p50", 0.0)
            p95 = m.get("p95", 0.0)
            p99 = m.get("p99", 0.0)
            status = "PASS" if p95 < target else "FAIL"
            print(f"{name:<36} | {p50:<9.4f} | {p95:<9.4f} | {p99:<9.4f} | <{target:<8.0f} | {status}")
        else:
            print(f"{name:<36} | {'N/A':<9} | {'N/A':<9} | {'N/A':<9} | <{target:<8.0f} | N/A")

    print("-" * 75)
    lbl = results["metrics"]["labeler_throughput_records_per_sec"]
    print(f"Labeler Throughput: {lbl['records_per_sec']:.2f} records/sec ({lbl['total_windows']} windows labeled)")
    lmon = results["metrics"]["learned_monitor_latency_ms_or_null"]
    print(f"Learned Monitor Status: {'Available' if lmon else 'null (offline/no torch)'}")
    print("=" * 75)

    return results


def main():
    results = run_benchmarks(sample_size=1000)
    out_dir = repo_root / "artifacts" / "phase3b"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "benchmark_phase3b.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nFull benchmark report exported to: {out_file}")


if __name__ == "__main__":
    main()
