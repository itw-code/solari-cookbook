"""Comprehensive Test & Benchmark Suite for Phase 2 Reflex Automation.

Verifies:
1. Static analysis compliance: strictly public Playwright APIs, zero forbidden private internals.
2. Deterministic Playwright Executor actions, auto-waiting, and error recovery.
3. Invariant selector cache and 6-tier self-healing fallback resolution chain.
4. Session readiness guard (stability, visibility, Zero-Pixel Trap, disabled, occluding modals).
5. State verification engine (SimHash diffing, Hamming distance, URL changes, stuck detection).
6. Reflex runner execution loop, ESCALATE signals, and telemetry latency breakdowns.
7. Empirical N=100 latency benchmarks (Locator Resolution, Action Execution, SimHash Verification).
"""

from __future__ import annotations

import ast
import inspect
import os
import pathlib
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import pytest

# Ensure src is in python path
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

from arc_cua.cdp_extractor import AXNode, CDP_AXTree_Extractor, SanitizedAXTree
from arc_cua.executor_interface import (
    ActionPayload,
    ActionVerb,
    FORBIDDEN_PRIVATE_INTERNALS,
    audit_public_api_compliance,
)
from arc_cua.locator_resolver import (
    LocatorResolutionError,
    LocatorResolver,
    ResolvedLocator,
    SelectorLRUCache,
)
from arc_cua.playwright_executor import PlaywrightExecutor
from arc_cua.reflex_runner import ReflexExecutionResult, ReflexRunner, ReflexStatus
from arc_cua.schemas import (
    ActionResult,
    ActionStep,
    EscalationPayload,
    EscalationReason,
    PerceptionSource,
    TelemetryRecord,
    UIState,
)
from arc_cua.session_guard import ReadinessResult, SessionGuard
from arc_cua.state_verifier import (
    StateVerificationResult,
    StateVerifier,
    compute_hamming_distance,
)
from arc_cua.telemetry import (
    MetricDistribution,
    TelemetryCollector,
    compute_percentiles,
    compute_simhash64,
)


# ============================================================================
# Mock Playwright Fixtures
# ============================================================================

class MockElementLocator:
    """Public Playwright Locator mock."""

    def __init__(
        self,
        selector: str,
        visible: bool = True,
        enabled: bool = True,
        count: int = 1,
        bbox: Optional[Dict[str, float]] = None,
        should_fail_click: bool = False,
        should_fail_fill: bool = False,
    ):
        self.selector = selector
        self._is_visible = visible
        self._is_enabled = enabled
        self._count = count
        self._bbox = bbox or {"x": 100.0, "y": 200.0, "width": 80.0, "height": 30.0}
        self.should_fail_click = should_fail_click
        self.should_fail_fill = should_fail_fill
        self.actions_log: List[str] = []

    @property
    def first(self) -> MockElementLocator:
        return self

    def count(self) -> int:
        return self._count
    def is_visible(self) -> bool:
        return self._is_visible and self._count > 0

    def is_enabled(self) -> bool:
        return self._is_enabled

    def is_disabled(self) -> bool:
        return not self._is_enabled

    def bounding_box(self) -> Optional[Dict[str, float]]:
        if not self._is_visible or self._count == 0:
            return None
        return self._bbox

    def click(self, timeout: Optional[float] = None) -> None:
        if self.should_fail_click:
            raise RuntimeError(f"Playwright TimeoutError: Element '{self.selector}' not clickable")
        self.actions_log.append(f"click:{self.selector}")

    def fill(self, text: str, timeout: Optional[float] = None) -> None:
        if self.should_fail_fill:
            raise RuntimeError(f"Playwright TimeoutError: Element '{self.selector}' cannot be filled")
        self.actions_log.append(f"fill:{self.selector}={text}")

    def select_option(self, value: str, timeout: Optional[float] = None) -> None:
        self.actions_log.append(f"select:{self.selector}={value}")

    def wait_for(self, state: str = "visible", timeout: Optional[float] = None) -> None:
        if not self._is_visible and state == "visible":
            raise TimeoutError(f"Timeout waiting for locator('{self.selector}') state='{state}'")


