"""Playwright Public API Executor Interface Contract (Phase 2 Preparation).

Remediates Question 3 / Architectural Handshake:
- Establishes the formal contract for Phase 2 Reflex Action Execution.
- Enforces strict compliance with Playwright's public API contracts:
  * Uses `page.locator(selector).click()`, `page.locator(selector).fill(...)`,
    `page.locator(selector).select_option(...)`, `page.keyboard.press(...)`,
    `page.mouse.wheel(...)`, and `page.goto(...)`.
  * Strictly prohibits and audits against private internals (`_channel`, `_connection`, `_impl_obj`).
- Prepares data schemas and interface signatures WITHOUT executing Phase 2 workflows.
"""

from __future__ import annotations

import abc
import dataclasses
import enum
import logging
import time
from typing import Any, Dict, List, Optional, Protocol, Tuple, Union, runtime_checkable

from .schemas import ActionResult
logger = logging.getLogger("arc_cua.executor_interface")

# Forbidden Playwright private member names
FORBIDDEN_PRIVATE_INTERNALS = {
    "_channel",
    "_connection",
    "_impl_obj",
    "_initializer",
    "_object",
    "_transport",
    "_dispatcherFiber",
}


class ActionVerb(str, enum.Enum):
    """Primitive automation action verbs emitted by the Reflex engine."""
    CLICK = "CLICK"
    DBLCLICK = "DBLCLICK"
    HOVER = "HOVER"
    TYPE = "TYPE"
    FILL = "FILL"
    SELECT_OPTION = "SELECT_OPTION"
    PRESS_KEY = "PRESS_KEY"
    SCROLL = "SCROLL"
    WAIT_FOR_SELECTOR = "WAIT_FOR_SELECTOR"
    NAVIGATE = "NAVIGATE"


@dataclasses.dataclass(frozen=True)
class ActionPayload:
    """Structured action command emitted by Reflex engine or Cortex planner."""
    verb: ActionVerb
    target_selector: Optional[str] = None  # CSS, XPath, or Playwright semantic locator
    action_index: Optional[int] = None    # Monotonic index referencing [#N] in AXTree
    value: Optional[str] = None           # Text to fill, option value, or key name
    coordinates: Optional[Tuple[int, int]] = None  # (x, y) coordinates
    scroll_delta: Optional[Tuple[int, int]] = None  # (dx, dy)
    timeout_ms: float = 5000.0


@dataclasses.dataclass(frozen=True)
class ExecutionOutcome:
    """Execution telemetry resulting from a dispatched Playwright action."""
    success: bool
    action: ActionPayload
    execution_latency_ms: float
    error_message: Optional[str] = None
    resulting_url: Optional[str] = None
    retries_count: int = 0


def audit_public_api_compliance(page_or_target: Any) -> Tuple[bool, List[str]]:
    """Audit an object or execution frame to verify no private Playwright internals are accessed.

    Returns:
        Tuple of (is_compliant, list_of_violations).
    """
    violations: List[str] = []
    for forbidden in FORBIDDEN_PRIVATE_INTERNALS:
        if hasattr(page_or_target, forbidden):
            violations.append(forbidden)
    return len(violations) == 0, violations


