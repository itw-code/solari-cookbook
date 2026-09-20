"""Comprehensive Test Suite for ARC Evaluation Harness (Phase 4A).

Verifies all Task 4A requirements:
1. Eval schemas validate (EvalTask, EvalAssertion, EvalResult, CostRecord, ScorecardSummary, EvalRunSummary).
2. Local task suite contains at least 12 tasks.
3. Local task suite has all required categories.
4. Assertion engine detects success.
5. Assertion engine detects failure.
6. Eval runner runs in mock mode.
7. Eval runner produces structured EvalResult.
8. Cost ledger produces cost record.
9. Scorecard builder aggregates results and computes percentiles.
10. Report generator writes all 5 required artifacts.
11. Hybrid mode recovers at least one forced stuck task.
12. Reflex-only mode fails at least one forced stuck task.
13. Public Playwright API compliance remains enforced (zero private internals in eval/).
14. No external network calls occur during evaluation.
15. Live browser eval smoke test (skips gracefully if Chromium is unavailable).
"""

from __future__ import annotations

import ast
import json
import pathlib
import socket
import sys
from typing import Any, Dict, List
import pytest
REPO_ROOT = pathlib.Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from arc_cua.eval.assertions import (
    check_element_state,
    check_input_value,
    check_page_title,
    check_state_hash_changed,
    check_url,
    check_visible_text,
    evaluate_assertion,
)
from arc_cua.eval.cost import CostLedger, CostModelConfig
from arc_cua.eval.runner import EvalCortexClient, EvalRunner, MockEvalPage
from arc_cua.eval.schemas import (
    AssertionType,
    CostRecord,
    ElementState,
    EvalAssertion,
    EvalAssertionResult,
    EvalResult,
    EvalRunSummary,
    EvalTask,
    ScorecardSummary,
)
from arc_cua.eval.scorecard import ScorecardBuilder
from arc_cua.eval.tasks_local import (
    create_local_tasks,
    get_fixture_url,
    get_task_by_id,
    get_tasks_by_category,
)
from arc_cua.executor_interface import FORBIDDEN_PRIVATE_INTERNALS
from arc_cua.schemas import ActionStep

LIVE_BROWSER_EVAL_SMOKE_SKIPPED = "LIVE_BROWSER_EVAL_SMOKE_SKIPPED"


# 1. Eval schemas validate
def test_eval_schemas_validate():
    """Verify serialization, deserialization, and field integrity of all evaluation schemas."""
    assertion = EvalAssertion(
        type=AssertionType.VISIBLE_TEXT,
        selector="div#status",
        expected="Success",
        description="Check status is success",
        timeout_ms=1500.0,
    )
    assert assertion.type == AssertionType.VISIBLE_TEXT
    a_dict = assertion.to_dict()
    a_rebuilt = EvalAssertion.from_dict(a_dict)
    assert a_rebuilt.type == AssertionType.VISIBLE_TEXT
    assert a_rebuilt.selector == "div#status"

    task = EvalTask(
        task_id="test_task_1",
        name="Test Task",
        category="healthy_form",
        description="Sample task for validation",
        start_url="file:///tmp/page.html",
        action_steps=[
            ActionStep(step_number=1, verb="CLICK", target_selector="button#ok", value=None, action_index=None, latency_ms=0, success=True)
        ],
        expected_assertions=[assertion],
    )
    t_dict = task.to_dict()
    t_rebuilt = EvalTask.from_dict(t_dict)
    assert t_rebuilt.task_id == "test_task_1"
    assert len(t_rebuilt.expected_assertions) == 1

    cost = CostRecord(
        task_id="test_task_1",
        mock_cortex_cost_usd=0.0,
        local_reflex_cost_usd=0.00001,
        browser_runtime_ms=150.0,
        total_cost_usd=0.00001,
    )
    c_dict = cost.to_dict()
    c_rebuilt = CostRecord.from_dict(c_dict)
    assert c_rebuilt.total_cost_usd == 0.00001

    res = EvalResult(
        task_id="test_task_1",
        success=True,
        total_steps=2,
        reflex_steps=2,
        escalations=0,
        recoveries_attempted=0,
        recoveries_succeeded=0,
        milestones_detected=1,
        duration_ms=250.0,
        cost_usd=0.00001,
    )
    r_dict = res.to_dict()
    r_rebuilt = EvalResult.from_dict(r_dict)
    assert r_rebuilt.success is True
    assert r_rebuilt.total_steps == 2

    scorecard = ScorecardSummary(
        total_tasks=1,
        successful_tasks=1,
        success_rate=1.0,
        mode="hybrid",
    )
    s_dict = scorecard.to_dict()
    s_rebuilt = ScorecardSummary.from_dict(s_dict)
    assert s_rebuilt.success_rate == 1.0


