"""Success Assertion Engine for ARC (Phase 4A).

Implements Task 4A.4:
- Deterministic assertion checks:
  * check_url
  * check_visible_text
  * check_element_state
  * check_input_value
  * check_page_title
  * check_state_hash_changed
- Strictly public Playwright APIs (zero private internals referenced).
- Zero-Pixel Trap & visibility validation adapted from ColdStart qa-framework/assertions.ts.
- Structured EvalAssertionResult output with detailed latency and error tracking.
- Exception-safe execution (no unhandled crashes on failed checks).
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Optional, Pattern, Union

from ..state_verifier import compute_hamming_distance
from .schemas import (
    AssertionType,
    ElementState,
    EvalAssertion,
    EvalAssertionResult,
)

logger = logging.getLogger("arc_cua.eval.assertions")


def check_url(
    page: Any,
    expected: Union[str, Pattern],
    timeout_ms: float = 2000.0,
    assertion: Optional[EvalAssertion] = None,
) -> EvalAssertionResult:
    """Verify current page URL matches expected string or regex pattern."""
    t0 = time.perf_counter()
    if assertion is None:
        assertion = EvalAssertion(type=AssertionType.URL, expected=str(expected), timeout_ms=timeout_ms)

    actual_url = ""
    try:
        if hasattr(page, "url"):
            actual_url = page.url or ""
        elif callable(getattr(page, "get_url", None)):
            actual_url = page.get_url() or ""

        # Quick match check
        if isinstance(expected, str):
            passed = expected in actual_url
        elif hasattr(expected, "search"):
            passed = bool(expected.search(actual_url))
        else:
            passed = str(expected) in actual_url

        # Brief wait / polling if not immediately matched and page supports wait
        if not passed and timeout_ms > 0 and hasattr(page, "wait_for_url") and isinstance(expected, str):
            try:
                page.wait_for_url(f"**/*{expected}*", timeout=timeout_ms)
                actual_url = page.url or ""
                passed = expected in actual_url
            except Exception:
                passed = False

        latency_ms = (time.perf_counter() - t0) * 1000.0
        error_msg = None if passed else f"URL mismatch: expected '{expected}', found '{actual_url}'"
        return EvalAssertionResult(
            assertion=assertion,
            passed=passed,
            actual=actual_url,
            error_message=error_msg,
            latency_ms=latency_ms,
        )
    except Exception as e:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return EvalAssertionResult(
            assertion=assertion,
            passed=False,
            actual=actual_url,
            error_message=f"check_url exception: {e}",
            latency_ms=latency_ms,
        )


def check_visible_text(
    page: Any,
    expected: Union[str, Pattern],
    selector: Optional[str] = None,
    timeout_ms: float = 2000.0,
    min_width: float = 1.0,
    min_height: float = 1.0,
    assertion: Optional[EvalAssertion] = None,
) -> EvalAssertionResult:
    """Verify text is visible on the page, with zero-pixel trap validation."""
    t0 = time.perf_counter()
    if assertion is None:
        assertion = EvalAssertion(
            type=AssertionType.VISIBLE_TEXT,
            selector=selector,
            expected=str(expected),
            timeout_ms=timeout_ms,
            min_width=min_width,
            min_height=min_height,
        )

    actual_text = ""
    try:
        if selector:
            loc = page.locator(selector)
            # Try waiting for visibility if page supports wait_for
            if hasattr(loc, "wait_for"):
                try:
                    loc.wait_for(state="visible", timeout=timeout_ms)
                except Exception:
                    pass

            # 1. Check basic visibility
            is_visible = False
            if hasattr(loc, "is_visible"):
                is_visible = loc.is_visible()
            elif hasattr(loc, "visible"):
                is_visible = bool(loc.visible)
            else:
                is_visible = True

            if not is_visible:
                latency_ms = (time.perf_counter() - t0) * 1000.0
                return EvalAssertionResult(
                    assertion=assertion,
                    passed=False,
                    actual="Element not visible",
                    error_message=f"Element '{selector}' is not visible in DOM",
                    latency_ms=latency_ms,
                )

            # 2. Check Zero-Pixel Trap / Bounding box (adapted from ColdStart F-039)
            if hasattr(loc, "bounding_box"):
                box = loc.bounding_box()
                if box:
                    w = box.get("width", 0)
                    h = box.get("height", 0)
                    if w < min_width or h < min_height:
                        latency_ms = (time.perf_counter() - t0) * 1000.0
                        return EvalAssertionResult(
                            assertion=assertion,
                            passed=False,
                            actual=f"Zero-pixel trap (w={w}px, h={h}px)",
                            error_message=f"Element '{selector}' collapsed to zero pixels: width={w}, height={h}",
                            latency_ms=latency_ms,
                        )

            # 3. Retrieve inner text
            if hasattr(loc, "inner_text"):
                actual_text = loc.inner_text()
            elif hasattr(loc, "text_content"):
                actual_text = loc.text_content() or ""
            elif hasattr(loc, "value"):
                actual_text = str(loc.value or "")
        else:
            # Full page search
            if hasattr(page, "inner_text"):
                actual_text = page.inner_text("body")
            else:
                actual_text = ""

        # Validate text pattern
        expected_str = str(expected)
        if isinstance(expected, str):
            passed = expected_str in actual_text
        elif hasattr(expected, "search"):
            passed = bool(expected.search(actual_text))
        else:
            passed = expected_str in actual_text

        latency_ms = (time.perf_counter() - t0) * 1000.0
        error_msg = None if passed else f"Text mismatch: expected '{expected_str}' in '{actual_text[:120]}'"
        return EvalAssertionResult(
            assertion=assertion,
            passed=passed,
            actual=actual_text,
            error_message=error_msg,
            latency_ms=latency_ms,
        )
    except Exception as e:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return EvalAssertionResult(
            assertion=assertion,
            passed=False,
            actual=actual_text,
            error_message=f"check_visible_text exception: {e}",
            latency_ms=latency_ms,
        )


def check_element_state(
    page: Any,
    selector: str,
    expected_state: Union[ElementState, str],
    timeout_ms: float = 2000.0,
    assertion: Optional[EvalAssertion] = None,
) -> EvalAssertionResult:
    """Verify an element adheres to an interactive or DOM state."""
    t0 = time.perf_counter()
    if assertion is None:
        assertion = EvalAssertion(
            type=AssertionType.ELEMENT_STATE,
            selector=selector,
            expected=expected_state,
            timeout_ms=timeout_ms,
        )

    state_val = expected_state.value if isinstance(expected_state, ElementState) else str(expected_state).lower()
    actual_state = "unknown"

    try:
        loc = page.locator(selector)
        count = 0
        if hasattr(loc, "count"):
            count = loc.count()

        if state_val == "attached":
            passed = (count > 0)
            actual_state = "attached" if passed else "detached"
        elif state_val == "detached":
            passed = (count == 0)
            actual_state = "detached" if passed else "attached"
        elif state_val == "visible":
            is_vis = False
            if hasattr(loc, "is_visible"):
                is_vis = loc.is_visible()
            elif hasattr(loc, "visible"):
                is_vis = bool(loc.visible)
            passed = is_vis and (count > 0)
            actual_state = "visible" if passed else "hidden"
        elif state_val == "hidden":
            is_vis = True
            if count == 0:
                is_vis = False
            elif hasattr(loc, "is_visible"):
                is_vis = loc.is_visible()
            elif hasattr(loc, "visible"):
                is_vis = bool(loc.visible)
            passed = not is_vis
            actual_state = "hidden" if passed else "visible"
        elif state_val == "enabled":
            passed = False
            if hasattr(loc, "is_enabled"):
                passed = loc.is_enabled()
            elif hasattr(loc, "enabled"):
                passed = bool(loc.enabled)
            actual_state = "enabled" if passed else "disabled"
        elif state_val == "disabled":
            passed = False
            if hasattr(loc, "is_disabled"):
                passed = loc.is_disabled()
            elif hasattr(loc, "enabled"):
                passed = not bool(loc.enabled)
            actual_state = "disabled" if passed else "enabled"
        elif state_val == "checked":
            passed = False
            if hasattr(loc, "is_checked"):
                passed = loc.is_checked()
            actual_state = "checked" if passed else "unchecked"
        else:
            passed = False
            actual_state = f"unsupported_state:{state_val}"

        latency_ms = (time.perf_counter() - t0) * 1000.0
        error_msg = None if passed else f"Element '{selector}' state mismatch: expected '{state_val}', got '{actual_state}'"
        return EvalAssertionResult(
            assertion=assertion,
            passed=passed,
            actual=actual_state,
            error_message=error_msg,
            latency_ms=latency_ms,
        )
    except Exception as e:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return EvalAssertionResult(
            assertion=assertion,
            passed=False,
            actual=actual_state,
            error_message=f"check_element_state exception: {e}",
            latency_ms=latency_ms,
        )


def check_input_value(
    page: Any,
    selector: str,
    expected_value: str,
    timeout_ms: float = 2000.0,
    assertion: Optional[EvalAssertion] = None,
) -> EvalAssertionResult:
    """Verify input/textarea value matches expected string."""
    t0 = time.perf_counter()
    if assertion is None:
        assertion = EvalAssertion(
            type=AssertionType.INPUT_VALUE,
            selector=selector,
            expected=expected_value,
            timeout_ms=timeout_ms,
        )

    actual_value = ""
    try:
        loc = page.locator(selector)
        if hasattr(loc, "input_value"):
            try:
                actual_value = loc.input_value(timeout=timeout_ms)
            except TypeError:
                actual_value = loc.input_value()
        elif hasattr(loc, "value"):
            actual_value = str(loc.value or "")
        elif hasattr(loc, "evaluate"):
            actual_value = str(loc.evaluate("(el) => el.value") or "")

        passed = (actual_value == str(expected_value))
        latency_ms = (time.perf_counter() - t0) * 1000.0
        error_msg = None if passed else f"Input value mismatch: expected '{expected_value}', got '{actual_value}'"
        return EvalAssertionResult(
            assertion=assertion,
            passed=passed,
            actual=actual_value,
            error_message=error_msg,
            latency_ms=latency_ms,
        )
    except Exception as e:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return EvalAssertionResult(
            assertion=assertion,
            passed=False,
            actual=actual_value,
            error_message=f"check_input_value exception: {e}",
            latency_ms=latency_ms,
        )


def check_page_title(
    page: Any,
    expected_title: str,
    timeout_ms: float = 2000.0,
    assertion: Optional[EvalAssertion] = None,
) -> EvalAssertionResult:
    """Verify page title matches or contains expected title."""
    t0 = time.perf_counter()
    if assertion is None:
        assertion = EvalAssertion(
            type=AssertionType.PAGE_TITLE,
            expected=expected_title,
            timeout_ms=timeout_ms,
        )

    actual_title = ""
    try:
        if hasattr(page, "title"):
            actual_title = page.title() or ""
        elif callable(getattr(page, "get_title", None)):
            actual_title = page.get_title() or ""

        passed = (expected_title in actual_title) or (actual_title == expected_title)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        error_msg = None if passed else f"Page title mismatch: expected '{expected_title}', got '{actual_title}'"
        return EvalAssertionResult(
            assertion=assertion,
            passed=passed,
            actual=actual_title,
            error_message=error_msg,
            latency_ms=latency_ms,
        )
    except Exception as e:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return EvalAssertionResult(
            assertion=assertion,
            passed=False,
            actual=actual_title,
            error_message=f"check_page_title exception: {e}",
            latency_ms=latency_ms,
        )


def check_state_hash_changed(
    initial_hash: int,
    current_hash: int,
    expected_changed: bool = True,
    min_hamming_distance: int = 1,
    assertion: Optional[EvalAssertion] = None,
) -> EvalAssertionResult:
    """Verify whether state hash changed via bitwise Hamming distance (StateVerifier integration)."""
    t0 = time.perf_counter()
    if assertion is None:
        assertion = EvalAssertion(
            type=AssertionType.STATE_HASH_CHANGED,
            expected=expected_changed,
        )

    try:
        distance = compute_hamming_distance(initial_hash, current_hash)
        actual_changed = (distance >= min_hamming_distance)
        passed = (actual_changed == bool(expected_changed))

        latency_ms = (time.perf_counter() - t0) * 1000.0
        details = {
            "initial_hash": hex(initial_hash),
            "current_hash": hex(current_hash),
            "hamming_distance": distance,
            "actual_changed": actual_changed,
        }
        error_msg = None if passed else (
            f"State hash change mismatch: expected_changed={expected_changed}, "
            f"actual_changed={actual_changed} (Hamming dist={distance})"
        )
        return EvalAssertionResult(
            assertion=assertion,
            passed=passed,
            actual=details,
            error_message=error_msg,
            latency_ms=latency_ms,
        )
    except Exception as e:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return EvalAssertionResult(
            assertion=assertion,
            passed=False,
            actual={"initial_hash": initial_hash, "current_hash": current_hash},
            error_message=f"check_state_hash_changed exception: {e}",
            latency_ms=latency_ms,
        )


def evaluate_assertion(
    page: Any,
    assertion: EvalAssertion,
    initial_state_hash: Optional[int] = None,
    current_state_hash: Optional[int] = None,
) -> EvalAssertionResult:
    """Evaluate an arbitrary EvalAssertion against a page or state snapshot."""
    atype = assertion.type.value if isinstance(assertion.type, AssertionType) else str(assertion.type)

    if atype == AssertionType.URL.value:
        return check_url(page, assertion.expected, timeout_ms=assertion.timeout_ms, assertion=assertion)

    elif atype == AssertionType.VISIBLE_TEXT.value:
        return check_visible_text(
            page,
            assertion.expected,
            selector=assertion.selector,
            timeout_ms=assertion.timeout_ms,
            min_width=assertion.min_width,
            min_height=assertion.min_height,
            assertion=assertion,
        )

    elif atype == AssertionType.ELEMENT_STATE.value:
        return check_element_state(
            page,
            selector=assertion.selector or "body",
            expected_state=assertion.expected,
            timeout_ms=assertion.timeout_ms,
            assertion=assertion,
        )

    elif atype == AssertionType.INPUT_VALUE.value:
        return check_input_value(
            page,
            selector=assertion.selector or "input",
            expected_value=str(assertion.expected),
            timeout_ms=assertion.timeout_ms,
            assertion=assertion,
        )

    elif atype == AssertionType.PAGE_TITLE.value:
        return check_page_title(
            page,
            expected_title=str(assertion.expected),
            timeout_ms=assertion.timeout_ms,
            assertion=assertion,
        )

    elif atype == AssertionType.STATE_HASH_CHANGED.value:
        init_h = initial_state_hash if initial_state_hash is not None else 0
        curr_h = current_state_hash if current_state_hash is not None else 0
        return check_state_hash_changed(
            initial_hash=init_h,
            current_hash=curr_h,
            expected_changed=bool(assertion.expected),
            assertion=assertion,
        )

    else:
        return EvalAssertionResult(
            assertion=assertion,
            passed=False,
            actual=f"Unsupported assertion type: {atype}",
            error_message=f"Unsupported assertion type '{atype}'",
            latency_ms=0.0,
        )