class MockKeyboard:
    def __init__(self):
        self.pressed_keys: List[str] = []

    def press(self, key: str) -> None:
        self.pressed_keys.append(key)


class MockMouse:
    def __init__(self):
        self.clicks: List[Tuple[float, float]] = []
        self.wheels: List[Tuple[int, int]] = []

    def click(self, x: float, y: float) -> None:
        self.clicks.append((x, y))

    def wheel(self, delta_x: int, delta_y: int) -> None:
        self.wheels.append((delta_x, delta_y))


class MockPlaywrightPage:
    """Mock of Playwright Page exposing only public methods."""

    def __init__(self, url: str = "https://app.arc.local/dashboard", default_present: bool = True):
        self.url = url
        self.keyboard = MockKeyboard()
        self.mouse = MockMouse()
        self.locators: Dict[str, MockElementLocator] = {}
        self.history: List[str] = []
        self.default_present = default_present
        self.eval_values: Dict[str, Any] = {
            "() => document.readyState": "complete",
        }

    def locator(self, selector: str) -> MockElementLocator:
        if selector in self.locators:
            return self.locators[selector]
        # Overlays and modals are absent by default unless explicitly added
        if any(term in selector for term in (".modal", "backdrop", "overlay", "dialog")):
            loc = MockElementLocator(selector=selector, count=0, visible=False)
            self.locators[selector] = loc
            return loc
        count = 1 if self.default_present else 0
        loc = MockElementLocator(selector=selector, count=count, visible=(count > 0))
        self.locators[selector] = loc
        return loc

    def goto(self, url: str, timeout: Optional[float] = None) -> None:
        self.url = url
        self.history.append(f"goto:{url}")

    def wait_for_timeout(self, timeout_ms: float) -> None:
        self.history.append(f"wait:{timeout_ms}")

    def evaluate(self, script: str, arg: Any = None) -> Any:
        if script in self.eval_values:
            val = self.eval_values[script]
            if callable(val):
                return val(arg)
            return val
        return None


# ============================================================================
# Test Suite 1: Static Analysis & Public API Compliance
# ============================================================================

class TestPublicAPICompliance:
    """Verifies strict ban on private Playwright internals in source and runtime."""

    def test_static_source_code_scan_playwright_executor(self):
        """Parse playwright_executor.py AST to guarantee no forbidden private attributes are used."""
        executor_path = pathlib.Path("src/arc_cua/playwright_executor.py")
        assert executor_path.exists(), "playwright_executor.py must exist"

        source = executor_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(executor_path))

        used_attributes: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                used_attributes.add(node.attr)

        forbidden_found = used_attributes.intersection(FORBIDDEN_PRIVATE_INTERNALS)
        assert len(forbidden_found) == 0, (
            f"Compliance Violation: Private Playwright internals referenced in AST: {forbidden_found}"
        )

    def test_static_string_ban_in_source(self):
        """Direct string check for forbidden words."""
        source = pathlib.Path("src/arc_cua/playwright_executor.py").read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_PRIVATE_INTERNALS:
            assert forbidden not in source, f"Forbidden attribute string '{forbidden}' found in source"

    def test_runtime_audit_clean_page(self):
        """Audit clean mock page."""
        page = MockPlaywrightPage()
        is_clean, violations = audit_public_api_compliance(page)
        assert is_clean is True
        assert len(violations) == 0

    def test_runtime_audit_detects_violation(self):
        """Audit detects simulated leak."""
        class LeakyPage(MockPlaywrightPage):
            def __init__(self):
                super().__init__()
                self._impl_obj = "forbidden_playwright_impl"

        is_clean, violations = audit_public_api_compliance(LeakyPage())
        assert is_clean is False
        assert "_impl_obj" in violations


# ============================================================================
# Test Suite 2: Deterministic Playwright Executor
# ============================================================================