# 2. Local task suite contains at least 12 tasks
def test_local_task_suite_count():
    """Verify local task suite has at least 12 defined tasks."""
    tasks = create_local_tasks()
    assert len(tasks) >= 12, f"Expected at least 12 tasks, got {len(tasks)}"


# 3. Local task suite has required categories
def test_local_task_suite_categories():
    """Verify all 12 required categories are present in the synthetic task suite."""
    required_categories = {
        "healthy_form",
        "healthy_navigation",
        "healthy_dropdown",
        "healthy_scroll",
        "healthy_input_validation",
        "stuck_noop",
        "stuck_missing_locator",
        "recovery_after_noop",
        "recovery_after_timeout",
        "milestone_multi_step",
        "readiness_blocked_element",
        "assertion_failure",
    }
    tasks = create_local_tasks()
    present_categories = {t.category for t in tasks}
    missing = required_categories - present_categories
    assert not missing, f"Missing required task categories: {missing}"


# 4. Assertion engine detects success
def test_assertion_engine_detects_success():
    """Verify assertion engine accurately confirms passing DOM assertions."""
    page = MockEvalPage()
    page.handle_fill("input#user-name", "tester")
    page.handle_click("button#submit-form-btn")

    # 1. Visible text check
    res_text = check_visible_text(page, expected="Form submitted: tester ()", selector="div#form-result")
    assert res_text.passed is True
    assert res_text.error_message is None

    # 2. Page title check
    res_title = check_page_title(page, expected_title="ARC Evaluation Suite")
    assert res_title.passed is True

    # 3. Element state check
    res_state = check_element_state(page, selector="div#form-result", expected_state=ElementState.VISIBLE)
    assert res_state.passed is True

    # 4. State hash change check
    res_hash = check_state_hash_changed(initial_hash=100, current_hash=250, expected_changed=True)
    assert res_hash.passed is True


# 5. Assertion engine detects failure
def test_assertion_engine_detects_failure():
    """Verify assertion engine catches failed assertions safely without crashing."""
    page = MockEvalPage()

    # Mismatched text
    res_text = check_visible_text(page, expected="NonExistentExpectedText", selector="div#form-result")
    assert res_text.passed is False
    assert res_text.error_message is not None

    # Mismatched URL
    res_url = check_url(page, expected="https://unknown-domain-fail.com", timeout_ms=10.0)
    assert res_url.passed is False
    assert res_url.error_message is not None

    # Mismatched element state
    res_state = check_element_state(page, selector="div#form-result", expected_state=ElementState.HIDDEN)
    assert res_state.passed is False
    assert res_state.error_message is not None


# 6. Eval runner runs in mock mode
def test_eval_runner_runs_in_mock_mode():
    """Verify EvalRunner executes tasks in pure mock mode."""
    runner = EvalRunner(mode="hybrid", mock_mode=True)
    task = get_task_by_id("task_healthy_form")
    assert task is not None
    result = runner.run_task(task)
    assert isinstance(result, EvalResult)
    assert result.task_id == "task_healthy_form"
    assert result.success is True


# 7. Eval runner produces EvalResult
def test_eval_runner_produces_eval_result():
    """Verify completeness of fields in EvalResult."""
    runner = EvalRunner(mode="hybrid", mock_mode=True)
    task = get_task_by_id("task_healthy_navigation")
    assert task is not None
    result = runner.run_task(task)
    assert result.total_steps > 0
    assert result.reflex_steps > 0
    assert result.duration_ms > 0.0
    assert len(result.assertion_results) == len(task.expected_assertions)
    assert "category" in result.metadata


# 8. Cost ledger produces cost record
def test_cost_ledger_produces_cost_record():
    """Verify CostLedger calculation and aggregation."""
    ledger = CostLedger()
    record = ledger.calculate_task_cost(
        task_id="task_test",
        reflex_steps=4,
        cortex_calls=1,
        browser_runtime_ms=500.0,
        is_mock_cortex=True,
    )
    assert record.task_id == "task_test"
    assert record.mock_cortex_cost_usd == 0.0
    assert record.total_cost_usd >= 0.0

    aggregated = ledger.aggregate_costs([record])
    assert "total_cost_usd" in aggregated
    assert "avg_cost_per_task_usd" in aggregated


