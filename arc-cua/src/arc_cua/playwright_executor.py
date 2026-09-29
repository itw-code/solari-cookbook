"""Deterministic Playwright Executor for Phase 2 Reflex Automation.

Implements Task 2.1:
- Implements the ActionExecutor interface defined in executor_interface.py.
- Implements methods: click, type_text, select, scroll, press_key, goto, wait.
- Ensures all actions use strict element-readiness contracts via public Playwright APIs.
- Catches Playwright timeouts and DOM exceptions, returning structured ActionResult schemas.
- Strictly adheres to public Playwright APIs, zero usage of private internals.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import Error as PlaywrightError
except ImportError:
    PlaywrightTimeoutError = TimeoutError  # type: ignore
    PlaywrightError = RuntimeError  # type: ignore

from .executor_interface import (
    ActionExecutor,
    ActionPayload,
    ActionVerb,
    audit_public_api_compliance,
)
from .schemas import ActionResult

logger = logging.getLogger("arc_cua.playwright_executor")


# Scrolls the nearest scrollable ancestor of the resolved element and reports the
# measured offset delta, so a delivered no-op is distinguishable from a real scroll.
# Virtualised containers own their overflow, so a viewport wheel does not move them.
_SCROLL_ELEMENT_SCRIPT = """
(el, [dx, dy]) => {
    const isScrollable = (node, axis) => {
        const size = axis === 'y' ? node.scrollHeight - node.clientHeight
                                  : node.scrollWidth - node.clientWidth;
        if (size <= 1) return false;
        const overflow = getComputedStyle(node)[axis === 'y' ? 'overflowY' : 'overflowX'];
        return overflow === 'auto' || overflow === 'scroll' || overflow === 'overlay';
    };

    let target = null;
    let fellBackToDocument = false;
    for (let node = el; node; node = node.parentElement) {
        if (isScrollable(node, 'y') || isScrollable(node, 'x')) { target = node; break; }
    }
    if (!target) {
        // No scrollable ancestor: the document itself is the only thing that can move.
        // Report this explicitly - silently scrolling the document while claiming an
        // element scroll is the same defect class as the viewport-wheel bug this
        // function exists to fix.
        target = document.scrollingElement || document.documentElement;
        fellBackToDocument = true;
    }

    const topBefore = target.scrollTop;
    const leftBefore = target.scrollLeft;
    target.scrollTop = topBefore + dy;
    target.scrollLeft = leftBefore + dx;

    return {
        top_before: topBefore,
        top_after: target.scrollTop,
        left_before: leftBefore,
        left_after: target.scrollLeft,
        scroll_height: target.scrollHeight,
        client_height: target.clientHeight,
        fell_back_to_document: fellBackToDocument,
        scrolled_node: fellBackToDocument
            ? 'document'
            : (target.id ? '#' + target.id
                : (target.getAttribute && target.getAttribute('data-testid')
                    ? '[data-testid=' + target.getAttribute('data-testid') + ']'
                    : target.tagName.toLowerCase())),
    };
}
"""


class PlaywrightExecutor(ActionExecutor):
    """Deterministic local execution engine using strictly public Playwright APIs."""

    def __init__(self, default_timeout_ms: float = 5000.0, audit_compliance: bool = True):
        """Initialize the deterministic Playwright executor.

        Args:
            default_timeout_ms: Fallback timeout in milliseconds for element interactions.
            audit_compliance: If True, audits page objects for forbidden private internals.
        """
        self.default_timeout_ms = default_timeout_ms
        self.audit_compliance = audit_compliance

    def _pre_action_audit(self, page: Any) -> None:
        """Verify target page object does not access forbidden private attributes."""
        if self.audit_compliance:
            is_clean, violations = audit_public_api_compliance(page)
            if not is_clean:
                logger.warning(
                    f"Public API Audit Warning: page target exposes private internals: {violations}"
                )

    def execute(self, page: Any, action: ActionPayload) -> ActionResult:
        """Route ActionPayload to respective public Playwright method.

        Args:
            page: Public Playwright Page object.
            action: ActionPayload command with verb and parameters.

        Returns:
            ActionResult with timing, success status, and error diagnostics.
        """
        self._pre_action_audit(page)
        timeout_ms = action.timeout_ms or self.default_timeout_ms

        if action.verb in (ActionVerb.CLICK, ActionVerb.DBLCLICK):
            if action.coordinates is not None:
                x, y = action.coordinates
                return self.click(page, f"coords:{x},{y}", timeout_ms=timeout_ms)
            if action.target_selector:
                return self.click(page, action.target_selector, timeout_ms=timeout_ms)
            return ActionResult(
                success=False,
                verb=action.verb.value,
                error_message="CLICK requires target_selector or coordinates",
                action=action,
            )

        elif action.verb in (ActionVerb.TYPE, ActionVerb.FILL):
            if not action.target_selector:
                return ActionResult(
                    success=False,
                    verb=action.verb.value,
                    error_message="TYPE/FILL requires target_selector",
                    action=action,
                )
            return self.type_text(
                page, action.target_selector, action.value or "", timeout_ms=timeout_ms
            )

        elif action.verb == ActionVerb.SELECT_OPTION:
            if not action.target_selector or action.value is None:
                return ActionResult(
                    success=False,
                    verb=action.verb.value,
                    error_message="SELECT_OPTION requires target_selector and value",
                    action=action,
                )
            return self.select(
                page, action.target_selector, action.value, timeout_ms=timeout_ms
            )

        elif action.verb == ActionVerb.PRESS_KEY:
            if not action.value:
                return ActionResult(
                    success=False,
                    verb=action.verb.value,
                    error_message="PRESS_KEY requires key value",
                    action=action,
                )
            return self.press_key(page, action.value)

        elif action.verb == ActionVerb.SCROLL:
            dx, dy = action.scroll_delta or (0, 300)
            return self.scroll(
                page,
                dx,
                dy,
                target_selector=action.target_selector,
                timeout_ms=timeout_ms,
            )

        elif action.verb == ActionVerb.NAVIGATE:
            if not action.value:
                return ActionResult(
                    success=False,
                    verb=action.verb.value,
                    error_message="NAVIGATE requires URL value",
                    action=action,
                )
            return self.goto(page, action.value, timeout_ms=timeout_ms)

        elif action.verb == ActionVerb.WAIT_FOR_SELECTOR:
            if action.target_selector:
                start = time.perf_counter()
                try:
                    page.locator(action.target_selector).wait_for(
                        state="visible", timeout=timeout_ms
                    )
                    lat = (time.perf_counter() - start) * 1000.0
                    return ActionResult(
                        success=True,
                        verb="WAIT_FOR_SELECTOR",
                        target_selector=action.target_selector,
                        latency_ms=lat,
                        resulting_url=getattr(page, "url", None),
                        action=action,
                    )
                except Exception as e:
                    lat = (time.perf_counter() - start) * 1000.0
                    return ActionResult(
                        success=False,
                        verb="WAIT_FOR_SELECTOR",
                        target_selector=action.target_selector,
                        latency_ms=lat,
                        error_message=str(e),
                        resulting_url=getattr(page, "url", None),
                        action=action,
                    )
            else:
                wait_dur = int(action.value) if (action.value and str(action.value).isdigit()) else timeout_ms
                return self.wait(page, timeout_ms=wait_dur)
        else:
            return ActionResult(
                success=False,
                verb=str(action.verb),
                error_message=f"Unsupported action verb: {action.verb}",
                action=action,
            )

    def click(self, page: Any, selector: str, timeout_ms: float = 3000.0) -> ActionResult:
        """Click an element via public `page.locator(selector).click()` or coordinate click."""
        self._pre_action_audit(page)
        start = time.perf_counter()

        try:
            # Check for coordinate-based click string
            if selector.startswith("coords:"):
                raw_coords = selector[len("coords:"):]
                cx, cy = [float(c.strip()) for c in raw_coords.split(",")]
                page.mouse.click(cx, cy)
                lat = (time.perf_counter() - start) * 1000.0
                return ActionResult(
                    success=True,
                    verb="CLICK",
                    target_selector=selector,
                    latency_ms=lat,
                    resulting_url=getattr(page, "url", None),
                    metadata={"click_type": "coordinates", "x": cx, "y": cy},
                )

            # Public Playwright locator click: auto-waits for visible, stable, enabled, non-occluded
            loc = page.locator(selector)
            loc.click(timeout=timeout_ms)

            lat = (time.perf_counter() - start) * 1000.0
            return ActionResult(
                success=True,
                verb="CLICK",
                target_selector=selector,
                latency_ms=lat,
                resulting_url=getattr(page, "url", None),
                metadata={"click_type": "locator"},
            )
        except (PlaywrightTimeoutError, PlaywrightError, Exception) as exc:
            lat = (time.perf_counter() - start) * 1000.0
            logger.debug(f"Click failed on '{selector}': {exc}")
            return ActionResult(
                success=False,
                verb="CLICK",
                target_selector=selector,
                latency_ms=lat,
                error_message=str(exc),
                resulting_url=getattr(page, "url", None),
            )

    def type_text(
        self, page: Any, selector: str, text: str, timeout_ms: float = 3000.0
    ) -> ActionResult:
        """Type or fill text into an element via public `page.locator(selector).fill(text)`."""
        self._pre_action_audit(page)
        start = time.perf_counter()

        try:
            loc = page.locator(selector)
            # Public Playwright fill: auto-waits for visible, stable, enabled
            loc.fill(text, timeout=timeout_ms)

            lat = (time.perf_counter() - start) * 1000.0
            return ActionResult(
                success=True,
                verb="TYPE",
                target_selector=selector,
                value=text,
                latency_ms=lat,
                resulting_url=getattr(page, "url", None),
            )
        except (PlaywrightTimeoutError, PlaywrightError, Exception) as exc:
            lat = (time.perf_counter() - start) * 1000.0
            logger.debug(f"Type failed on '{selector}': {exc}")
            return ActionResult(
                success=False,
                verb="TYPE",
                target_selector=selector,
                value=text,
                latency_ms=lat,
                error_message=str(exc),
                resulting_url=getattr(page, "url", None),
            )

    def select(
        self, page: Any, selector: str, value: str, timeout_ms: float = 3000.0
    ) -> ActionResult:
        """Select dropdown option via public `page.locator(selector).select_option(value=value)`."""
        self._pre_action_audit(page)
        start = time.perf_counter()

        try:
            loc = page.locator(selector)
            # Public Playwright select_option
            loc.select_option(value=value, timeout=timeout_ms)

            lat = (time.perf_counter() - start) * 1000.0
            return ActionResult(
                success=True,
                verb="SELECT",
                target_selector=selector,
                value=value,
                latency_ms=lat,
                resulting_url=getattr(page, "url", None),
            )
        except (PlaywrightTimeoutError, PlaywrightError, Exception) as exc:
            lat = (time.perf_counter() - start) * 1000.0
            logger.debug(f"Select failed on '{selector}': {exc}")
            return ActionResult(
                success=False,
                verb="SELECT",
                target_selector=selector,
                value=value,
                latency_ms=lat,
                error_message=str(exc),
                resulting_url=getattr(page, "url", None),
            )

    def scroll(
        self,
        page: Any,
        delta_x: int,
        delta_y: int,
        target_selector: Optional[str] = None,
        timeout_ms: float = 3000.0,
    ) -> ActionResult:
        """Scroll a resolved container element, or the viewport when no target is given.

        A viewport-level wheel event does nothing to a virtualised container that owns
        its own overflow (Metabase's results table: scrollHeight 816,408px vs clientHeight
        169px), yet the old implementation ignored the resolved target and reported
        `success: true` for a delivered no-op (audit F-04). When a target is supplied the
        nearest scrollable ancestor is scrolled instead, and the measured scroll offset
        delta is reported so a no-op is visible to the caller.

        Args:
            page: Public Playwright Page object.
            delta_x: Horizontal scroll delta in pixels.
            delta_y: Vertical scroll delta in pixels.
            target_selector: Optional container to scroll; falls back to viewport wheel.
            timeout_ms: Locator resolution timeout.

        Returns:
            ActionResult with scroll_mode and measured offset deltas in metadata.
        """
        self._pre_action_audit(page)
        start = time.perf_counter()

        if target_selector:
            try:
                loc = page.locator(target_selector)
                # Walk to the nearest scrollable ancestor: the AXTree target is often an
                # inner wrapper, while the overflow lives on a parent container.
                measured = loc.evaluate(
                    _SCROLL_ELEMENT_SCRIPT, [delta_x, delta_y], timeout=timeout_ms
                )
                lat = (time.perf_counter() - start) * 1000.0

                applied = bool(
                    measured.get("top_after") != measured.get("top_before")
                    or measured.get("left_after") != measured.get("left_before")
                )
                fell_back = bool(measured.get("fell_back_to_document"))
                metadata = {
                    "delta_x": delta_x,
                    "delta_y": delta_y,
                    # Distinguish a genuine element scroll from a document fallback:
                    # the caller must not be told an element scrolled when the page did.
                    "scroll_mode": "document" if fell_back else "element",
                    "scroll_applied": applied,
                    "scroll_top_before": measured.get("top_before"),
                    "scroll_top_after": measured.get("top_after"),
                    "scroll_height": measured.get("scroll_height"),
                    "client_height": measured.get("client_height"),
                    "scrolled_node": measured.get("scrolled_node"),
                    "target_selector": target_selector,
                }
                if fell_back:
                    metadata["scroll_fallback_reason"] = (
                        "no scrollable ancestor for the target; the document was scrolled"
                    )
                return ActionResult(
                    success=True,
                    verb="SCROLL",
                    target_selector=target_selector,
                    latency_ms=lat,
                    resulting_url=getattr(page, "url", None),
                    metadata=metadata,
                )
            except (PlaywrightTimeoutError, PlaywrightError, Exception) as exc:
                lat = (time.perf_counter() - start) * 1000.0
                logger.debug(f"Element scroll failed on '{target_selector}': {exc}")
                return ActionResult(
                    success=False,
                    verb="SCROLL",
                    target_selector=target_selector,
                    latency_ms=lat,
                    error_message=str(exc),
                    resulting_url=getattr(page, "url", None),
                    metadata={"delta_x": delta_x, "delta_y": delta_y, "scroll_mode": "element"},
                )

        try:
            page.mouse.wheel(delta_x, delta_y)
            lat = (time.perf_counter() - start) * 1000.0
            return ActionResult(
                success=True,
                verb="SCROLL",
                latency_ms=lat,
                resulting_url=getattr(page, "url", None),
                metadata={
                    "delta_x": delta_x,
                    "delta_y": delta_y,
                    "scroll_mode": "viewport",
                    "scroll_applied": None,
                },
            )
        except (PlaywrightTimeoutError, PlaywrightError, Exception) as exc:
            lat = (time.perf_counter() - start) * 1000.0
            logger.debug(f"Scroll failed ({delta_x}, {delta_y}): {exc}")
            return ActionResult(
                success=False,
                verb="SCROLL",
                latency_ms=lat,
                error_message=str(exc),
                resulting_url=getattr(page, "url", None),
                metadata={"delta_x": delta_x, "delta_y": delta_y, "scroll_mode": "viewport"},
            )

    def press_key(self, page: Any, key: str) -> ActionResult:
        """Dispatch keyboard event via public `page.keyboard.press(key)`."""
        self._pre_action_audit(page)
        start = time.perf_counter()

        try:
            page.keyboard.press(key)
            lat = (time.perf_counter() - start) * 1000.0
            return ActionResult(
                success=True,
                verb="PRESS_KEY",
                value=key,
                latency_ms=lat,
                resulting_url=getattr(page, "url", None),
            )
        except (PlaywrightTimeoutError, PlaywrightError, Exception) as exc:
            lat = (time.perf_counter() - start) * 1000.0
            logger.debug(f"Press key failed '{key}': {exc}")
            return ActionResult(
                success=False,
                verb="PRESS_KEY",
                value=key,
                latency_ms=lat,
                error_message=str(exc),
                resulting_url=getattr(page, "url", None),
            )

    def goto(self, page: Any, url: str, timeout_ms: float = 30000.0) -> ActionResult:
        """Navigate via public `page.goto(url)`."""
        self._pre_action_audit(page)
        start = time.perf_counter()

        try:
            page.goto(url, timeout=timeout_ms)
            lat = (time.perf_counter() - start) * 1000.0
            return ActionResult(
                success=True,
                verb="GOTO",
                value=url,
                latency_ms=lat,
                resulting_url=getattr(page, "url", None),
            )
        except (PlaywrightTimeoutError, PlaywrightError, Exception) as exc:
            lat = (time.perf_counter() - start) * 1000.0
            logger.debug(f"Goto failed on '{url}': {exc}")
            return ActionResult(
                success=False,
                verb="GOTO",
                value=url,
                latency_ms=lat,
                error_message=str(exc),
                resulting_url=getattr(page, "url", None),
            )

    def wait(self, page: Any, timeout_ms: float = 1000.0) -> ActionResult:
        """Wait via public `page.wait_for_timeout(timeout_ms)`."""
        self._pre_action_audit(page)
        start = time.perf_counter()

        try:
            if hasattr(page, "wait_for_timeout"):
                page.wait_for_timeout(timeout_ms)
            else:
                time.sleep(timeout_ms / 1000.0)

            lat = (time.perf_counter() - start) * 1000.0
            return ActionResult(
                success=True,
                verb="WAIT",
                latency_ms=lat,
                resulting_url=getattr(page, "url", None),
            )
        except (PlaywrightTimeoutError, PlaywrightError, Exception) as exc:
            lat = (time.perf_counter() - start) * 1000.0
            logger.debug(f"Wait failed: {exc}")
            return ActionResult(
                success=False,
                verb="WAIT",
                latency_ms=lat,
                error_message=str(exc),
                resulting_url=getattr(page, "url", None),
            )
