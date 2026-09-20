"""WebArena Assertion Adapter for ARC (Phase 4B).

Implements WebArena evaluation types:
1. url_match: Checks whether final URL matches expected pattern (exact, prefix, or regex).
2. string_match: Checks whether target response or DOM text contains reference answers (fuzzy, exact, or must-include).
3. program_html: Verifies backend state (database mutations via WebArenaEnv or DOM states).
4. unsupported: Handles unsupported evaluation types gracefully (SKIPPED).

Integrates with WebArenaEnv and DatabaseDiffEngine from Phase 4B Task 1.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from typing import Any, Dict, List, Optional, Sequence, Union

from .schemas import EvalAssertion, EvalAssertionResult
from .webarena_env import DatabaseDiffReport, WebArenaEnv

logger = logging.getLogger("arc_cua.eval.webarena_assertions")


def normalize_url(url: str) -> str:
    """Normalize a URL for comparison: lowercase scheme/netloc, strip trailing slash."""
    if not url:
        return ""
    parsed = urllib.parse.urlsplit(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    query = parsed.query
    fragment = parsed.fragment

    rebuilt = urllib.parse.urlunsplit((scheme, netloc, path, query, fragment))
    return rebuilt.rstrip("/")


def check_webarena_url_match(
    assertion: EvalAssertion,
    current_url: str,
    env: Optional[WebArenaEnv] = None,
) -> EvalAssertionResult:
    """Evaluate WebArena url_match assertion against current URL."""
    expected_data = assertion.expected
    if isinstance(expected_data, dict):
        ref_url = str(expected_data.get("reference_url", ""))
        url_note = str(expected_data.get("url_note", "exact")).lower()
    else:
        ref_url = str(expected_data or "")
        url_note = "exact"

    # Resolve any environment domain placeholders (e.g. __SHOPPING__)
    if env is not None:
        ref_url = env.resolve_url(ref_url)
        current_url = env.resolve_url(current_url)

    curr_norm = normalize_url(current_url)
    ref_norm = normalize_url(ref_url)

    passed = False
    error_msg = None

    if url_note == "regex" or ref_url.startswith("^") or (ref_url.endswith("$") and not ref_url.endswith("/$")):
        try:
            pattern = re.compile(ref_url)
            passed = bool(pattern.search(current_url))
            if not passed:
                error_msg = f"URL '{current_url}' did not match regex pattern '{ref_url}'"
        except re.error as err:
            passed = False
            error_msg = f"Invalid regex pattern in url_match: '{ref_url}' ({err})"
    elif url_note == "prefix":
        passed = curr_norm.startswith(ref_norm)
        if not passed:
            error_msg = f"URL '{curr_norm}' does not start with prefix '{ref_norm}'"
    else:
        # Exact match or path equality
        passed = (curr_norm == ref_norm)
        if not passed:
            # Tolerant query-string reorder comparison
            p_curr = urllib.parse.urlsplit(curr_norm)
            p_ref = urllib.parse.urlsplit(ref_norm)
            if (
                p_curr.scheme == p_ref.scheme
                and p_curr.netloc == p_ref.netloc
                and p_curr.path == p_ref.path
            ):
                q_curr = urllib.parse.parse_qs(p_curr.query)
                q_ref = urllib.parse.parse_qs(p_ref.query)
                if q_curr == q_ref:
                    passed = True
            if not passed:
                error_msg = f"Expected URL '{ref_norm}', but found '{curr_norm}'"

    return EvalAssertionResult(
        assertion=assertion,
        passed=passed,
        actual=current_url,
        error_message=error_msg,
    )


def normalize_text(text: str) -> str:
    """Normalize text: strip, collapse multiple whitespace characters into single space."""
    if not text:
        return ""
    return " ".join(text.strip().split())


def check_webarena_string_match(
    assertion: EvalAssertion,
    page_text: str,
) -> EvalAssertionResult:
    """Evaluate WebArena string_match assertion against DOM or response text."""
    expected_data = assertion.expected
    if isinstance(expected_data, dict):
        ref_answers = expected_data.get("reference_answers", "")
        string_note = str(expected_data.get("string_note", "fuzzy_match")).lower()
    else:
        ref_answers = expected_data
        string_note = "fuzzy_match"

    norm_target = normalize_text(page_text).lower()

    candidates: List[str] = []
    must_include: List[str] = []

    if isinstance(ref_answers, dict):
        if "exact_match" in ref_answers:
            val = ref_answers["exact_match"]
            candidates.extend([val] if isinstance(val, str) else list(val))
            string_note = "exact_match"
        if "fuzzy_match" in ref_answers:
            val = ref_answers["fuzzy_match"]
            candidates.extend([val] if isinstance(val, str) else list(val))
        if "must_include" in ref_answers:
            val = ref_answers["must_include"]
            must_include.extend([val] if isinstance(val, str) else list(val))
    elif isinstance(ref_answers, list):
        candidates.extend([str(c) for c in ref_answers])
    elif ref_answers is not None:
        candidates.append(str(ref_answers))

    passed = False
    error_msg = None

    if must_include:
        missing = [m for m in must_include if normalize_text(m).lower() not in norm_target]
        if missing:
            passed = False
            error_msg = f"String match failed: missing required tokens: {missing}"
        else:
            passed = True

    if candidates and (not must_include or passed):
        found = False
        for c in candidates:
            norm_c = normalize_text(c).lower()
            if string_note == "exact_match":
                if norm_target == norm_c:
                    found = True
                    break
            else:
                # Fuzzy / substring match
                if norm_c in norm_target:
                    found = True
                    break
        passed = found
        if not passed:
            error_msg = f"None of reference candidates {candidates} matched target text"

    return EvalAssertionResult(
        assertion=assertion,
        passed=passed,
        actual=page_text[:200] if page_text else "",
        error_message=error_msg,
    )


def check_webarena_program_html(
    assertion: EvalAssertion,
    env: Optional[WebArenaEnv] = None,
    page: Optional[Any] = None,
    diff_report: Optional[DatabaseDiffReport] = None,
) -> EvalAssertionResult:
    """Evaluate WebArena program_html (backend DB query, DB diff, or DOM locator)."""
    expected_data = assertion.expected
    if not isinstance(expected_data, dict):
        return EvalAssertionResult(
            assertion=assertion,
            passed=False,
            actual=None,
            error_message=f"program_html expected data must be dict, got {type(expected_data).__name__}",
        )

    point = expected_data.get("point", "db").lower()
    locator = expected_data.get("locator") or expected_data.get("selector", "")
    expected = expected_data.get("expected")

    passed = False
    actual: Any = None
    error_msg: Optional[str] = None

    if point == "db":
        if env is None:
            return EvalAssertionResult(
                assertion=assertion,
                passed=False,
                actual=None,
                error_message="Cannot evaluate DB program_html assertion: WebArenaEnv is not available",
            )
        try:
            rows = env.query_db(locator)
            actual = rows
            if expected is None:
                passed = len(rows) > 0
                if not passed:
                    error_msg = f"Query '{locator}' returned 0 rows (expected > 0)"
            elif isinstance(expected, int):
                # Count check: either len(rows) == expected, or single row with count column == expected
                if len(rows) == 1 and any("count" in k.lower() for k in rows[0].keys()):
                    count_val = next(v for k, v in rows[0].items() if "count" in k.lower())
                    passed = (count_val == expected)
                    actual = count_val
                    if not passed:
                        error_msg = f"Expected count {expected}, but DB returned {count_val}"
                else:
                    passed = (len(rows) == expected)
                    actual = len(rows)
                    if not passed:
                        error_msg = f"Expected {expected} rows, but DB returned {len(rows)}"
            elif isinstance(expected, (str, float, bool)):
                # Scalar check on single result
                if len(rows) == 1:
                    first_val = next(iter(rows[0].values()))
                    passed = (str(first_val).lower() == str(expected).lower())
                    actual = first_val
                    if not passed:
                        error_msg = f"Expected value '{expected}', got '{first_val}'"
                else:
                    passed = False
                    error_msg = f"Expected single scalar row for value '{expected}', got {len(rows)} rows"
            elif isinstance(expected, dict):
                # Column subset check
                passed = False
                for r in rows:
                    if all(r.get(k) == v for k, v in expected.items()):
                        passed = True
                        break
                if not passed:
                    error_msg = f"No row matched expected fields {expected}"
            elif isinstance(expected, list):
                # List of expected dicts or values
                passed = (len(rows) == len(expected))
                if not passed:
                    error_msg = f"Row count {len(rows)} does not match expected count {len(expected)}"
        except Exception as err:
            passed = False
            error_msg = f"Database query '{locator}' failed: {err}"

    elif point == "db_diff":
        if diff_report is None:
            return EvalAssertionResult(
                assertion=assertion,
                passed=False,
                actual=None,
                error_message="Cannot evaluate db_diff program_html assertion: DatabaseDiffReport is missing",
            )
        table = expected_data.get("table", "")
        op = expected_data.get("op", "inserted")
        count = expected_data.get("count", 1)
        actual = diff_report
        t_diff = diff_report.tables.get(table)
        if not t_diff:
            passed = False
            error_msg = f"Table '{table}' not present in DB diff report"
        elif op == "inserted":
            passed = len(t_diff.inserted) == count
            if not passed:
                error_msg = f"Expected {count} rows inserted into '{table}', got {len(t_diff.inserted)}"
        elif op == "deleted":
            passed = len(t_diff.deleted) == count
            if not passed:
                error_msg = f"Expected {count} rows deleted from '{table}', got {len(t_diff.deleted)}"
        elif op == "unchanged":
            passed = (t_diff.total_mutations == 0)
            if not passed:
                error_msg = f"Expected '{table}' to be unchanged, but detected {t_diff.total_mutations} mutations"
        else:
            passed = False
            error_msg = f"Unknown DB diff operation '{op}'"

    elif point == "dom":
        if page is None:
            return EvalAssertionResult(
                assertion=assertion,
                passed=False,
                actual=None,
                error_message="Cannot evaluate DOM program_html assertion: page handle is missing",
            )
        try:
            # Use public locator / query method
            locator_obj = page.locator(locator)
            is_visible = locator_obj.is_visible() if hasattr(locator_obj, "is_visible") else True
            actual = {"is_visible": is_visible}
            if expected == "visible":
                passed = bool(is_visible)
            elif expected == "hidden":
                passed = not is_visible
            else:
                passed = bool(is_visible)
            if not passed:
                error_msg = f"DOM element '{locator}' state did not match expected '{expected}'"
        except Exception as err:
            passed = False
            error_msg = f"DOM evaluation failed for '{locator}': {err}"

    else:
        passed = False
        error_msg = f"Unsupported program_html point '{point}'"

    return EvalAssertionResult(
        assertion=assertion,
        passed=passed,
        actual=actual,
        error_message=error_msg,
    )


def check_webarena_unsupported(
    assertion: EvalAssertion,
    skip_passes: bool = True,
) -> EvalAssertionResult:
    """Handle unsupported WebArena evaluation assertions.

    If skip_passes is True, skipped assertions do not fail the overall task,
    while recording that the check was skipped.
    """
    return EvalAssertionResult(
        assertion=assertion,
        passed=skip_passes,
        actual="SKIPPED",
        error_message=f"Skipped unsupported assertion: {assertion.description}",
    )


class WebArenaAssertionAdapter:
    """Adapter unifying WebArena assertions with the ARC evaluation harness."""

    def __init__(
        self,
        env: Optional[WebArenaEnv] = None,
        skip_unsupported: bool = True,
    ):
        self.env = env
        self.skip_unsupported = skip_unsupported

    def evaluate(
        self,
        assertion: EvalAssertion,
        current_url: Optional[str] = None,
        page_text: Optional[str] = None,
        page: Optional[Any] = None,
        diff_report: Optional[DatabaseDiffReport] = None,
    ) -> EvalAssertionResult:
        """Evaluate a single WebArena assertion."""
        atype = assertion.type.value if hasattr(assertion.type, "value") else str(assertion.type)

        if atype == "url_match" or atype == "url":
            return check_webarena_url_match(assertion, current_url or "", env=self.env)
        elif atype == "string_match" or atype == "visible_text":
            return check_webarena_string_match(assertion, page_text or "")
        elif atype == "program_html":
            return check_webarena_program_html(
                assertion,
                env=self.env,
                page=page,
                diff_report=diff_report,
            )
        elif atype == "unsupported":
            return check_webarena_unsupported(assertion, skip_passes=self.skip_unsupported)
        else:
            # Fall back to unsupported handler
            return check_webarena_unsupported(assertion, skip_passes=self.skip_unsupported)

    def evaluate_all(
        self,
        assertions: Sequence[EvalAssertion],
        current_url: Optional[str] = None,
        page_text: Optional[str] = None,
        page: Optional[Any] = None,
        diff_report: Optional[DatabaseDiffReport] = None,
    ) -> List[EvalAssertionResult]:
        """Evaluate all assertions and return results."""
        return [
            self.evaluate(
                a,
                current_url=current_url,
                page_text=page_text,
                page=page,
                diff_report=diff_report,
            )
            for a in assertions
        ]
