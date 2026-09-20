"""Comprehensive Test Suite for WebArena-Verified Subset Integration (Phase 4B).

Verifies all Phase 4B requirements:
1. WebArena task mapper correctly parses sample JSON.
2. WebArena assertion adapter correctly evaluates url_match (exact, prefix, regex, normalization).
3. WebArena assertion adapter correctly evaluates string_match (exact, fuzzy, must_include).
4. WebArena assertion adapter correctly evaluates program_html (using mock DB and DB diff).
5. WebArena runner executes a mock subset task successfully.
6. WebArena runner correctly handles unsupported assertion types (graceful SKIP).
7. No external network calls occur in mock mode.
8. WebArena task mapper correctly parses JSONL streams.
9. WebArena subset selection contains >= 10 tasks across at least 3 domains (Reddit, Shopping, GitLab).
10. WebArena environment reset restores mock database state to baseline.
11. DatabaseDiffEngine accurately detects row insertions, updates, and deletions.
12. Public Playwright API compliance (zero private internals in eval/ modules).
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

from arc_cua.eval.schemas import EvalAssertion, EvalAssertionResult, EvalResult, EvalTask
from arc_cua.eval.tasks_webarena import (
    RAW_WEBARENA_SUBSET,
    create_webarena_subset,
    get_webarena_task_by_id,
    get_webarena_tasks_by_domain,
)
from arc_cua.eval.webarena_assertions import (
    WebArenaAssertionAdapter,
    check_webarena_program_html,
    check_webarena_string_match,
    check_webarena_unsupported,
    check_webarena_url_match,
    normalize_text,
    normalize_url,
)
from arc_cua.eval.webarena_env import (
    DatabaseDiffEngine,
    DatabaseDiffReport,
    WebArenaEnv,
)
from arc_cua.eval.webarena_mapper import (
    build_program_html_assertion,
    build_string_match_assertion,
    build_unsupported_assertion,
    build_url_match_assertion,
    map_webarena_task,
    parse_webarena_json,
    parse_webarena_jsonl,
)
from arc_cua.eval.webarena_runner import MockWebArenaPage, WebArenaRunner
from arc_cua.executor_interface import FORBIDDEN_PRIVATE_INTERNALS


# -----------------------------------------------------------------------------
# 1. Task Mapper JSON Parsing
# -----------------------------------------------------------------------------
def test_task_mapper_parses_sample_json():
    """Verify WebArena task mapper correctly parses single objects and arrays from JSON."""
    raw_task = {
        "task_id": 42,
        "intent": "Search for noise-cancelling headphones and add to cart",
        "start_url": "__SHOPPING__/products/headphones",
        "sites": ["shopping"],
        "require_login": False,
        "eval": {
            "eval_types": ["url_match", "string_match", "program_html"],
            "reference_url": "__SHOPPING__/products/headphones",
            "url_note": "exact",
            "reference_answers": {"fuzzy_match": ["Noise Cancelling Headphones", "$199.99"]},
            "program_html": [
                {
                    "point": "db",
                    "locator": "SELECT count(*) as count FROM shopping_products WHERE sku = 'SKU-HEADPHONES-02'",
                    "expected": 1,
                }
            ],
        },
    }

    env = WebArenaEnv(mode="mock")
    task = map_webarena_task(raw_task, env=env)

    assert task.task_id == "webarena_42"
    assert task.category == "shopping"
    assert "headphones" in task.start_url
    assert len(task.expected_assertions) == 3

    assert task.expected_assertions[0].type == "url_match"
    assert task.expected_assertions[1].type == "string_match"
    assert task.expected_assertions[2].type == "program_html"
    assert task.metadata["supported"] is True

    # Parse JSON string array
    tasks = parse_webarena_json(json.dumps([raw_task]), env=env)
    assert len(tasks) == 1
    assert tasks[0].task_id == "webarena_42"


# -----------------------------------------------------------------------------
# 2. URL Match Assertion
# -----------------------------------------------------------------------------
def test_assertion_adapter_url_match():
    """Verify url_match handles exact, prefix, query normalization, and regex patterns."""
    env = WebArenaEnv(mode="mock")
    adapter = WebArenaAssertionAdapter(env=env)

    # Exact match with normalization (trailing slashes)
    a_exact = build_url_match_assertion("http://127.0.0.1:9999/f/technology/")
    r1 = adapter.evaluate(a_exact, current_url="http://127.0.0.1:9999/f/technology")
    assert r1.passed is True

    # Exact match with query params (different order)
    a_query = build_url_match_assertion("http://127.0.0.1:7770/search?q=laptop&sort=price")
    r2 = adapter.evaluate(a_query, current_url="http://127.0.0.1:7770/search?sort=price&q=laptop")
    assert r2.passed is True

    # Prefix match
    a_prefix = build_url_match_assertion("http://127.0.0.1:8023/core/engine", url_note="prefix")
    r3 = adapter.evaluate(a_prefix, current_url="http://127.0.0.1:8023/core/engine/issues/1")
    assert r3.passed is True

    # Regex match
    a_regex = build_url_match_assertion(r"^http://127\.0\.0\.1:9999/f/[a-z]+/\d+$", url_note="regex")
    r4 = adapter.evaluate(a_regex, current_url="http://127.0.0.1:9999/f/technology/42")
    assert r4.passed is True

    # Mismatch failure
    a_fail = build_url_match_assertion("http://127.0.0.1:9999/f/science")
    r5 = adapter.evaluate(a_fail, current_url="http://127.0.0.1:9999/f/technology")
    assert r5.passed is False
    assert "Expected URL" in (r5.error_message or "")


# -----------------------------------------------------------------------------
# 3. String Match Assertion
# -----------------------------------------------------------------------------
def test_assertion_adapter_string_match():
    """Verify string_match handles fuzzy substring, exact match, and must_include tokens."""
    adapter = WebArenaAssertionAdapter()

    page_text = "Welcome to Arc Research! We provide autonomous CUA systems and evaluation benches."

    # Fuzzy match passes on substring
    a_fuzzy = build_string_match_assertion({"fuzzy_match": ["Arc Research", "CUA systems"]})
    r1 = adapter.evaluate(a_fuzzy, page_text=page_text)
    assert r1.passed is True

    # Case insensitive and normalized whitespace
    a_case = build_string_match_assertion({"fuzzy_match": ["  arc  research  "]})
    r2 = adapter.evaluate(a_case, page_text=page_text)
    assert r2.passed is True

    # Must include tokens (all must be present)
    a_must = build_string_match_assertion({"must_include": ["Arc", "autonomous", "evaluation"]})
    r3 = adapter.evaluate(a_must, page_text=page_text)
    assert r3.passed is True

    # Missing must_include token fails
    a_must_fail = build_string_match_assertion({"must_include": ["Arc", "NonExistentWord"]})
    r4 = adapter.evaluate(a_must_fail, page_text=page_text)
    assert r4.passed is False
    assert "missing required tokens" in (r4.error_message or "")

    # Exact match fails if whole text doesn't match
    a_exact = build_string_match_assertion({"exact_match": "Arc Research"})
    r5 = adapter.evaluate(a_exact, page_text=page_text)
    assert r5.passed is False


# -----------------------------------------------------------------------------
# 4. Program HTML (Database and Diff Assertions)
# -----------------------------------------------------------------------------
def test_assertion_adapter_program_html_mock_db():
    """Verify program_html evaluates database queries and table diff mutations."""
    env = WebArenaEnv(mode="mock")
    adapter = WebArenaAssertionAdapter(env=env)

    # Query initial seeded record
    a_seeded = build_program_html_assertion({
        "point": "db",
        "locator": "SELECT count(*) as count FROM shopping_products WHERE sku = 'SKU-LAPTOP-01'",
        "expected": 1,
    })
    r1 = adapter.evaluate(a_seeded)
    assert r1.passed is True

    # Execute mutation and check updated count
    env.execute_mock_mutation(
        "INSERT INTO reddit_comments (post_id, author, content) VALUES (?, ?, ?)",
        (1, "tester", "Excellent benchmark suite"),
    )
    a_comment = build_program_html_assertion({
        "point": "db",
        "locator": "SELECT count(*) as count FROM reddit_comments WHERE post_id = 1 AND content LIKE '%Excellent%'",
        "expected": 1,
    })
    r2 = adapter.evaluate(a_comment)
    assert r2.passed is True

    # Count mismatch fails
    a_fail = build_program_html_assertion({
        "point": "db",
        "locator": "SELECT count(*) as count FROM reddit_comments WHERE post_id = 99",
        "expected": 1,
    })
    r3 = adapter.evaluate(a_fail)
    assert r3.passed is False
    assert "Expected count 1, but DB returned 0" in (r3.error_message or "")


# -----------------------------------------------------------------------------
# 5. Runner Executes Mock Subset Task Successfully
# -----------------------------------------------------------------------------
def test_webarena_runner_executes_mock_task():
    """Verify WebArenaRunner executes task, interacts with mock environment, and returns EvalResult."""
    runner = WebArenaRunner(mode="hybrid")
    task = get_webarena_task_by_id("102")
    assert task is not None

    res = runner.run_task(task)
    assert isinstance(res, EvalResult)
    assert res.success is True
    assert res.task_id == "webarena_102"
    assert res.total_steps >= 2
    assert all(a.passed for a in res.assertion_results)


# -----------------------------------------------------------------------------
# 6. Handling Unsupported Assertion Types
# -----------------------------------------------------------------------------
def test_webarena_runner_handles_unsupported_assertions():
    """Verify unsupported evaluation types (e.g. image_match) are marked and skipped gracefully."""
    raw_task = {
        "task_id": 999,
        "intent": "Visual layout verification task",
        "start_url": "http://127.0.0.1:7770/products",
        "sites": ["shopping"],
        "eval": {
            "eval_types": ["image_match", "manual"],
        },
    }

    env = WebArenaEnv(mode="mock")
    task = map_webarena_task(raw_task, env=env)

    assert task.metadata["supported"] is False
    assert len(task.expected_assertions) == 2
    assert all(a.type == "unsupported" for a in task.expected_assertions)

    runner = WebArenaRunner(mode="hybrid", env=env, skip_unsupported_assertions=True)
    res = runner.run_task(task)

    assert res.success is True
    assert all(a.actual == "SKIPPED" for a in res.assertion_results)

    # When skip_unsupported_assertions=False, unsupported assertions fail
    strict_runner = WebArenaRunner(mode="hybrid", env=env, skip_unsupported_assertions=False)
    strict_res = strict_runner.run_task(task)
    assert strict_res.success is False


# -----------------------------------------------------------------------------
# 7. No External Network Calls Occur in Mock Mode
# -----------------------------------------------------------------------------
def test_no_external_network_calls_in_mock_mode(monkeypatch: pytest.MonkeyPatch):
    """Verify WebArena evaluation in mock mode makes zero external network socket connections."""
    real_connect = socket.socket.connect

    def guarded_connect(self, address):
        host = address[0]
        # Allow local loopback addresses if any local socket is used
        if host in ("127.0.0.1", "localhost", "::1"):
            return real_connect(self, address)
        raise RuntimeError(f"Prohibited external network call detected to {address}")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)

    runner = WebArenaRunner(mode="hybrid")
    task = get_webarena_task_by_id("101")
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
            "task_id": 1,
            "intent": "Line 1 intent",
            "start_url": "__REDDIT__/1",
            "sites": ["reddit"],
            "eval": {"eval_types": ["url_match"], "reference_url": "__REDDIT__/1"},
        }),
        json.dumps({
            "task_id": 2,
            "intent": "Line 2 intent",
            "start_url": "__SHOPPING__/2",
            "sites": ["shopping"],
            "eval": {"eval_types": ["url_match"], "reference_url": "__SHOPPING__/2"},
        }),
    ]
    jsonl_str = "\n".join(lines)
    tasks = parse_webarena_jsonl(jsonl_str)
    assert len(tasks) == 2
    assert tasks[0].task_id == "webarena_1"
    assert tasks[1].task_id == "webarena_2"


# -----------------------------------------------------------------------------
# 9. Subset Selection Domain Coverage
# -----------------------------------------------------------------------------
def test_subset_selection_domain_coverage():
    """Verify subset suite contains >= 10 tasks across Shopping, Reddit, and GitLab."""
    tasks = create_webarena_subset()
    assert len(tasks) >= 10, f"Expected >= 10 tasks, found {len(tasks)}"

    reddit_tasks = get_webarena_tasks_by_domain("reddit")
    shopping_tasks = get_webarena_tasks_by_domain("shopping")
    gitlab_tasks = get_webarena_tasks_by_domain("gitlab")

    assert len(reddit_tasks) >= 3, "Reddit domain must have at least 3 tasks"
    assert len(shopping_tasks) >= 3, "Shopping domain must have at least 3 tasks"
    assert len(gitlab_tasks) >= 3, "GitLab domain must have at least 3 tasks"

    # Verify diverse evaluation types
    all_eval_types = set()
    for t in tasks:
        for a in t.expected_assertions:
            all_eval_types.add(a.type if isinstance(a.type, str) else a.type.value)

    assert "url_match" in all_eval_types
    assert "string_match" in all_eval_types
    assert "program_html" in all_eval_types


# -----------------------------------------------------------------------------
# 10. WebArena Environment Reset
# -----------------------------------------------------------------------------
def test_webarena_env_reset():
    """Verify environment reset restores mock tables and wipes mutations."""
    env = WebArenaEnv(mode="mock")

    # Add a mutation
    env.execute_mock_mutation(
        "INSERT INTO reddit_posts (subforum, title, author) VALUES (?, ?, ?)",
        ("temp", "Temporary Post", "tester"),
    )
    posts = env.query_db("SELECT count(*) as cnt FROM reddit_posts WHERE subforum = 'temp'")
    assert posts[0]["cnt"] == 1

    # Reset
    env.reset()
    posts_after = env.query_db("SELECT count(*) as cnt FROM reddit_posts WHERE subforum = 'temp'")
    assert posts_after[0]["cnt"] == 0

    # Baseline seed persists
    base_post = env.query_db("SELECT count(*) as cnt FROM reddit_posts WHERE subforum = 'technology'")
    assert base_post[0]["cnt"] == 1


# -----------------------------------------------------------------------------
# 11. DatabaseDiffEngine Mutation Detection
# -----------------------------------------------------------------------------
def test_database_diff_engine():
    """Verify DatabaseDiffEngine detects inserts, updates, deletes and enforces assertions."""
    env = WebArenaEnv(mode="mock")
    diff_engine = env.diff_engine

    snap_before = diff_engine.snapshot(["reddit_posts", "shopping_products"])

    # Insert a post
    env.execute_mock_mutation(
        "INSERT INTO reddit_posts (subforum, title, author) VALUES (?, ?, ?)",
        ("ai", "New AI Benchmark", "researcher"),
    )
    # Update product price
    env.execute_mock_mutation(
        "UPDATE shopping_products SET price = 899.99 WHERE sku = 'SKU-LAPTOP-01'"
    )

    diff_report = diff_engine.diff(snap_before)

    assert diff_report.has_mutations is True
    assert diff_report.total_inserted == 1
    assert diff_report.total_updated == 1
    assert diff_report.total_deleted == 0

    # Check table assertions
    inserted_rows = diff_engine.assert_inserted(diff_report, "reddit_posts", expected_count=1)
    assert inserted_rows[0]["title"] == "New AI Benchmark"


# -----------------------------------------------------------------------------
# 12. Public Playwright API Compliance
# -----------------------------------------------------------------------------
def test_public_playwright_api_compliance_phase4b():
    """Verify no forbidden private Playwright internals are used in Phase 4B eval modules."""
    eval_dir = REPO_ROOT / "src" / "arc_cua" / "eval"
    phase4b_files = [
        "webarena_env.py",
        "webarena_mapper.py",
        "webarena_assertions.py",
        "tasks_webarena.py",
        "webarena_runner.py",
    ]

    for filename in phase4b_files:
        py_file = eval_dir / filename
        assert py_file.exists(), f"Phase 4B module {filename} does not exist"
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
        used_attributes: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                used_attributes.add(node.attr)

        violations = used_attributes.intersection(FORBIDDEN_PRIVATE_INTERNALS)
        assert not violations, (
            f"Public API Violation in {filename}: referenced private internals {violations}"
        )