# 9. Scorecard builder aggregates results
def test_scorecard_builder_aggregates_results():
    """Verify ScorecardBuilder computes summary metrics and percentiles."""
    r1 = EvalResult(task_id="t1", success=True, total_steps=3, reflex_steps=3, duration_ms=100.0)
    r2 = EvalResult(task_id="t2", success=False, total_steps=2, reflex_steps=2, duration_ms=200.0)
    scorecard = ScorecardBuilder.build([r1, r2], mode="hybrid", is_mocked=True)

    assert scorecard.total_tasks == 2
    assert scorecard.successful_tasks == 1
    assert scorecard.success_rate == 0.5
    assert scorecard.p50_duration_ms > 0.0
    assert scorecard.reflex_step_share == 1.0


# 10. Report generator writes artifacts
def test_report_generator_writes_artifacts(tmp_path: pathlib.Path):
    """Verify scripts/report_phase4a.py produces all 5 required artifacts."""
    from scripts.report_phase4a import run_evaluation

    res = run_evaluation(mock_mode=True, output_dir=tmp_path)
    assert (tmp_path / "report.md").exists()
    assert (tmp_path / "scorecard.json").exists()
    assert (tmp_path / "results.jsonl").exists()
    assert (tmp_path / "trajectory_logs.jsonl").exists()
    assert (tmp_path / "summary.json").exists()

    scorecard_content = json.loads((tmp_path / "scorecard.json").read_text(encoding="utf-8"))
    assert "success_rate" in scorecard_content
    assert "comparison" in scorecard_content


# 11. Hybrid mode recovers at least one forced stuck task
def test_hybrid_mode_recovers_forced_stuck_task():
    """Verify HybridRunner detects stuck state and recovers via Mock Cortex."""
    runner = EvalRunner(mode="hybrid", mock_mode=True)
    task = get_task_by_id("task_recovery_after_noop")
    assert task is not None
    result = runner.run_task(task)

    assert result.escalations > 0, "Hybrid mode must escalate on stuck loop"
    assert result.recoveries_succeeded > 0, "Hybrid mode must successfully execute recovery"
    assert result.success is True, "Task must succeed after recovery"


# 12. Reflex-only mode fails at least one forced stuck task
def test_reflex_only_fails_forced_stuck_task():
    """Verify ReflexRunner cannot recover from forced stuck loops without Cortex."""
    runner = EvalRunner(mode="reflex_only", mock_mode=True)
    task = get_task_by_id("task_recovery_after_noop")
    assert task is not None
    result = runner.run_task(task)

    assert result.success is False, "Reflex-only must fail task that requires recovery"
    assert result.recoveries_succeeded == 0, "Reflex-only has zero recoveries"


# 13. Public Playwright API compliance remains enforced
def test_public_playwright_api_compliance():
    """Static analysis verifying no forbidden private Playwright internals in eval/."""
    eval_dir = REPO_ROOT / "src" / "arc_cua" / "eval"
    for py_file in eval_dir.glob("*.py"):
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
        used_attributes: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                used_attributes.add(node.attr)

        violations = used_attributes.intersection(FORBIDDEN_PRIVATE_INTERNALS)
        assert not violations, (
            f"Public API Violation in {py_file.name}: referenced private internals {violations}"
        )


# 14. No external network calls occur
def test_no_external_network_calls(monkeypatch: pytest.MonkeyPatch):
    """Verify eval suite executes without initiating any external network sockets."""
    real_connect = socket.socket.connect

    def guarded_connect(self, address):
        host, port = address[0], address[1]
        # Allow local inter-process pipes or 127.0.0.1 for local CDP/Chromium
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise ConnectionRefusedError(f"External network call blocked: {host}:{port}")
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)

    runner = EvalRunner(mode="hybrid", mock_mode=True)
    task = get_task_by_id("task_healthy_form")
    assert task is not None
    res = runner.run_task(task)
    assert res.success is True


# 15. Live browser eval smoke test (if Chromium available)
def test_live_browser_eval_smoke():
    """Execute live local eval task with real Chromium browser if installed."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
    except Exception as e:
        pytest.skip(f"{LIVE_BROWSER_EVAL_SMOKE_SKIPPED}: Chromium not available ({e})")

    runner = EvalRunner(mode="hybrid", mock_mode=False, headless=True)
    task = get_task_by_id("task_healthy_form")
    assert task is not None
    result = runner.run_task(task)
    assert result.success is True
    assert result.total_steps >= 3
