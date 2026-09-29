"""One long-lived browser behind open / inspect / act / close.

Shared core for the MCP server (and the CLI's perception helpers). Holding the Playwright
connection in-process removes the per-call reconnect and the `~/.omp` state files the CLI
needs, and keeps the no-op streak and the `[#N]` index map in memory.

Backends:
- `local`: headless (or visible) Chromium launched by Playwright.
- `solari`: a Solari cloud browser provisioned via `SolariCloudDriver` and released on close.
- `cdp`: attach to any existing CDP endpoint (disconnects on close, never kills it).

Playwright's sync API is thread-affine: every method must be called from the thread that
called `open()`. The MCP server guarantees this with a single worker thread.
"""

from __future__ import annotations

import json
import logging
import time
import weakref
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from arc_cua.cdp_extractor import CDP_AXTree_Extractor
from arc_cua.executor_interface import ActionPayload, ActionVerb
from arc_cua.playwright_executor import PlaywrightExecutor
from arc_cua.state_verifier import StateVerifier

logger = logging.getLogger("arc_cua.browser_session")

# Consecutive mutating no-op actions on one target before a stall is reported.
ACT_STALL_THRESHOLD = 3
SOFT_NAVIGATION_WAIT_MS = 2000
SETTLE_POLL_MS = 300
ALLOWED_URL_SCHEMES = frozenset({"http", "https", "file", "about"})
BACKENDS = ("local", "solari", "cdp")

VERB_MAP: Dict[str, ActionVerb] = {
    "CLICK": ActionVerb.CLICK,
    "DBLCLICK": ActionVerb.DBLCLICK,
    # HOVER is omitted on purpose: PlaywrightExecutor does not implement it yet.
    "TYPE": ActionVerb.TYPE,
    "FILL": ActionVerb.FILL,
    "SELECT": ActionVerb.SELECT_OPTION,
    "SELECT_OPTION": ActionVerb.SELECT_OPTION,
    "PRESS_KEY": ActionVerb.PRESS_KEY,
    "SCROLL": ActionVerb.SCROLL,
    "WAIT": ActionVerb.WAIT_FOR_SELECTOR,
    "WAIT_FOR_SELECTOR": ActionVerb.WAIT_FOR_SELECTOR,
    "NAVIGATE": ActionVerb.NAVIGATE,
    "GOTO": ActionVerb.NAVIGATE,
}
NEUTRAL_VERBS = frozenset({ActionVerb.WAIT_FOR_SELECTOR})


class BrowserSessionError(RuntimeError):
    """A caller-facing failure with an actionable message."""


# --- perception helpers (also re-exported by arc_cua.cli) -------------------------------------

_CDP_SESSIONS: "weakref.WeakKeyDictionary[Any, Any]" = weakref.WeakKeyDictionary()


def page_cdp(page: Any) -> Any:
    """One CDP session per page, with Accessibility and DOM enabled once.

    Every CDP message is a network round trip on a remote (Solari) browser, about
    0.2-0.5 s. A fresh session per call (attach, two enables, detach) cost more round
    trips than the work itself.
    """
    cdp = _CDP_SESSIONS.get(page)
    if cdp is None:
        cdp = page.context.new_cdp_session(page)
        cdp.send("Accessibility.enable")
        cdp.send("DOM.enable")
        _CDP_SESSIONS[page] = cdp
    return cdp