class TestPlaywrightExecutor:
    """Tests ActionExecutor methods, auto-waiting, and error handling."""

    def test_executor_click_and_fill(self):
        page = MockPlaywrightPage()
        executor = PlaywrightExecutor()

        # Click
        res_click = executor.click(page, "#submit-button")
        assert res_click.success is True
        assert res_click.verb == "CLICK"
        assert res_click.target_selector == "#submit-button"
        assert res_click.latency_ms > 0
        assert "click:#submit-button" in page.locators["#submit-button"].actions_log

        # Type text
        res_type = executor.type_text(page, "input#email", "qa-test@arc.local")
        assert res_type.success is True
        assert res_type.verb == "TYPE"
        assert res_type.value == "qa-test@arc.local"
        assert "fill:input#email=qa-test@arc.local" in page.locators["input#email"].actions_log

    def test_executor_coordinate_click(self):
        page = MockPlaywrightPage()
        executor = PlaywrightExecutor()

        res_coords = executor.click(page, "coords:320.5,450.0")
        assert res_coords.success is True
        assert res_coords.metadata["click_type"] == "coordinates"
        assert (320.5, 450.0) in page.mouse.clicks

    def test_executor_select_scroll_press(self):
        page = MockPlaywrightPage()
        executor = PlaywrightExecutor()

        res_select = executor.select(page, "select#currency", "USD")
        assert res_select.success is True
        assert "select:select#currency=USD" in page.locators["select#currency"].actions_log

        res_scroll = executor.scroll(page, 0, 400)
        assert res_scroll.success is True
        assert (0, 400) in page.mouse.wheels

        res_press = executor.press_key(page, "Enter")
        assert res_press.success is True
        assert "Enter" in page.keyboard.pressed_keys

    def test_executor_catches_playwright_exceptions(self):
        page = MockPlaywrightPage()
        # Mock locator that raises timeout
        failing_loc = MockElementLocator(selector="#broken-btn", should_fail_click=True)
        page.locators["#broken-btn"] = failing_loc

        executor = PlaywrightExecutor()
        res = executor.click(page, "#broken-btn")
        assert res.success is False
        assert "Playwright TimeoutError" in (res.error_message or "")
        assert res.latency_ms > 0


# ============================================================================
# Test Suite 3: Invariant Selector Cache & Self-Healing Fallback Chain
# ============================================================================