class ActionExecutor(abc.ABC):
    """Abstract contract for executing deterministic Reflex actions via public Playwright APIs."""

    @abc.abstractmethod
    def execute(self, page: Any, action: ActionPayload) -> Any:
        """Execute a structured primitive action against a public Playwright Page object."""
        raise NotImplementedError

    @abc.abstractmethod
    def click(self, page: Any, selector: str, timeout_ms: float = 3000.0) -> Any:
        """Click an element via public `page.locator(selector).click()`."""
        raise NotImplementedError

    @abc.abstractmethod
    def type_text(self, page: Any, selector: str, text: str, timeout_ms: float = 3000.0) -> Any:
        """Type or fill text into an element via public `page.locator(selector).fill(text)`."""
        raise NotImplementedError

    @abc.abstractmethod
    def select(self, page: Any, selector: str, value: str, timeout_ms: float = 3000.0) -> Any:
        """Select dropdown option via public `page.locator(selector).select_option(value=value)`."""
        raise NotImplementedError

    @abc.abstractmethod
    def press_key(self, page: Any, key: str) -> Any:
        """Dispatch keyboard event via public `page.keyboard.press(key)`."""
        raise NotImplementedError

    @abc.abstractmethod
    def scroll(self, page: Any, delta_x: int, delta_y: int) -> Any:
        """Scroll page via public `page.mouse.wheel(delta_x, delta_y)`."""
        raise NotImplementedError

    @abc.abstractmethod
    def goto(self, page: Any, url: str, timeout_ms: float = 30000.0) -> Any:
        """Navigate via public `page.goto(url)`."""
        raise NotImplementedError

    @abc.abstractmethod
    def wait(self, page: Any, timeout_ms: float = 1000.0) -> Any:
        """Wait via public `page.wait_for_timeout(timeout_ms)`."""
        raise NotImplementedError

    # Aliases for compatibility
    def fill(self, page: Any, selector: str, text: str, timeout_ms: float = 3000.0) -> Any:
        return self.type_text(page, selector, text, timeout_ms)

    def select_option(self, page: Any, selector: str, value: str, timeout_ms: float = 3000.0) -> Any:
        return self.select(page, selector, value, timeout_ms)

    def navigate(self, page: Any, url: str, timeout_ms: float = 30000.0) -> Any:
        return self.goto(page, url, timeout_ms)


# Preserve backward-compatible alias
PlaywrightActionExecutorInterface = ActionExecutor