def cdp_send(page: Any, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """Send on the page's cached session, reattaching once if it was detached."""
    try:
        return page_cdp(page).send(method, params or {})
    except Exception:
        _CDP_SESSIONS.pop(page, None)
        return page_cdp(page).send(method, params or {})


def extract_page_tree(page: Any, extractor: Any) -> Any:
    """Extract the live AXTree from a Playwright page via CDP (two round trips)."""
    ax = cdp_send(page, "Accessibility.getFullAXTree")
    dom = cdp_send(page, "DOM.getDocument", {"depth": -1, "pierce": True})
    return extractor.sanitize(ax.get("nodes", []), dom.get("root"))


def settle_and_extract(page: Any, extractor: Any, settle_ms: float) -> Tuple[Any, int]:
    """Extract the AXTree after waiting for a client-rendered page to hydrate.

    `DOMContentLoaded` precedes hydration for SPAs, so extracting immediately observes
    an empty shell and reports it as a successful perception of a blank page
    (audit F-01). This waits for network idle (bounded; websocket-backed apps never
    reach it) and then re-extracts on a bounded poll until actionable nodes appear.

    Args:
        page: Live Playwright page.
        extractor: Sanitized AXTree extractor.
        settle_ms: Total budget in milliseconds for the settle phase.

    Returns:
        Tuple of (SanitizedAXTree, extraction attempt count).
    """
    deadline = time.monotonic() + max(0.0, settle_ms) / 1000.0

    # Stage 1: bounded network-idle wait. Best-effort only: apps holding an open
    # websocket or a polling timer never reach idle, so a timeout here is expected.
    remaining_ms = max(0.0, (deadline - time.monotonic()) * 1000.0)
    if remaining_ms > 0:
        try:
            page.wait_for_load_state("networkidle", timeout=remaining_ms)
        except Exception as e:
            logger.debug(f"networkidle settle timed out (expected for SPA/polling apps): {e}")

    # Stage 2: poll until actionable nodes appear or the budget is exhausted.
    tree = extract_page_tree(page, extractor)
    attempts = 1
    while tree.actionable_count == 0 and time.monotonic() < deadline:
        page.wait_for_timeout(min(250.0, max(0.0, (deadline - time.monotonic()) * 1000.0)))
        tree = extract_page_tree(page, extractor)
        attempts += 1

    return tree, attempts


def resolve_target(target_arg: Optional[str], index_arg: Optional[int],
                   tree_map: Optional[Dict[int, Any]]) -> Tuple[Optional[str], Optional[int]]:
    """Disambiguate monotonic index (@N or [#N] or --index N) from CSS/XPath selectors.

    Prevents collision where '#3' could mean CSS id='3' vs index 3.
    """
    idx: Optional[int] = None
    if index_arg is not None:
        idx = int(index_arg)
    elif target_arg:
        stripped = target_arg.strip()
        if stripped.startswith("@") and stripped[1:].isdigit():
            idx = int(stripped[1:])
        elif stripped.startswith("[#") and stripped.endswith("]") and stripped[2:-1].isdigit():
            idx = int(stripped[2:-1])
        else:
            # Standard CSS / XPath / text locator: keep as-is (e.g. '#submit-btn', '#3' for id='3')
            return target_arg, None
    else:
        return None, None

    if tree_map and idx in tree_map:
        entry = tree_map[idx]
        return entry.get("css") or entry.get("xpath") or f"text='{entry.get('name')}'", idx
    return None, idx


def check_url(url: str) -> str:
    """Reject navigation schemes that execute code or smuggle content (javascript:, data:)."""
    scheme = urlparse(url).scheme.lower()
    if scheme not in ALLOWED_URL_SCHEMES:
        raise BrowserSessionError(
            f"Refusing URL scheme '{scheme or '(none)'}:'. Allowed schemes: {sorted(ALLOWED_URL_SCHEMES)}. "
            "Use a full URL such as https://example.com."
        )
    return url


def format_tree(tree: Any, attempts: int, settle_ms: float) -> str:
    """Render a sanitized tree as the agent-facing text block (header, nodes, warnings)."""
    header = (f"# AXTree [Actionable: {tree.actionable_count} | Tokens: ~{tree.estimated_tokens} | "
              f"Latency: {tree.sanitization_latency_ms:.2f}ms]")
    # The extractor already appends the truncation manifest to yaml_linearized.
    lines = [header + (" | Truncated" if tree.truncated else ""), tree.yaml_linearized or "(empty tree)"]
    if tree.truncated:
        lines.append("NOTE: '# !DROPPED-ACTIONABLE [#N]' entries are still valid arc_act indices.")
    if tree.actionable_count == 0:
        lines.append(
            f"WARNING: no actionable nodes after {attempts} extraction attempt(s) within {settle_ms:.0f}ms. "
            "The page may still be hydrating, require login, or render canvas/WebGL the accessibility "
            "tree does not expose. Retry with a larger settle_ms, or use a screenshot."
        )
    return "\n".join(lines)


# --- session ----------------------------------------------------------------------------------

class BrowserSession:
    """Owns one browser connection plus the agent-visible state that goes with it."""

    def __init__(
        self,
        playwright_factory: Optional[Callable[[], Any]] = None,
        solari_driver_factory: Optional[Callable[[], Any]] = None,
    ):
        self._playwright_factory = playwright_factory
        self._solari_driver_factory = solari_driver_factory
        self._extractor = CDP_AXTree_Extractor()
        self._verifier = StateVerifier()
        self._pw: Any = None
        self.browser: Any = None
        self.page: Any = None
        self.backend: Optional[str] = None
        self._visible = False
        self._solari: Any = None
        self._solari_session: Any = None
        self._index_map: Dict[int, Any] = {}
        self._evicted_map: Dict[int, Any] = {}
        self._inspected_yaml: Optional[str] = None
        self._streak_key: Optional[str] = None
        self._streak = 0

    def _reset_perception(self) -> None:
        self._index_map, self._evicted_map, self._inspected_yaml = {}, {}, None

    @property
    def is_open(self) -> bool:
        return self.page is not None

    def _require_open(self) -> None:
        if not self.is_open:
            raise BrowserSessionError("No browser is open. Call arc_open first.")

    # --- lifecycle ---------------------------------------------------------------------------

    def open(self, url: Optional[str] = None, backend: str = "local", cdp_url: Optional[str] = None,
             visible: bool = False, stealth: bool = False) -> Dict[str, Any]:
        """Open (or reuse) a browser, optionally navigating to `url`.

        Reuses the current browser when the backend and visibility match; otherwise the
        current one is closed first and page state is lost.
        """
        if backend not in BACKENDS:
            raise BrowserSessionError(f"Unknown backend '{backend}'. Use one of {list(BACKENDS)}.")
        if backend == "cdp" and not cdp_url:
            raise BrowserSessionError("backend='cdp' requires cdp_url (ws:// or http:// DevTools endpoint).")
        if url:
            check_url(url)

        notice = None
        if self.is_open and (backend != self.backend or visible != self._visible or backend == "cdp"):
            self.close()
            notice = "Previous browser closed; page state and [#N] indices from it are gone."

        if not self.is_open:
            self._launch(backend, cdp_url, visible, stealth)

        if url:
            self.page.goto(url, wait_until="domcontentloaded")
            self._reset_perception()

        info = self.status()
        if notice:
            info["notice"] = notice
        return info

    def _launch(self, backend: str, cdp_url: Optional[str], visible: bool, stealth: bool) -> None:
        if self._pw is None:
            if self._playwright_factory:
                self._pw = self._playwright_factory()
            else:
                try:
                    from playwright.sync_api import sync_playwright
                except ImportError as e:
                    raise BrowserSessionError("Playwright is required: pip install playwright && playwright install chromium") from e
                self._pw = sync_playwright().start()

        if backend == "local":
            self.browser = self._pw.chromium.launch(headless=not visible)
            context = self.browser.new_context()
        else:
            if backend == "solari":
                if self._solari is None:
                    from arc_cua.cloud.solari_driver import SolariCloudDriver
                    self._solari = (self._solari_driver_factory or SolariCloudDriver)()
                self._solari_session = self._solari.provision_browser(stealth=stealth)
                cdp_url = self._solari_session.cdp_endpoint
            try:
                self.browser = self._pw.chromium.connect_over_cdp(cdp_url, timeout=30000)
            except Exception:
                self._release_solari()
                raise
            context = self.browser.contexts[0] if self.browser.contexts else self.browser.new_context()

        self.page = context.pages[0] if context.pages else context.new_page()
        self.backend, self._visible = backend, visible
        self._streak_key, self._streak = None, 0

    def _release_solari(self) -> None:
        if self._solari is not None and self._solari_session is not None:
            self._solari.terminate(self._solari_session.session_id)
        self._solari_session = None

    def close(self) -> Dict[str, Any]:
        """Close the browser (release it on Solari, disconnect on cdp). Idempotent."""
        was_open = self.is_open
        backend = self.backend
        try:
            if self.browser is not None:
                self.browser.close()
        except Exception as e:
            logger.warning(f"Browser close failed: {e}")
        finally:
            self._release_solari()
            self.browser = self.page = self.backend = None
            self._reset_perception()
            self._streak_key, self._streak = None, 0
        return {"closed": was_open, "backend": backend}

    def shutdown(self) -> None:
        """Close the browser and stop Playwright."""
        self.close()
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception as e:
                logger.debug(f"Playwright stop failed: {e}")
            self._pw = None

    def status(self) -> Dict[str, Any]:
        """Describe the current browser (no secrets: Solari endpoints are never returned)."""
        if not self.is_open:
            return {"open": False}
        info: Dict[str, Any] = {"open": True, "backend": self.backend, "url": self.page.url, "title": self.page.title()}
        if self._solari_session is not None:
            info["expires_at"] = self._solari_session.expires_at
        return info

    # --- perception & action -----------------------------------------------------------------

    def inspect(self, settle_ms: float = 5000.0, query: Optional[str] = None) -> Dict[str, Any]:
        """Extract the token-budgeted AXTree and remember its `[#N]` map for `act`.

        With `query`, return instead every affordance on the page - including ones the
        budget evicted - whose role or name contains all of the query's words. This is
        how an agent finds a named element on a truncated page.
        """
        self._require_open()
        tree, attempts = settle_and_extract(self.page, self._extractor, settle_ms)
        self._index_map = dict(tree.action_index_map)
        self._evicted_map = dict(tree.evicted_index_map)
        self._inspected_yaml = tree.yaml_linearized
        text = format_tree(tree, attempts, settle_ms) if not query else self._format_matches(query)
        return {
            "text": text,
            "url": self.page.url,
            "actionable_count": tree.actionable_count,
            "estimated_tokens": tree.estimated_tokens,
            "truncated": tree.truncated,
            "truncation_notice": tree.truncation_notice,
            "dropped_actionable_count": tree.dropped_actionable_count,
            "settle_attempts": attempts,
            "action_index_map": self._index_map,
        }

    def _format_matches(self, query: str, limit: int = 60) -> str:
        words = [w for w in query.lower().split() if w]
        known = {**self._evicted_map, **self._index_map}
        hits = [
            (idx, e) for idx, e in sorted(known.items())
            if all(w in f"{e.get('role', '')} {e.get('name') or ''}".lower() for w in words)
        ]
        lines = [f"# Matches for {json.dumps(query, ensure_ascii=False)}: {len(hits)} of {len(known)} affordances"
                 + (f" (first {limit} shown)" if len(hits) > limit else "")]
        for idx, e in hits[:limit]:
            name = json.dumps(e.get("name") or "", ensure_ascii=False)
            lines.append(f"- [#{idx}] {e.get('role')} {name}")
        if not hits:
            lines.append("(no affordance matches; plain text is not searched - try other words or arc_inspect without query)")
        return "\n".join(lines)

    def _mark_boxes(self, full_page: bool) -> List[Dict[str, Any]]:
        """Boxes (CSS px, relative to the captured image) for every known [#N].

        One `DOMSnapshot.captureSnapshot` round trip returns layout bounds for all nodes
        keyed by backendNodeId; per-node box queries would cost one network round trip
        each on a remote (Solari) browser.
        """
        known = {**self._evicted_map, **self._index_map}
        by_backend = {e.get("backend_dom_id"): idx for idx, e in known.items() if e.get("backend_dom_id")}
        if not by_backend:
            return []
        snap = cdp_send(self.page, "DOMSnapshot.captureSnapshot", {"computedStyles": []})
        doc = snap["documents"][0]
        backend_ids = doc["nodes"]["backendNodeId"]
        scroll_x, scroll_y = doc.get("scrollOffsetX", 0), doc.get("scrollOffsetY", 0)
        vw, vh = self.page.evaluate("[window.innerWidth, window.innerHeight]")

        marks: Dict[int, Dict[str, Any]] = {}
        for node_index, (x, y, w, h) in zip(doc["layout"]["nodeIndex"], doc["layout"]["bounds"]):
            idx = by_backend.get(backend_ids[node_index])
            if idx is None or idx in marks or w < 1 or h < 1:
                continue
            if not full_page:
                x, y = x - scroll_x, y - scroll_y
                if x + w <= 0 or y + h <= 0 or x >= vw or y >= vh:
                    continue
            marks[idx] = {"index": idx, "x": round(x, 1), "y": round(y, 1), "width": round(w, 1), "height": round(h, 1)}
        return sorted(marks.values(), key=lambda m: m["index"])

    def screenshot(self, marks: bool = True, full_page: bool = False, quality: int = 70) -> Dict[str, Any]:
        """Capture the page as JPEG in CSS pixels, optionally labelling [#N] affordances.

        Coordinates in the image equal page CSS pixels, so a point read off it can be
        clicked with `act("click", target="coords:x,y")` (canvas/WebGL content has no
        accessibility nodes to index). With marks and no prior inspect, one is run so the
        labels match a usable index map.
        """
        self._require_open()
        note = None
        if marks and not (self._index_map or self._evicted_map):
            self.inspect(settle_ms=2000)
            note = "arc_inspect was run to build the [#N] map shown in the marks."

        boxes = self._mark_boxes(full_page) if marks else []
        if boxes:
            self.page.evaluate(
                """([boxes, viewportRelative]) => {
                    const root = document.createElement('div');
                    root.setAttribute('data-arc-overlay', '1');
                    root.style.cssText = 'position:absolute;left:0;top:0;width:0;height:0;z-index:2147483647;pointer-events:none';
                    // Viewport-relative boxes are drawn in document coordinates.
                    const ox = viewportRelative ? window.scrollX : 0, oy = viewportRelative ? window.scrollY : 0;
                    for (const b of boxes) {
                        const box = document.createElement('div');
                        box.style.cssText = `position:absolute;left:${b.x + ox}px;top:${b.y + oy}px;width:${b.width}px;height:${b.height}px;outline:2px solid #e11d48;box-sizing:border-box`;
                        const tag = document.createElement('span');
                        tag.textContent = b.index;
                        // Inside the box: a label above it lands on the previous line in dense lists.
                        tag.style.cssText = 'position:absolute;left:0;top:0;background:rgba(225,29,72,.88);color:#fff;font:bold 10px/12px monospace;padding:0 2px';
                        box.appendChild(tag);
                        root.appendChild(box);
                    }
                    document.documentElement.appendChild(root);
                }""",
                [boxes, not full_page],
            )
        try:
            image = self.page.screenshot(type="jpeg", quality=quality, full_page=full_page, scale="css")
        finally:
            if boxes:
                self.page.evaluate("document.querySelectorAll('[data-arc-overlay]').forEach(e => e.remove())")

        vw, vh = self.page.evaluate("[window.innerWidth, window.innerHeight]")
        result: Dict[str, Any] = {
            "image": image,
            "format": "jpeg",
            "url": self.page.url,
            "viewport": {"width": vw, "height": vh},
            "full_page": full_page,
            "marked": len(boxes),
            "marks": boxes,
        }
        if note:
            result["note"] = note
        return result

    def _pin_node(self, backend_id: Optional[int]) -> Optional[str]:
        """Tag the DOM node behind an [#N] with `data-arc-pin` and return a selector for it.

        The extractor's CSS for elements without id/testid/label is text-derived and
        matches every identical link on list pages, which Playwright's strict locators
        reject. Chromium's backendNodeId identifies the exact node. Returns None when the
        node no longer exists (the caller falls back to the CSS locator).
        """
        if not backend_id:
            return None
        try:
            # Two round trips: resolve, then clear old pins and set this one in the same call.
            obj = cdp_send(self.page, "DOM.resolveNode", {"backendNodeId": int(backend_id)})["object"]["objectId"]
            cdp_send(self.page, "Runtime.callFunctionOn", {
                "objectId": obj,
                "functionDeclaration": "function(){"
                    " document.querySelectorAll('[data-arc-pin]').forEach(e => e.removeAttribute('data-arc-pin'));"
                    " (this.nodeType === 1 ? this : this.parentElement).setAttribute('data-arc-pin', '1'); }",
            })
            return "[data-arc-pin='1']"
        except Exception as e:
            logger.debug(f"Pinning backend node {backend_id} failed, using CSS locator: {e}")
            return None

    def act(self, action: str, index: Optional[int] = None, target: Optional[str] = None,
            value: Optional[str] = None, timeout_ms: float = 5000.0, observe: bool = False,
            settle_ms: float = 3000.0) -> Dict[str, Any]:
        """Dispatch one action, verify whether it changed the page, and track no-op streaks.

        `[#N]` indices resolve against the last `inspect`, i.e. what the agent actually saw.
        `page_changed_since_inspect` flags that the page has moved on since then.
        With `observe`, the result carries the post-action tree under `tree` and its
        indices replace the last inspect's, as if `inspect` had been called.
        """
        self._require_open()
        verb = VERB_MAP.get(action.strip().upper())
        if verb is None:
            raise BrowserSessionError(f"Unknown action '{action}'. Supported: {sorted(VERB_MAP)}")
        if verb == ActionVerb.NAVIGATE:
            check_url(value or "")

        target_is_index = index is not None or bool(target and target.strip()[:1] in ("@", "["))
        known = {**self._evicted_map, **self._index_map}
        if target_is_index and not known:
            raise BrowserSessionError("No [#N] index map yet. Call arc_inspect before acting by index.")
        selector, idx = resolve_target(target, index, known)
        if target_is_index and selector is None:
            raise BrowserSessionError(
                f"Index {idx} is not in the last inspect (valid: 1..{max(known, default=0)}). "
                "Re-run arc_inspect; the page may have changed."
            )
        if idx is not None:
            # Text-derived CSS (a:has-text('hide')) is ambiguous on list pages; pin the exact node.
            selector = self._pin_node(known[idx].get("backend_dom_id")) or selector

        tree_before = extract_page_tree(self.page, self._extractor)
        url_before = self.page.url
        payload = ActionPayload(verb=verb, target_selector=selector, action_index=idx,
                                value=value, timeout_ms=float(timeout_ms))
        start = time.perf_counter()
        result = PlaywrightExecutor(default_timeout_ms=float(timeout_ms)).execute(self.page, payload)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        tree_after = extract_page_tree(self.page, self._extractor)
        url_at_after = self.page.url
        ver = self._verifier.verify(result, tree_before.yaml_linearized, tree_after.yaml_linearized)

        is_noop = result.success and not ver.state_changed and not ver.url_changed and verb not in NEUTRAL_VERBS
        key = f"{verb.name}:{selector}"
        self._streak = (self._streak + 1 if key == self._streak_key else 1) if is_noop else 0
        self._streak_key = key if is_noop else None

        out: Dict[str, Any] = {
            "success": result.success,
            "verb": verb.name,
            "target": selector,
            "index": idx,
            "action_latency_ms": round(elapsed_ms, 2),
            "state_changed": ver.state_changed,
            "url_changed": ver.url_changed,
            "url": self.page.url,
            "hamming_distance": ver.hamming_distance,
            "noop_streak": self._streak,
            "stall_suspected": self._streak >= ACT_STALL_THRESHOLD,
            "page_changed_since_inspect": self._inspected_yaml is not None
            and tree_before.yaml_linearized != self._inspected_yaml,
            "error": result.error_message,
        }
        if result.metadata:
            out["metadata"] = result.metadata
        if out["stall_suspected"]:
            out["warning"] = (
                f"{self._streak} consecutive successful no-op actions on '{selector}'. The target is likely "
                "wrong or inert: re-inspect, pick another element, or take a screenshot."
            )
        if observe:
            changed = ver.state_changed or ver.url_changed
            if (verb == ActionVerb.CLICK and idx is not None and known[idx].get("role") == "link"
                    and result.success and self.page.url == url_before):
                changed = self._await_soft_navigation(url_before) or changed
            # If the URL moved only after tree_after was taken, tree_after is the old page plus
            # click side effects (focus); the new page must differ from it, not from tree_before.
            navigated_late = url_at_after == url_before and self.page.url != url_before
            baseline = tree_after if navigated_late else tree_before
            out["tree"] = self._observe_after(baseline.yaml_linearized, tree_after, changed, settle_ms)
            out["url"] = self.page.url
            out["url_changed"] = out["url"] != url_before
        return out

    def _await_soft_navigation(self, url_before: str) -> bool:
        """Give a clicked link a moment to navigate before the page is shown to the agent.

        Client-routed sites (GitHub's Turbo, most SPAs) fetch first and push the new URL
        later, so the tree taken right after the click is still the old page. An agent
        shown that page concludes the click failed (in the LLM benchmark, the model then
        typed the URL by hand). Bounded, and paid only by links that have not navigated yet.
        """
        try:
            self.page.wait_for_url(lambda u: u != url_before, wait_until="commit",
                                   timeout=SOFT_NAVIGATION_WAIT_MS)
            return True
        except Exception:
            return False

    def _observe_after(self, before_yaml: str, tree_after: Any, changed: bool, settle_ms: float) -> str:
        """The page as the agent should see it after an action, adopted as the new [#N] map.

        Saves the agent the arc_inspect round trip it would otherwise make after every
        action (about 1-2 s each on a remote Solari browser). A changed page is re-settled
        first, since the verifier's snapshot is taken right after dispatch, often before a
        navigation or re-render lands.
        """
        attempts = 1
        tree = tree_after
        if changed:
            tree, attempts = self._settle_changed_page(before_yaml, tree_after, settle_ms)
        self._index_map = dict(tree.action_index_map)
        self._evicted_map = dict(tree.evicted_index_map)
        self._inspected_yaml = tree.yaml_linearized
        return f"URL: {self.page.url}\n" + format_tree(tree, attempts, settle_ms)

    def _settle_changed_page(self, before_yaml: str, tree_after: Any, settle_ms: float) -> Tuple[Any, int]:
        """Extract once the page has visibly moved on from `before_yaml` and stopped changing.

        Network idle alone is not enough after an action: it does not reset for
        client-side navigations, so a router that pushes the URL before rendering
        (GitHub) still shows the old page. Poll until the tree differs from the
        pre-action tree, has actionable nodes, and two consecutive reads agree, within
        `settle_ms`. The verifier's post-action snapshot counts as the first read, so a
        page that changed synchronously costs one confirming extraction.
        """
        deadline = time.monotonic() + max(0.0, settle_ms) / 1000.0
        try:
            self.page.wait_for_load_state("networkidle", timeout=max(1.0, settle_ms))
        except Exception as e:
            logger.debug(f"networkidle wait after action timed out: {e}")
        tree, attempts = tree_after, 0
        while True:
            started = time.monotonic()
            nxt = extract_page_tree(self.page, self._extractor)
            attempts += 1
            settled = (nxt.yaml_linearized == tree.yaml_linearized and nxt.yaml_linearized != before_yaml
                       and nxt.actionable_count > 0)
            tree = nxt
            if settled or time.monotonic() >= deadline:
                return tree, attempts
            # Remote extractions already take longer than the poll interval; only pace local ones.
            pause_ms = SETTLE_POLL_MS - (time.monotonic() - started) * 1000
            if pause_ms > 0:
                self.page.wait_for_timeout(pause_ms)