class TestLocatorResolverAndCache:
    """Verifies fallback chain (CSS fails -> XPath succeeds), LRU cache, and self-healing."""

    def test_fallback_css_fails_xpath_succeeds(self):
        """Primary test required by Task 2.6: mock an AXTree where primary CSS fails but XPath succeeds."""
        page = MockPlaywrightPage(default_present=False)

        # Target node with both CSS and XPath
        node = AXNode(
            index=1,
            role="button",
            name="Confirm Transaction",
            value=None,
            description=None,
            is_actionable=True,
            states=["focusable"],
            backend_dom_id=42,
            css_selector="button.broken-obsolete-class",
            xpath="//button[@id='confirm-tx']",
            text="Confirm Transaction",
            aria_label="Confirm Transaction",
            bbox=(100, 200, 120, 40),
        )

        # Configure page so CSS selector fails (count=0), but XPath succeeds (count=1)
        page.locators["button.broken-obsolete-class"] = MockElementLocator(
            selector="button.broken-obsolete-class", count=0, visible=False
        )
        page.locators["//button[@id='confirm-tx']"] = MockElementLocator(
            selector="//button[@id='confirm-tx']", count=1, visible=True
        )

        resolver = LocatorResolver()
        resolved = resolver.resolve(node, page=page)

        assert resolved.strategy == "xpath"
        assert resolved.selector == "//button[@id='confirm-tx']"
        assert resolved.confidence == 0.80
        assert resolved.target_node == node

    def test_fallback_full_chain_to_bbox(self):
        """When CSS, XPath, Role, and Text fail on page, fallback to Bounding Box."""
        page = MockPlaywrightPage(default_present=False)

        node = AXNode(
            index=2,
            role="canvas_widget",
            name="Custom Canvas Item",
            value=None,
            description=None,
            is_actionable=True,
            states=[],
            backend_dom_id=None,
            css_selector="canvas.item",
            xpath="//canvas[@class='item']",
            bbox=(50, 60, 100, 80),
        )

        # Everything fails on page except bbox coordinates
        page.locators["canvas.item"] = MockElementLocator(selector="canvas.item", count=0)
        page.locators["//canvas[@class='item']"] = MockElementLocator(selector="//canvas[@class='item']", count=0)

        resolver = LocatorResolver()
        resolved = resolver.resolve(node, page=page)

        assert resolved.strategy == "bbox"
        assert resolved.selector == "coords:100.0,100.0"
        assert resolved.confidence == 0.40

    def test_lru_cache_hit_and_self_healing(self):
        """Verifies LRU cache stores resolved strategy and evicts on DOM drift."""
        page = MockPlaywrightPage(default_present=False)
        node = AXNode(
            index=3,
            role="button",
            name="Submit",
            value=None,
            description=None,
            is_actionable=True,
            states=[],
            backend_dom_id=101,
            css_selector="button#submit",
            xpath="//button[@id='submit']",
        )
        page.locators["button#submit"] = MockElementLocator(selector="button#submit", count=1)

        resolver = LocatorResolver()
        goal = "submit form"

        # 1. First resolution: populates cache
        r1 = resolver.resolve(node, page=page, goal=goal)
        assert r1.cached is False
        assert len(resolver.cache) == 1

        # 2. Second resolution: hits cache
        r2 = resolver.resolve(node, page=page, goal=goal)
        assert r2.cached is True
        assert r2.selector == "button#submit"

        # 3. Simulate DOM drift: cached selector no longer works on page
        page.locators["button#submit"] = MockElementLocator(selector="button#submit", count=0)
        page.locators["//button[@id='submit']"] = MockElementLocator(selector="//button[@id='submit']", count=1)

        # 4. Self-healing: cache entry evicted, falls back to working XPath
        r3 = resolver.resolve(node, page=page, goal=goal)
        assert r3.strategy == "xpath"
        assert r3.selector == "//button[@id='submit']"


# ============================================================================
# Test Suite 4: Session Readiness Guard
# ============================================================================

class TestSessionReadinessGuard:
    """Verifies pre-action environment and target element readiness."""

    def test_readiness_passes_on_healthy_target(self):
        page = MockPlaywrightPage()
        page.locators["#active-btn"] = MockElementLocator(
            selector="#active-btn", visible=True, enabled=True, bbox={"x": 50, "y": 50, "width": 80, "height": 30}
        )

        guard = SessionGuard()
        res = guard.verify_readiness(page, target_selector="#active-btn")
        assert res.is_ready is True
        assert res.page_stable is True
        assert res.target_visible is True
        assert res.target_enabled is True

    def test_readiness_blocks_on_hidden_element(self):
        page = MockPlaywrightPage()
        page.locators["#hidden-btn"] = MockElementLocator(
            selector="#hidden-btn", visible=False, enabled=True
        )

        guard = SessionGuard()
        res = guard.verify_readiness(page, target_selector="#hidden-btn", wait_if_unready=False)
        assert res.is_ready is False
        assert res.target_visible is False
        assert "not visible" in (res.reason or "")

    def test_readiness_blocks_on_disabled_element(self):
        page = MockPlaywrightPage()
        page.locators["#disabled-btn"] = MockElementLocator(
            selector="#disabled-btn", visible=True, enabled=False
        )

        guard = SessionGuard()
        res = guard.verify_readiness(page, target_selector="#disabled-btn", wait_if_unready=False)
        assert res.is_ready is False
        assert res.target_enabled is False
        assert "disabled" in (res.reason or "")

    def test_readiness_zero_pixel_trap_detection(self):
        """Detects flex-collapsed element with 0px dimensions (ColdStart F-039)."""
        page = MockPlaywrightPage()
        page.locators["#collapsed-btn"] = MockElementLocator(
            selector="#collapsed-btn", visible=True, enabled=True, bbox={"x": 10, "y": 10, "width": 100, "height": 0}
        )

        guard = SessionGuard(min_dimension_px=5.0)
        res = guard.verify_readiness(page, target_selector="#collapsed-btn", wait_if_unready=False)
        assert res.is_ready is False
        assert "Zero-Pixel Trap" in (res.reason or "")

    def test_readiness_blocks_on_blocking_overlay(self):
        page = MockPlaywrightPage()
        page.locators["#target-under-modal"] = MockElementLocator(
            selector="#target-under-modal", visible=True, enabled=True
        )
        # Add modal backdrop
        page.locators[".modal-backdrop, .modal.show, [role='dialog'][aria-modal='true'], .loading-overlay"] = (
            MockElementLocator(selector=".modal-backdrop", count=1, visible=True)
        )

        guard = SessionGuard()
        res = guard.verify_readiness(page, target_selector="#target-under-modal", wait_if_unready=False)
        assert res.is_ready is False
        assert res.no_blocking_overlay is False
        assert "modal or backdrop" in (res.reason or "")


