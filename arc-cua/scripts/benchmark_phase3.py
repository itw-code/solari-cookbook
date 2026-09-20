"""Benchmark Phase 3A Components Overhead.

Measures:
- stuck_monitor_latency_ms
- milestone_monitor_latency_ms
- escalation_controller_latency_ms
- recovery_compiler_latency_ms
- mock_cortex_latency_ms
- hybrid_overhead_per_step_ms

Reports p50, p95, p99 against architectural targets.
"""

from __future__ import annotations

import os
import pathlib
import platform
import sys
import time
from typing import Dict, List

# Ensure src is in python path
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

from arc_cua.cortex.mock_cortex import MockCortexClient
from arc_cua.cortex.recovery_compiler import RecoveryCompiler
from arc_cua.hybrid_runner import HybridRunner
from arc_cua.monitors.escalation_controller import EscalationController
from arc_cua.monitors.milestone_monitor import MilestoneMonitor
from arc_cua.monitors.stuck_monitor import StepTelemetry, StuckMonitor
from arc_cua.schemas import (
    ActionStep,
    EscalationPayload,
    EscalationReason,
    PerceptionSource,
    PlanSource,
    RecoveryPlan,
    UIState,
)
from arc_cua.telemetry import compute_percentiles


def run_benchmarks(sample_size: int = 1000):
    env_str = f"{platform.system()} {platform.release()} ({platform.machine()}), Python {platform.python_version()}"
    integration_mode = "mock"

    stuck_monitor = StuckMonitor(window_size=5)
    milestone_monitor = MilestoneMonitor()
    escalation_controller = EscalationController()
    recovery_compiler = RecoveryCompiler()
    mock_cortex = MockCortexClient()

    # Test payload for Cortex & Compiler
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
    cortex_resp = mock_cortex.recover(dummy_payload)

    # 1. Benchmark Stuck Monitor
    stuck_latencies: List[float] = []
    for i in range(sample_size):
        step = StepTelemetry(
            step_id=i,
            verb="CLICK",
            target="#btn",
            success=True,
            state_changed=(i % 3 != 0),
            state_hash=0x1000 + (i % 2),
            hamming_distance=4 if (i % 3 != 0) else 0,
        )
        t0 = time.perf_counter()
        stuck_monitor.evaluate_step(step)
        dt = (time.perf_counter() - t0) * 1000.0
        stuck_latencies.append(dt)

    # 2. Benchmark Milestone Monitor
    milestone_latencies: List[float] = []
    for i in range(sample_size):
        step = StepTelemetry(
            step_id=i,
            verb="CLICK",
            target="#submit",
            success=True,
            state_changed=True,
            hamming_distance=15,
            url_changed=(i % 10 == 0),
            url="https://app.arc.local/done",
        )
        t0 = time.perf_counter()
        milestone_monitor.evaluate(step, goal="Complete submission", state_text_after="Done complete")
        dt = (time.perf_counter() - t0) * 1000.0
        milestone_latencies.append(dt)

    # 3. Benchmark Escalation Controller
    controller_latencies: List[float] = []
    for i in range(sample_size):
        stuck_sig = stuck_monitor.evaluate_window()
        t0 = time.perf_counter()
        escalation_controller.decide(stuck_sig)
        dt = (time.perf_counter() - t0) * 1000.0
        controller_latencies.append(dt)

    # 4. Benchmark Recovery Compiler
    compiler_latencies: List[float] = []
    for i in range(sample_size):
        t0 = time.perf_counter()
        recovery_compiler.compile(cortex_resp, start_step=1)
        dt = (time.perf_counter() - t0) * 1000.0
        compiler_latencies.append(dt)

    # 5. Benchmark Mock Cortex
    cortex_latencies: List[float] = []
    for i in range(sample_size):
        t0 = time.perf_counter()
        mock_cortex.recover(dummy_payload)
        dt = (time.perf_counter() - t0) * 1000.0
        cortex_latencies.append(dt)

    # 6. Benchmark Hybrid Overhead Per Step (Monitors + Controller evaluation)
    hybrid_latencies: List[float] = []
    for i in range(sample_size):
        step = StepTelemetry(
            step_id=i,
            verb="CLICK",
            target="#btn",
            success=True,
            state_changed=True,
            hamming_distance=10,
        )
        t0 = time.perf_counter()
        s_sig = stuck_monitor.evaluate_step(step)
        m_sig = milestone_monitor.evaluate(step, goal="Benchmark step")
        escalation_controller.decide(s_sig, m_sig, step=step)
        dt = (time.perf_counter() - t0) * 1000.0
        hybrid_latencies.append(dt)

    metrics = [
        ("stuck_monitor_latency_ms", stuck_latencies, "<10ms"),
        ("milestone_monitor_latency_ms", milestone_latencies, "<10ms"),
        ("escalation_controller_latency_ms", controller_latencies, "<5ms"),
        ("recovery_compiler_latency_ms", compiler_latencies, "<5ms"),
        ("mock_cortex_latency_ms", cortex_latencies, "<20ms"),
        ("hybrid_overhead_per_step_ms", hybrid_latencies, "<25ms"),
    ]

    print("=" * 70)
    print("PHASE 3A BENCHMARK OVERHEAD RESULTS")
    print(f"Sample Size: {sample_size}")
    print(f"Environment: {env_str}")
    print(f"Integration Mode: {integration_mode}")
    print("=" * 70)

    results = {}
    for name, latencies, target in metrics:
        dist = compute_percentiles(latencies, metric_name=name)
        results[name] = dist
        target_met = "PASS" if (
            (name == "stuck_monitor_latency_ms" and dist.p95 < 10.0)
            or (name == "milestone_monitor_latency_ms" and dist.p95 < 10.0)
            or (name == "escalation_controller_latency_ms" and dist.p95 < 5.0)
            or (name == "recovery_compiler_latency_ms" and dist.p95 < 5.0)
            or (name == "mock_cortex_latency_ms" and dist.p95 < 20.0)
            or (name == "hybrid_overhead_per_step_ms" and dist.p95 < 25.0)
        ) else "FAIL"

        print(f"\nMetric: {name}")
        print(f"  Target p95: {target} [{target_met}]")
        print(f"  p50: {dist.p50:.4f} ms")
        print(f"  p95: {dist.p95:.4f} ms")
        print(f"  p99: {dist.p99:.4f} ms")
        print(f"  mean: {dist.mean:.4f} ms (min: {dist.min:.4f} ms, max: {dist.max:.4f} ms)")

    return results


if __name__ == "__main__":
    run_benchmarks(1000)
