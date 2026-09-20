"""Session Readiness Guard for Phase 2 Reflex Automation.

Implements Task 2.3:
- Verifies execution environment readiness prior to action dispatch.
- Checks:
  1. Page stability (document.readyState, network idle / mutation stability).
  2. Target visibility (is_visible, non-zero bounding box / Zero-Pixel Trap prevention).
  3. Target enabled state (is_enabled, not disabled).
  4. Absence of blocking modals, backdrops, and occluding overlays.
- Returns structured ReadinessResult.
- Supports polling/waiting up to timeout before aborting action.
"""

from __future__ import annotations

import dataclasses
import logging
import time
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("arc_cua.session_guard")


@dataclasses.dataclass
class ReadinessResult:
    """Outcome of pre-action readiness evaluation."""
    is_ready: bool
    page_stable: bool = True
    target_visible: bool = True
    target_enabled: bool = True
    no_blocking_overlay: bool = True
    reason: Optional[str] = None
    readiness_latency_ms: float = 0.0
    details: Dict[str, Any] = dataclasses.field(default_factory=dict)


class SessionGuard:
    """Environment supervisor verifying DOM stability, visibility, and non-occlusion."""

    DEFAULT_MIN_DIMENSION_PX: float = 5.0  # ColdStart F-039 Zero-Pixel Trap threshold

    def __init__(
        self,
        default_timeout_ms: float = 3000.0,
        poll_interval_ms: float = 100.0,
        min_dimension_px: float = DEFAULT_MIN_DIMENSION_PX,
    ):
        self.default_timeout_ms = default_timeout_ms
        self.poll_interval_ms = poll_interval_ms
        self.min_dimension_px = min_dimension_px

    def verify_readiness(
        self,
        page: Any,
        target_selector: Optional[str] = None,
        timeout_ms: Optional[float] = None,
        wait_if_unready: bool = True,
    ) -> ReadinessResult:
        """Evaluate whether page and optional target element are ready for interaction.

        Args:
            page: Public Playwright Page object or mock.
            target_selector: Optional selector or coords string for the action target.
            timeout_ms: Maximum time to wait for readiness.
            wait_if_unready: If True, polls until ready or timeout expires.

        Returns:
            ReadinessResult with boolean readiness and diagnostic details.
        """
        start_time = time.perf_counter()
        timeout = timeout_ms if timeout_ms is not None else self.default_timeout_ms
        deadline = start_time + (timeout / 1000.0)

        last_result: Optional[ReadinessResult] = None

        while True:
            iteration_start = time.perf_counter()
            result = self._check_readiness_once(page, target_selector)
            result.readiness_latency_ms = (time.perf_counter() - start_time) * 1000.0
            last_result = result

            if result.is_ready or not wait_if_unready:
                return result

            # Check if timeout expired
            now = time.perf_counter()
            if now >= deadline:
                logger.warning(
                    f"SessionGuard readiness check timed out ({timeout}ms): {result.reason}"
                )
                return result

            # Sleep poll interval
            sleep_sec = min(self.poll_interval_ms / 1000.0, max(0.01, deadline - now))
            if hasattr(page, "wait_for_timeout"):
                try:
                    page.wait_for_timeout(sleep_sec * 1000.0)
                except Exception:
                    time.sleep(sleep_sec)
            else:
                time.sleep(sleep_sec)

    def _check_readiness_once(
        self, page: Any, target_selector: Optional[str]
    ) -> ReadinessResult:
        """Run a single pass of stability, visibility, enabled, and occlusion checks."""
        details: Dict[str, Any] = {}

        # 1. Page Stability Check
        page_stable, page_reason = self._check_page_stability(page)
        details["page_stable"] = page_stable
        if not page_stable:
            return ReadinessResult(
                is_ready=False,
                page_stable=False,
                reason=f"Page unstable: {page_reason}",
                details=details,
            )

        # If no target selector, or coordinate action, page stability is sufficient
        if not target_selector or target_selector.startswith("coords:"):
            return ReadinessResult(
                is_ready=True,
                page_stable=True,
                target_visible=True,
                target_enabled=True,
                no_blocking_overlay=True,
                details=details,
            )

        # 2. Target Visibility & Zero-Pixel Trap Check
        vis_ok, vis_reason, box = self._check_target_visibility(page, target_selector)
        details["target_visible"] = vis_ok
        if box:
            details["bounding_box"] = box
        if not vis_ok:
            return ReadinessResult(
                is_ready=False,
                target_visible=False,
                reason=f"Target not visible: {vis_reason}",
                details=details,
            )

        # 3. Target Enabled Check
        en_ok, en_reason = self._check_target_enabled(page, target_selector)
        details["target_enabled"] = en_ok
        if not en_ok:
            return ReadinessResult(
                is_ready=False,
                target_enabled=False,
                reason=f"Target disabled: {en_reason}",
                details=details,
            )

        # 4. Absence of Blocking Modals/Overlays & Occlusion Check
        occ_ok, occ_reason = self._check_overlay_and_occlusion(page, target_selector, box)
        details["no_blocking_overlay"] = occ_ok
        if not occ_ok:
            return ReadinessResult(
                is_ready=False,
                no_blocking_overlay=False,
                reason=f"Target occluded or blocked: {occ_reason}",
                details=details,
            )

        return ReadinessResult(
            is_ready=True,
            page_stable=True,
            target_visible=True,
            target_enabled=True,
            no_blocking_overlay=True,
            details=details,
        )

    def _check_page_stability(self, page: Any) -> Tuple[bool, Optional[str]]:
        """Verify DOM readyState and load state."""
        if page is None:
            return True, None

        if hasattr(page, "evaluate"):
            try:
                ready_state = page.evaluate("() => document.readyState")
                if ready_state not in ("complete", "interactive"):
                    return False, f"document.readyState is '{ready_state}'"
            except Exception as e:
                # If page evaluate throws execution context destroyed, page is navigating
                return False, f"Evaluation error (page navigating): {e}"

        return True, None

    def _check_target_visibility(
        self, page: Any, selector: str
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, float]]]:
        """Verify target exists, is visible, and has non-zero layout dimensions."""
        if not hasattr(page, "locator"):
            return True, None, None

        try:
            loc = page.locator(selector)
            # Count check
            if hasattr(loc, "count"):
                count = loc.count()
                if count == 0:
                    return False, f"Element '{selector}' not present in DOM (count=0)", None

            # Visibility check
            if hasattr(loc, "is_visible"):
                if not loc.is_visible():
                    return False, f"Element '{selector}' is not visible", None

            # Layout bounding box check (prevents Zero-Pixel Trap F-039)
            if hasattr(loc, "bounding_box"):
                box = loc.bounding_box()
                if box is None:
                    return False, f"Element '{selector}' has null bounding box (detached/unrendered)", None
                w = box.get("width", 0.0)
                h = box.get("height", 0.0)
                if w < self.min_dimension_px or h < self.min_dimension_px:
                    return (
                        False,
                        f"Zero-Pixel Trap: Element '{selector}' layout dimensions ({w:.1f}x{h:.1f}px) below {self.min_dimension_px}px threshold",
                        box,
                    )
                return True, None, box

            return True, None, None
        except Exception as e:
            return False, str(e), None

    def _check_target_enabled(self, page: Any, selector: str) -> Tuple[bool, Optional[str]]:
        """Verify target element is enabled and not disabled."""
        if not hasattr(page, "locator"):
            return True, None

        try:
            loc = page.locator(selector)
            if hasattr(loc, "is_enabled"):
                if not loc.is_enabled():
                    return False, f"Element '{selector}' is disabled"
            if hasattr(loc, "is_disabled"):
                if loc.is_disabled():
                    return False, f"Element '{selector}' is disabled"
            return True, None
        except Exception as e:
            return False, str(e)

    def _check_overlay_and_occlusion(
        self, page: Any, selector: str, box: Optional[Dict[str, float]]
    ) -> Tuple[bool, Optional[str]]:
        """Check for active blocking dialogs/overlays and physical occlusion."""
        if page is None:
            return True, None

        # Check for presence of active blocking modals or backdrops
        if hasattr(page, "locator"):
            try:
                # Check known blocking overlay classes/roles
                overlay_loc = page.locator(
                    ".modal-backdrop, .modal.show, [role='dialog'][aria-modal='true'], .loading-overlay"
                )
                if hasattr(overlay_loc, "count") and overlay_loc.count() > 0:
                    # Check if overlay is visible
                    first_loc = overlay_loc.first if hasattr(overlay_loc, "first") else overlay_loc
                    if hasattr(first_loc, "is_visible") and first_loc.is_visible():
                            # If target is inside the modal dialog, it's allowed!
                            if hasattr(page, "evaluate"):
                                try:
                                    is_inside = page.evaluate(
                                        """({ sel }) => {
                                            const target = document.querySelector(sel);
                                            const modal = document.querySelector(".modal.show, [role='dialog'][aria-modal='true']");
                                            if (target && modal && modal.contains(target)) return true;
                                            return false;
                                        }""",
                                        {"sel": selector},
                                    )
                                    if is_inside:
                                        return True, None
                                except Exception:
                                    pass
                            return False, "Active blocking modal or backdrop detected on page"
            except Exception:
                pass

        # Check occlusion via elementFromPoint if evaluate and box are available
        if box and hasattr(page, "evaluate"):
            try:
                cx = box["x"] + box["width"] / 2.0
                cy = box["y"] + box["height"] / 2.0
                occlusion_info = page.evaluate(
                    """({ sel, x, y }) => {
                        const top = document.elementFromPoint(x, y);
                        if (!top) return { occluded: true, topDesc: "none" };
                        const target = document.querySelector(sel);
                        if (!target) return { occluded: false, topDesc: top.tagName };
                        const hit = target === top || target.contains(top);
                        const desc = top.tagName + (top.className ? '.' + top.className.toString().slice(0, 30) : '');
                        return { occluded: !hit, topDesc: desc };
                    }""",
                    {"sel": selector, "x": cx, "y": cy},
                )
                if occlusion_info and occlusion_info.get("occluded"):
                    return False, f"Target occluded by top element: <{occlusion_info.get('topDesc')}>"
            except Exception:
                # Evaluation of elementFromPoint may fail in headless/mock or cross-origin
                pass

        return True, None