# ============================================================================
# Test Suite 5: State Verification Engine
# ============================================================================

class TestStateVerifier:
    """Verifies state transition detection, SimHash diffing, and stuck detection."""

    def test_state_change_detected_on_simhash_delta(self):
        verifier = StateVerifier()
        action_res = ActionResult(success=True, verb="CLICK", target_selector="#next-step")

        state_before = "- [#1] button 'Save Draft'\n- [#2] input 'Name'"
        state_after = "- [#1] button 'Save Draft'\n- [#2] input 'Name' value='Alice'\n- [#3] text 'Draft Saved'"

        res = verifier.verify(action_res, state_before, state_after)
        assert res.state_changed is True
        assert res.hamming_distance > 0
        assert res.text_delta_detected is True
        assert res.is_stuck_indicator is False

    def test_state_change_detected_on_url_change(self):
        verifier = StateVerifier()
        action_res = ActionResult(
            success=True, verb="CLICK", target_selector="a#nav-invoices", resulting_url="https://app.arc.local/invoices"
        )
        state_text = "- page 'Dashboard'"

        res = verifier.verify(
            action_res,
            state_text,
            state_text,
            url_before="https://app.arc.local/dashboard",
            url_after="https://app.arc.local/invoices",
        )
        assert res.state_changed is True
        assert res.url_changed is True
        assert res.is_stuck_indicator is False

    def test_stuck_indicator_on_no_op_click(self):
        """Action succeeds mechanically, but produces zero state delta -> flag stuck."""
        verifier = StateVerifier()
        action_res = ActionResult(success=True, verb="CLICK", target_selector="#inert-button")

        state_identical = "- [#1] button 'Inert'\n- [#2] text 'No change'"

        res = verifier.verify(
            action_res,
            state_identical,
            state_identical,
            url_before="https://app.arc.local/dashboard",
            url_after="https://app.arc.local/dashboard",
        )
        assert res.state_changed is False
        assert res.hamming_distance == 0
        assert res.is_stuck_indicator is True

    def test_neutral_action_wait_not_flagged_as_stuck(self):
        """WAIT action with 0 state delta is expected and not flagged as stuck."""
        verifier = StateVerifier()
        action_res = ActionResult(success=True, verb="WAIT")
        state_identical = "- page content"

        res = verifier.verify(action_res, state_identical, state_identical)
        assert res.state_changed is False
        assert res.is_stuck_indicator is False


# ============================================================================
# Test Suite 6: Reflex Runner Execution & Escalation
# ============================================================================

