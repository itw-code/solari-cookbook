"""Comprehensive Test Suite for OSWorld Desktop Subset Integration (Phase 4C).

Verifies all Phase 4C requirements:
1. OSWorld task mapper correctly parses sample JSON.
2. OSWorld assertion adapter correctly evaluates file_exist.
3. OSWorld assertion adapter correctly evaluates file_content_match.
4. OSWorld assertion adapter correctly evaluates terminal_output_match.
5. OSWorld assertion adapter correctly evaluates at_spi_state_match (using mock AT-SPI tree).
6. OSWorld runner executes a mock subset task successfully.
7. No external network calls occur in mock mode.
8. OSWorld task mapper correctly parses JSONL streams.
9. OSWorld environment reset restores mock file system, terminal, and AT-SPI state.
10. OSWorld runner correctly handles unsupported assertions (graceful SKIP).
11. OSWorld subset selection contains >= 10 tasks across at least 3 domains (os_fs, terminal, desktop).
12. Public Playwright API compliance (zero private internals in eval/ modules).
13. Full subset batch execution achieves 100% success rate in mock mode.
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

from arc_cua.eval.osworld_assertions import (
    OSWorldAssertionAdapter,
    check_at_spi_state_match,
    check_file_content_match,
    check_file_exist,
    check_osworld_unsupported,
    check_terminal_output_match,
)
from arc_cua.eval.osworld_env import OSWorldEnv
from arc_cua.eval.osworld_mapper import (
    build_at_spi_state_match_assertion,
    build_file_content_match_assertion,
    build_file_exist_assertion,
    build_terminal_output_match_assertion,
    build_unsupported_assertion,
    map_osworld_task,
    parse_osworld_json,
    parse_osworld_jsonl,
)
from arc_cua.eval.osworld_runner import MockOSWorldPage, OSWorldRunner
from arc_cua.eval.schemas import EvalAssertion, EvalAssertionResult, EvalResult, EvalTask
from arc_cua.eval.tasks_osworld import (
    RAW_OSWORLD_SUBSET,
    create_osworld_subset,
    get_osworld_task_by_id,
    get_osworld_tasks_by_domain,
)
from arc_cua.executor_interface import FORBIDDEN_PRIVATE_INTERNALS


# -----------------------------------------------------------------------------
# 1. OSWorld Task Mapper Correctly Parses Sample JSON
# -----------------------------------------------------------------------------
def test_osworld_task_mapper_parses_sample_json():
    """Verify task mapper converts OSWorld JSON into typed EvalTask objects."""
    sample_json = {
        "id": "osworld_test_01",
        "instruction": "Create a deployment config file at /workspace/deploy.cfg",
        "domain": "os_fs",
        "category": "os_fs",
        "start_url": "desktop://os_fs",
        "start_state": {
            "files": {"/workspace/base.cfg": "env=production\n"},
            "terminal_history": ["cd /workspace"],
        },
        "eval": {
            "eval_types": ["file_exist", "file_content_match"],
            "rules": [
                {
                    "type": "file_exist",
                    "file_path": "/workspace/deploy.cfg",
                    "expected": True,
                },
                {
                    "type": "file_content_match",
                    "file_path": "/workspace/deploy.cfg",
                    "expected": "env=staging",
                    "match_type": "substring",
                },
            ],
        },
    }

    json_str = json.dumps(sample_json)
    tasks = parse_osworld_json(json_str)

    assert len(tasks) == 1
    task = tasks[0]
    assert task.task_id == "osworld_test_01"
    assert task.category == "os_fs"
    assert "deploy.cfg" in task.description
    assert len(task.expected_assertions) == 2

    # Check parsed assertions
    a1 = task.expected_assertions[0]
    assert a1.type == "file_exist"
    assert a1.selector == "/workspace/deploy.cfg"
    assert a1.expected is True

    a2 = task.expected_assertions[1]
    assert a2.type == "file_content_match"
    assert a2.selector == "/workspace/deploy.cfg"
    assert a2.expected["pattern"] == "env=staging"
    assert a2.expected["match_type"] == "substring"


# -----------------------------------------------------------------------------
# 2. OSWorld Assertion Adapter Correctly Evaluates file_exist
# -----------------------------------------------------------------------------
def test_osworld_assertion_file_exist():
    """Verify file_exist evaluation under positive, negative, and missing cases."""
    env = OSWorldEnv(
        mode="mock",
        initial_files={"/home/user/workspace/target.txt": "file content"},
    )

    # Positive check: file exists
    a_exist = build_file_exist_assertion("/home/user/workspace/target.txt", expected=True)
    res1 = check_file_exist(a_exist, env)
    assert res1.passed is True
    assert res1.actual["exists"] is True

    # Missing file check: expected True, but missing
    a_missing = build_file_exist_assertion("/home/user/workspace/absent.txt", expected=True)
    res2 = check_file_exist(a_missing, env)
    assert res2.passed is False
    assert "does not exist" in res2.error_message

    # Deletion / absent check: expected False, and it is absent
    a_not_exist = build_file_exist_assertion("/home/user/workspace/absent.txt", expected=False)
    res3 = check_file_exist(a_not_exist, env)
    assert res3.passed is True

    # Deletion check failure: expected False, but file exists
    a_should_not_exist = build_file_exist_assertion("/home/user/workspace/target.txt", expected=False)
    res4 = check_file_exist(a_should_not_exist, env)
    assert res4.passed is False
    assert "NOT to exist" in res4.error_message


# -----------------------------------------------------------------------------
# 3. OSWorld Assertion Adapter Correctly Evaluates file_content_match
# -----------------------------------------------------------------------------
def test_osworld_assertion_file_content_match():
    """Verify file_content_match with substring, regex, exact, and line matching."""
    env = OSWorldEnv(
        mode="mock",
        initial_files={
            "/home/user/workspace/sample.txt": "Alpha Beta Gamma\nversion=2.5.0\nStatus: Healthy\n",
        },
    )

    # Substring match
    a_sub = build_file_content_match_assertion("/home/user/workspace/sample.txt", "Beta Gamma", match_type="substring")
    res_sub = check_file_content_match(a_sub, env)
    assert res_sub.passed is True

    # Regex match
    a_reg = build_file_content_match_assertion("/home/user/workspace/sample.txt", r"version=\d+\.\d+\.\d+", match_type="regex")
    res_reg = check_file_content_match(a_reg, env)
    assert res_reg.passed is True

    # Exact match failure
    a_exact_fail = build_file_content_match_assertion("/home/user/workspace/sample.txt", "Beta Gamma", match_type="exact")
    res_exact_fail = check_file_content_match(a_exact_fail, env)
    assert res_exact_fail.passed is False

    # Exact match success
    env.write_file("/home/user/workspace/exact.txt", "Exact Match Content\n")
    a_exact_pass = build_file_content_match_assertion("/home/user/workspace/exact.txt", "Exact Match Content", match_type="exact")
    res_exact_pass = check_file_content_match(a_exact_pass, env)
    assert res_exact_pass.passed is True

    # Lines include
    a_lines = build_file_content_match_assertion(
        "/home/user/workspace/sample.txt",
        "Alpha Beta Gamma\nStatus: Healthy",
        match_type="lines_include",
    )
    res_lines = check_file_content_match(a_lines, env)
    assert res_lines.passed is True

    # Target file does not exist
    a_not_found = build_file_content_match_assertion("/non/existent.txt", "test")
    res_not_found = check_file_content_match(a_not_found, env)
    assert res_not_found.passed is False
    assert "does not exist" in res_not_found.error_message


# -----------------------------------------------------------------------------
# 4. OSWorld Assertion Adapter Correctly Evaluates terminal_output_match
# -----------------------------------------------------------------------------
def test_osworld_assertion_terminal_output_match():
    """Verify terminal_output_match against stdout output and command history."""
    env = OSWorldEnv(
        mode="mock",
        initial_terminal_history=["git checkout -b feature", "git add ."],
        initial_terminal_output=["Switched to a new branch 'feature'", "All checks passed: OK"],
    )

    # Substring match against terminal output
    a_sub = build_terminal_output_match_assertion("checks passed: OK", match_type="substring")
    res_sub = check_terminal_output_match(a_sub, env)
    assert res_sub.passed is True

    # Regex match
    a_reg = build_terminal_output_match_assertion(r"branch '[\w\-]+'", match_type="regex")
    res_reg = check_terminal_output_match(a_reg, env)
    assert res_reg.passed is True

    # Command history check
    a_cmd = build_terminal_output_match_assertion("git checkout", match_type="command")
    res_cmd = check_terminal_output_match(a_cmd, env)
    assert res_cmd.passed is True

    # Command not found check
    a_cmd_fail = build_terminal_output_match_assertion("npm install", match_type="command")
    res_cmd_fail = check_terminal_output_match(a_cmd_fail, env)
    assert res_cmd_fail.passed is False
    assert "not found in terminal history" in res_cmd_fail.error_message


# -----------------------------------------------------------------------------
# 5. OSWorld Assertion Adapter Correctly Evaluates at_spi_state_match
# -----------------------------------------------------------------------------
def test_osworld_assertion_at_spi_state_match():
    """Verify at_spi_state_match inspection of mock desktop accessibility tree."""
    env = OSWorldEnv(mode="mock")

    # App 1: VS Code - Push Button "Run Benchmark Test"
    a_code_btn = build_at_spi_state_match_assertion(
        app_name="code",
        role="push_button",
        name="Run Benchmark Test",
        state="showing",
    )
    res1 = check_at_spi_state_match(a_code_btn, env)
    assert res1.passed is True
    assert res1.actual["matched_count"] >= 1
    assert "showing" in res1.actual["first_match"]["states"]

    # App 1: VS Code - Entry "Search files by name (Ctrl+P)"
    a_code_entry = build_at_spi_state_match_assertion(
        app_name="code",
        role="entry",
        name="Search files by name",
        state="enabled",
    )
    res2 = check_at_spi_state_match(a_code_entry, env)
    assert res2.passed is True

    # App 2: GNOME Terminal - Page Tab "Bash Tab 1"
    a_term_tab = build_at_spi_state_match_assertion(
        app_name="gnome-terminal",
        role="page_tab",
        name="Bash Tab 1",
        state="selected",
    )
    res3 = check_at_spi_state_match(a_term_tab, env)
    assert res3.passed is True

    # Missing widget check
    a_missing_widget = build_at_spi_state_match_assertion(
        app_name="nonexistent_app",
        role="button",
        name="Cancel",
    )
    res_missing = check_at_spi_state_match(a_missing_widget, env)
    assert res_missing.passed is False
    assert "Expected matching AT-SPI widget" in res_missing.error_message


# -----------------------------------------------------------------------------
# 6. OSWorld Runner Executes a Mock Subset Task Successfully
# -----------------------------------------------------------------------------
def test_osworld_runner_executes_mock_subset_task():
    """Verify OSWorldRunner executes a task, performs actions, and verifies assertions."""
    runner = OSWorldRunner(mode="hybrid", mock_mode=True)
    task = get_osworld_task_by_id("201")
    assert task is not None

    result: EvalResult = runner.run_task(task)

    assert result.task_id == "201"
    assert result.success is True
    assert result.aborted is False
    assert len(result.assertion_results) == 2
    assert all(a.passed for a in result.assertion_results)
    assert result.metadata["osworld"] is True

    # Verify file was genuinely created in runner's env
    assert runner.env.file_exists("/home/user/workspace/summary.txt")
    assert "Phase 4C Benchmark Ready" in runner.env.read_file("/home/user/workspace/summary.txt")


# -----------------------------------------------------------------------------
# 7. No External Network Calls Occur in Mock Mode
# -----------------------------------------------------------------------------
def test_no_external_network_calls_in_mock_mode(monkeypatch: pytest.MonkeyPatch):
    """Verify OSWorld evaluation in mock mode makes zero external network socket connections."""
    real_connect = socket.socket.connect

    def guarded_connect(self, address):
        host = address[0]
        if host in ("127.0.0.1", "localhost", "::1"):
            return real_connect(self, address)
        raise RuntimeError(f"Prohibited external network call detected to {address}")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)

    runner = OSWorldRunner(mode="hybrid", mock_mode=True)
    task = get_osworld_task_by_id("205")
    assert task is not None

    res = runner.run_task(task)
    assert res.success is True


# -----------------------------------------------------------------------------
# 8. JSONL Stream Parsing
# -----------------------------------------------------------------------------
def test_task_mapper_parses_jsonl():
    """Verify task mapper parses line-delimited JSONL benchmark definitions."""
    lines = [
        json.dumps({
            "id": "os_01",
            "instruction": "Test line 1",
            "domain": "os_fs",
            "eval": {"eval_types": ["file_exist"], "file": {"path": "/tmp/a.txt", "exist": True}},
        }),
        json.dumps({
            "id": "os_02",
            "instruction": "Test line 2",
            "domain": "terminal",
            "eval": {"eval_types": ["terminal_output_match"], "terminal": {"expected": "done"}},
        }),
    ]
    jsonl_str = "\n".join(lines)
    tasks = parse_osworld_jsonl(jsonl_str)

    assert len(tasks) == 2
    assert tasks[0].task_id == "os_01"
    assert tasks[0].category == "os_fs"
    assert tasks[1].task_id == "os_02"
    assert tasks[1].category == "terminal"


# -----------------------------------------------------------------------------
# 9. Environment Reset Restores State
# -----------------------------------------------------------------------------
def test_osworld_env_reset_restores_state():
    """Verify OSWorldEnv reset restores files, terminal, and AT-SPI state."""
    env = OSWorldEnv(
        mode="mock",
        initial_files={"/init.txt": "baseline content"},
        initial_terminal_history=["init_cmd"],
        initial_terminal_output=["baseline output"],
    )

    # Mutate environment
    env.write_file("/temp.txt", "temporary content")
    env.execute_command("echo 'extra' >> /temp.txt")
    env.append_terminal_output("extra output")
    env.update_widget_state(
        app_name="code",
        role="push_button",
        name="Run Benchmark Test",
        add_states=["custom_mutated_state"],
    )

    assert env.file_exists("/temp.txt")
    assert len(env.get_terminal_history()) > 1

    # Reset environment
    env.reset()

    assert env.file_exists("/init.txt")
    assert not env.file_exists("/temp.txt")
    assert env.get_terminal_history() == ["init_cmd"]
    assert env.get_terminal_output() == "baseline output"


# -----------------------------------------------------------------------------
# 10. Unsupported Assertions Handled Gracefully
# -----------------------------------------------------------------------------
def test_osworld_runner_handles_unsupported_assertions():
    """Verify unsupported evaluation types (e.g. image_similarity) are skipped gracefully."""
    raw_task = {
        "id": "os_unsupported_99",
        "instruction": "Capture screenshot and match visual layout",
        "domain": "desktop",
        "eval": {
            "eval_types": ["image_similarity", "vlm_score"],
        },
    }

    task = map_osworld_task(raw_task)
    assert len(task.expected_assertions) == 2
    assert all(a.type == "skip" for a in task.expected_assertions)

    # When skip_unsupported_assertions=True, task passes
    runner = OSWorldRunner(mode="hybrid", skip_unsupported_assertions=True)
    res = runner.run_task(task)
    assert res.success is True
    assert all(a.actual == "SKIPPED" for a in res.assertion_results)

    # When skip_unsupported_assertions=False, strict adapter marks them failed
    strict_adapter = OSWorldAssertionAdapter(env=runner.env, skip_unsupported=False)
    strict_res = strict_adapter.evaluate_all(task.expected_assertions)
    # The assertions were mapped to type "skip", which evaluate_assertion passes
    # If an assertion has raw unsupported type, it fails:
    unsupported_raw_assertion = EvalAssertion(type="vlm_score", expected={})
    strict_eval = strict_adapter.evaluate_assertion(unsupported_raw_assertion)
    assert strict_eval.passed is False
    assert "Unsupported OSWorld assertion type" in strict_eval.error_message


# -----------------------------------------------------------------------------
# 11. Subset Selection Contains >= 10 Tasks Across >= 3 Domains
# -----------------------------------------------------------------------------
def test_osworld_subset_selection_integrity():
    """Verify subset contains 12 tasks across os_fs, terminal, and desktop domains."""
    tasks = create_osworld_subset()
    assert len(tasks) == 12

    domains = set(t.category for t in tasks)
    assert len(domains) >= 3
    assert "os_fs" in domains
    assert "terminal" in domains
    assert "desktop" in domains

    # Verify presence of all four evaluation assertion modalities
    all_assertion_types = set(
        a.type.value if hasattr(a.type, "value") else str(a.type)
        for t in tasks
        for a in t.expected_assertions
    )
    assert "file_exist" in all_assertion_types
    assert "file_content_match" in all_assertion_types
    assert "terminal_output_match" in all_assertion_types
    assert "at_spi_state_match" in all_assertion_types


# -----------------------------------------------------------------------------
# 12. Public Playwright API Compliance
# -----------------------------------------------------------------------------
def test_public_playwright_api_compliance():
    """AST check verifying zero forbidden Playwright private internals in Phase 4C modules."""
    eval_dir = REPO_ROOT / "src" / "arc_cua" / "eval"
    phase4c_files = [
        eval_dir / "osworld_env.py",
        eval_dir / "osworld_mapper.py",
        eval_dir / "osworld_assertions.py",
        eval_dir / "tasks_osworld.py",
        eval_dir / "osworld_runner.py",
    ]

    violations = []
    for f in phase4c_files:
        if not f.exists():
            violations.append(f"Missing file: {f}")
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_PRIVATE_INTERNALS:
                violations.append(f"{f.name}:{node.lineno} uses forbidden private internal: '{node.attr}'")
            elif isinstance(node, ast.ImportFrom) and node.module:
                for forbidden in FORBIDDEN_PRIVATE_INTERNALS:
                    if forbidden in node.module:
                        violations.append(f"{f.name}:{node.lineno} imports forbidden internal: '{forbidden}'")

    assert violations == [], f"Playwright private internal violations found: {violations}"


# -----------------------------------------------------------------------------
# 13. Full Subset Batch Execution Achieves 100% Success Rate in Mock Mode
# -----------------------------------------------------------------------------
def test_osworld_runner_all_subset_tasks():
    """Verify all 12 OSWorld subset tasks execute and pass in mock mode."""
    runner = OSWorldRunner(mode="hybrid", mock_mode=True)
    tasks = create_osworld_subset()

    results = runner.run_all(tasks)

    assert len(results) == 12
    failed_tasks = [r.task_id for r in results if not r.success]
    assert failed_tasks == [], f"The following OSWorld tasks failed: {failed_tasks}"

    success_rate = sum(1 for r in results if r.success) / len(results)
    assert success_rate == 1.0