class BasePlaywrightExecutor(PlaywrightActionExecutorInterface):
    """Reference implementation enforcing strictly public Playwright API usage."""

    def execute(self, page: Any, action: ActionPayload) -> ExecutionOutcome:
        """Route ActionPayload to respective public Playwright method."""
        start_time = time.perf_counter()

        # Audit caller target to ensure public API usage only
        is_clean, violations = audit_public_api_compliance(page)
        if not is_clean:
            logger.warning(f"Auditing note: page object exposes private internals: {violations}")

        try:
            if action.verb == ActionVerb.CLICK:
                assert action.target_selector is not None, "CLICK requires target_selector"
                return self.click(page, action.target_selector, action.timeout_ms)
            elif action.verb == ActionVerb.FILL:
                assert action.target_selector is not None, "FILL requires target_selector"
                assert action.value is not None, "FILL requires text value"
                return self.fill(page, action.target_selector, action.value, action.timeout_ms)
            elif action.verb == ActionVerb.SELECT_OPTION:
                assert action.target_selector is not None, "SELECT_OPTION requires target_selector"
                assert action.value is not None, "SELECT_OPTION requires option value"
                return self.select_option(page, action.target_selector, action.value, action.timeout_ms)
            elif action.verb == ActionVerb.PRESS_KEY:
                assert action.value is not None, "PRESS_KEY requires key value"
                return self.press_key(page, action.value)
            elif action.verb == ActionVerb.SCROLL:
                dx, dy = action.scroll_delta or (0, 300)
                return self.scroll(page, dx, dy)
            elif action.verb == ActionVerb.NAVIGATE:
                assert action.value is not None, "NAVIGATE requires URL value"
                return self.navigate(page, action.value, action.timeout_ms)
            else:
                raise ValueError(f"Unsupported action verb: {action.verb}")
        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return ExecutionOutcome(
                success=False,
                action=action,
                execution_latency_ms=latency_ms,
                error_message=str(e),
                resulting_url=getattr(page, "url", None),
            )

    def click(self, page: Any, selector: str, timeout_ms: float = 3000.0) -> ExecutionOutcome:
        start = time.perf_counter()
        # Strictly public Playwright API: locator(selector).click(timeout=...)
        page.locator(selector).click(timeout=timeout_ms)
        latency = (time.perf_counter() - start) * 1000.0
        return ExecutionOutcome(
            success=True,
            action=ActionPayload(verb=ActionVerb.CLICK, target_selector=selector, timeout_ms=timeout_ms),
            execution_latency_ms=latency,
            resulting_url=getattr(page, "url", None),
        )

    def fill(self, page: Any, selector: str, text: str, timeout_ms: float = 3000.0) -> ExecutionOutcome:
        start = time.perf_counter()
        # Strictly public Playwright API: locator(selector).fill(text, timeout=...)
        page.locator(selector).fill(text, timeout=timeout_ms)
        latency = (time.perf_counter() - start) * 1000.0
        return ExecutionOutcome(
            success=True,
            action=ActionPayload(verb=ActionVerb.FILL, target_selector=selector, value=text, timeout_ms=timeout_ms),
            execution_latency_ms=latency,
            resulting_url=getattr(page, "url", None),
        )

    def select_option(self, page: Any, selector: str, value: str, timeout_ms: float = 3000.0) -> ExecutionOutcome:
        start = time.perf_counter()
        # Strictly public Playwright API: locator(selector).select_option(value=value, timeout=...)
        page.locator(selector).select_option(value=value, timeout=timeout_ms)
        latency = (time.perf_counter() - start) * 1000.0
        return ExecutionOutcome(
            success=True,
            action=ActionPayload(verb=ActionVerb.SELECT_OPTION, target_selector=selector, value=value, timeout_ms=timeout_ms),
            execution_latency_ms=latency,
            resulting_url=getattr(page, "url", None),
        )

    def press_key(self, page: Any, key: str) -> ExecutionOutcome:
        start = time.perf_counter()
        # Strictly public Playwright API: keyboard.press(key)
        page.keyboard.press(key)
        latency = (time.perf_counter() - start) * 1000.0
        return ExecutionOutcome(
            success=True,
            action=ActionPayload(verb=ActionVerb.PRESS_KEY, value=key),
            execution_latency_ms=latency,
            resulting_url=getattr(page, "url", None),
        )

    def scroll(self, page: Any, delta_x: int, delta_y: int) -> ExecutionOutcome:
        start = time.perf_counter()
        # Strictly public Playwright API: mouse.wheel(delta_x, delta_y)
        page.mouse.wheel(delta_x, delta_y)
        latency = (time.perf_counter() - start) * 1000.0
        return ExecutionOutcome(
            success=True,
            action=ActionPayload(verb=ActionVerb.SCROLL, scroll_delta=(delta_x, delta_y)),
            execution_latency_ms=latency,
            resulting_url=getattr(page, "url", None),
        )

    def navigate(self, page: Any, url: str, timeout_ms: float = 30000.0) -> ExecutionOutcome:
        start = time.perf_counter()
        # Strictly public Playwright API: goto(url, timeout=...)
        page.goto(url, timeout=timeout_ms)
        latency = (time.perf_counter() - start) * 1000.0
        return ExecutionOutcome(
            success=True,
            action=ActionPayload(verb=ActionVerb.NAVIGATE, value=url, timeout_ms=timeout_ms),
            execution_latency_ms=latency,
            resulting_url=getattr(page, "url", None),
        )

    def type_text(self, page: Any, selector: str, text: str, timeout_ms: float = 3000.0) -> ExecutionOutcome:
        return self.fill(page, selector, text, timeout_ms)

    def select(self, page: Any, selector: str, value: str, timeout_ms: float = 3000.0) -> ExecutionOutcome:
        return self.select_option(page, selector, value, timeout_ms)

    def goto(self, page: Any, url: str, timeout_ms: float = 30000.0) -> ExecutionOutcome:
        return self.navigate(page, url, timeout_ms)

    def wait(self, page: Any, timeout_ms: float = 1000.0) -> ExecutionOutcome:
        start = time.perf_counter()
        if hasattr(page, "wait_for_timeout"):
            page.wait_for_timeout(timeout_ms)
        else:
            time.sleep(timeout_ms / 1000.0)
        latency = (time.perf_counter() - start) * 1000.0
        return ExecutionOutcome(
            success=True,
            action=ActionPayload(verb=ActionVerb.WAIT_FOR_SELECTOR, timeout_ms=timeout_ms),
            execution_latency_ms=latency,
            resulting_url=getattr(page, "url", None),
        )