class TestReflexRunner:
    """Verifies execution loop, telemetry recording, and ESCALATE conditions."""

    def test_reflex_runner_successful_run(self):
        page = MockPlaywrightPage()
        runner = ReflexRunner()

        steps = [
            ActionStep(step_number=1, verb="CLICK", target_selector="#nav-link", value=None, action_index=None, latency_ms=0, success=True),
            ActionStep(step_number=2, verb="TYPE", target_selector="input#search", value="Arc 2026", action_index=None, latency_ms=0, success=True),
        ]

        result = runner.run_steps(page, steps, task_goal="Search for Arc records")
        assert result.status == ReflexStatus.COMPLETED
        assert len(result.completed_steps) == 2
        assert result.escalation_payload is None
        assert len(result.telemetry_records) == 2

        # Verify telemetry breakdown
        first_record = result.telemetry_records[0]
        assert first_record.route == "reflex"
        assert first_record.tokens_consumed == 0
        assert "resolution_latency_ms" in first_record.metadata
        assert "verification_latency_ms" in first_record.metadata

    def test_reflex_runner_escalates_on_repeated_stuck_actions(self):
        """When actions succeed mechanically but state fails to change 3 times, escalate."""
        page = MockPlaywrightPage()
        # State verifier always sees identical state
        runner = ReflexRunner(max_stuck_attempts=3)

        # 3 clicks on an unresponsive button that changes nothing
        steps = [
            ActionStep(step_number=1, verb="CLICK", target_selector="#stuck-btn", value=None, action_index=None, latency_ms=0, success=True),
            ActionStep(step_number=2, verb="CLICK", target_selector="#stuck-btn", value=None, action_index=None, latency_ms=0, success=True),
            ActionStep(step_number=3, verb="CLICK", target_selector="#stuck-btn", value=None, action_index=None, latency_ms=0, success=True),
        ]

        # Explicitly pass identical tree so state never changes
        extractor = CDP_AXTree_Extractor()
        static_tree = extractor.sanitize([{"nodeId": 1, "backendDOMNodeId": 10, "role": {"value": "button"}, "name": {"value": "Stuck Button"}}])

        result = runner.run_steps(page, steps, initial_tree=static_tree, task_goal="Attempt stuck clicks")
        assert result.status == ReflexStatus.ESCALATE
        assert result.escalation_payload is not None
        assert result.escalation_payload.reason == EscalationReason.STATE_NOT_CHANGED
        assert result.escalation_payload.failure_details["consecutive_stuck_count"] == 3

    def test_reflex_runner_escalates_on_locator_not_found(self):
        """When a locator cannot be found after fallback chain, escalate immediately."""
        page = MockPlaywrightPage()
        runner = ReflexRunner()

        # Step referencing non-existent action index in an empty tree
        extractor = CDP_AXTree_Extractor()
        empty_tree = extractor.sanitize([])

        steps = [
            ActionStep(step_number=1, verb="CLICK", target_selector=None, value=None, action_index=999, latency_ms=0, success=True),
        ]

        result = runner.run_steps(page, steps, initial_tree=empty_tree, task_goal="Click non-existent index")
        assert result.status == ReflexStatus.ESCALATE
        assert result.escalation_payload is not None
        assert result.escalation_payload.reason == EscalationReason.LOCATOR_NOT_FOUND


# ============================================================================
# Test Suite 7: Empirical Benchmark Distributions (N=100)
# ============================================================================

class TestPhase2EmpiricalBenchmarks:
    """Measures p50/p95/p99 latencies across N=100 iterations for Phase 2 components."""

    def test_benchmark_locator_resolution_n100(self):
        """Measure locator resolution latency across N=100 runs."""
        page = MockPlaywrightPage()
        resolver = LocatorResolver()

        node = AXNode(
            index=1,
            role="button",
            name="Checkout",
            value=None,
            description=None,
            is_actionable=True,
            states=[],
            backend_dom_id=50,
            css_selector="button.checkout-primary",
            xpath="//button[@class='checkout-primary']",
            bbox=(10, 20, 100, 30),
        )
        page.locators["button.checkout-primary"] = MockElementLocator(selector="button.checkout-primary", count=1)

        latencies: List[float] = []
        for i in range(100):
            start = time.perf_counter()
            # Alternating query and node resolution
            res = resolver.resolve(node, page=page, goal=f"checkout-{i % 5}")
            latencies.append((time.perf_counter() - start) * 1000.0)

        dist = compute_percentiles(latencies, "locator_resolution_ms")
        print(f"\n[BENCHMARK] Locator Resolution (N=100): p50={dist.p50:.4f}ms, p95={dist.p95:.4f}ms, p99={dist.p99:.4f}ms")
        assert dist.p50 < 1.0, f"p50 locator resolution ({dist.p50}ms) must be < 1.0ms"

    def test_benchmark_action_execution_overhead_n100(self):
        """Measure PlaywrightExecutor action dispatch latency across N=100 runs."""
        page = MockPlaywrightPage()
        executor = PlaywrightExecutor(audit_compliance=False)
        payload = ActionPayload(verb=ActionVerb.CLICK, target_selector="#perf-button")

        latencies: List[float] = []
        for _ in range(100):
            start = time.perf_counter()
            res = executor.execute(page, payload)
            latencies.append((time.perf_counter() - start) * 1000.0)
            assert res.success is True

        dist = compute_percentiles(latencies, "action_execution_ms")
        print(f"\n[BENCHMARK] Action Execution Overhead (N=100): p50={dist.p50:.4f}ms, p95={dist.p95:.4f}ms, p99={dist.p99:.4f}ms")
        assert dist.p50 < 1.5, f"p50 execution overhead ({dist.p50}ms) must be < 1.5ms"

    def test_benchmark_state_verification_simhash_n100(self):
        """Measure StateVerifier SimHash diffing and Hamming distance latency across N=100 runs."""
        verifier = StateVerifier()
        action_res = ActionResult(success=True, verb="CLICK", target_selector="#btn")

        state_before = "\n".join([f"- [#{i}] button 'Item {i}' css='button.item-{i}'" for i in range(50)])
        state_after = "\n".join([f"- [#{i}] button 'Item {i}' css='button.item-{i}'" for i in range(51)])

        latencies: List[float] = []
        for _ in range(100):
            start = time.perf_counter()
            res = verifier.verify(action_res, state_before, state_after)
            latencies.append((time.perf_counter() - start) * 1000.0)
            assert res.state_changed is True

        dist = compute_percentiles(latencies, "state_verification_ms")
        print(f"\n[BENCHMARK] State Verification (N=100): p50={dist.p50:.4f}ms, p95={dist.p95:.4f}ms, p99={dist.p99:.4f}ms")
        assert dist.p50 < 3.0, f"p50 state verification ({dist.p50}ms) must be < 3.0ms"


# ============================================================================
# Test Suite 8: Live Browser End-to-End Execution
# ============================================================================

class TestLiveBrowserReflexExecution:
    """Validates Reflex execution loop on real Chromium instance without mocks."""

    def test_live_chromium_reflex_e2e(self):
        """End-to-end execution of TYPE and CLICK on real rendered HTML in Chromium."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            pytest.skip("Playwright not installed in environment")

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.set_content("""
                    <!DOCTYPE html>
                    <html>
                    <head><title>Live Test</title></head>
                    <body>
                        <h1 id="greeting">Hello World</h1>
                        <input id="input-name" type="text" placeholder="Your Name" />
                        <button id="greet-btn" onclick="document.getElementById('greeting').innerText='Hello ' + document.getElementById('input-name').value">Greet</button>
                    </body>
                    </html>
                """)

                runner = ReflexRunner()
                steps = [
                    ActionStep(step_number=1, verb="TYPE", target_selector="input#input-name", value="Arc", action_index=None, latency_ms=0, success=True),
                    ActionStep(step_number=2, verb="CLICK", target_selector="button#greet-btn", value=None, action_index=None, latency_ms=0, success=True),
                ]

                result = runner.run_steps(page, steps, task_goal="Type name and click greet button")
                assert result.status == ReflexStatus.COMPLETED
                assert len(result.completed_steps) == 2
                assert page.locator("#greeting").inner_text() == "Hello Arc"

                browser.close()
        except Exception as e:
            if "Executable doesn't exist" in str(e):
                pytest.skip("Playwright Chromium browser binary not available")
            raise

