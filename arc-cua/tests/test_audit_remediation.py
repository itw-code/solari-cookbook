"""Regression suite for the ARC-CUA audit remediations (BENCH-CRM-PERSONA, 2026-09-22).

Each test pins a defect measured on a live authenticated SaaS surface, where the reflex
layer reported success while silently losing the information the caller needed:

1. `inspect --url` raced SPA hydration and reported an empty page as a valid observation.
2. `_print_tree` printed only the header, so the perception payload never reached stdout.
3. The 1,200-token cap evicted an open "Download results" dialog behind 90 gridcells and
   emitted no truncation boundary, so the caller could not tell anything had been dropped.
4. `scroll` ignored its resolved target, driving a viewport-level wheel that a virtualised
   container ignores, and reported the no-op as success.
5. A successful action with zero state change was recorded but never treated as a stall.

Every test here fails against the pre-remediation code.
"""

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from arc_cua import cli
from arc_cua.cdp_extractor import MAX_TOKENS, CDP_AXTree_Extractor

try:
    from arc_cua.cdp_extractor import MANIFEST_TOKEN_RESERVE
except ImportError:
    # Pre-remediation revisions have no manifest at all, so the constant does not exist.
    # Fall back rather than aborting the import: a module-level ImportError would collapse
    # the whole file into a single collection error when this suite is run against pre-fix
    # sources, hiding the per-test discrimination that proves each test earns its place.
    MANIFEST_TOKEN_RESERVE = 64

from arc_cua.executor_interface import ActionPayload, ActionVerb
from arc_cua.monitors.stuck_monitor import StepTelemetry, StuckMonitor
from arc_cua.playwright_executor import PlaywrightExecutor


# ============================================================================
# Fixtures: the Metabase Customer 360 shape
# ============================================================================

def dense_results_with_open_dialog(rows: int = 120) -> List[Dict[str, Any]]:
    """Raw CDP AX nodes: a dense results table plus an open Download-results dialog.

    Mirrors the BENCH-CRM-PERSONA surface, where 90 gridcells exhausted the token budget
    and the modal that was actually on screen was silently dropped.
    """
    nodes: List[Dict[str, Any]] = [
        {
            "nodeId": "1",
            "role": {"value": "RootWebArea"},
            "name": {"value": "Customer 360"},
            "childIds": ["2", "900"],
        },
        {
            "nodeId": "2",
            "role": {"value": "table"},
            "name": {"value": "Results"},
            "childIds": [str(10 + i) for i in range(rows)],
        },
    ]
    for i in range(rows):
        nodes.append({
            "nodeId": str(10 + i),
            "role": {"value": "row"},
            "name": {"value": ""},
            "childIds": [str(200 + i)],
        })
        nodes.append({
            "nodeId": str(200 + i),
            "role": {"value": "gridcell"},
            "name": {"value": f"customer_row_{i:03d}_long_cell_value_payload_creating_token_pressure"},
            "childIds": [],
        })

    nodes.append({
        "nodeId": "900",
        "role": {"value": "dialog"},
        "name": {"value": "Download results"},
        "childIds": ["901", "902", "903"],
    })
    nodes.append({"nodeId": "901", "role": {"value": "button"}, "name": {"value": "Download"}, "childIds": []})
    nodes.append({"nodeId": "902", "role": {"value": "button"}, "name": {"value": "Download results"}, "childIds": []})
    nodes.append({
        "nodeId": "903",
        "role": {"value": "radiogroup"},
        "name": {"value": "File format"},
        "childIds": ["910", "911", "912", "913"],
    })
    for nid, label in [
        ("910", ".csv"),
        ("911", ".xlsx"),
        ("912", ".json"),
        ("913", "Keep the data formatted"),
    ]:
        nodes.append({"nodeId": nid, "role": {"value": "radio"}, "name": {"value": label}, "childIds": []})

    return nodes


# ============================================================================
# Defect 3: the token cap must not evict interactive nodes
# ============================================================================

class TestTokenBudgetPreservesAffordances:
    """A dense data table must never evict the dialog that is currently on screen."""

    def test_dialog_survives_dense_gridcell_eviction(self):
        tree = CDP_AXTree_Extractor().sanitize(dense_results_with_open_dialog())

        assert tree.truncated is True, "fixture must actually exceed the budget"
        assert tree.estimated_tokens <= MAX_TOKENS, "manifest must still fit the hard cap"

        # The defect: zero nodes matching 'download' survived tail truncation.
        assert "Download results" in tree.yaml_linearized
        assert "button \"Download\"" in tree.yaml_linearized

        # The radio group offering the export format is reachable, not just the dialog.
        for option in (".csv", ".xlsx", ".json", "Keep the data formatted"):
            assert option in tree.yaml_linearized, f"radio option {option!r} was evicted"

    def test_evicted_nodes_are_announced_not_silent(self):
        tree = CDP_AXTree_Extractor().sanitize(dense_results_with_open_dialog())

        assert tree.truncation_notice is not None, "truncation must be announced"
        assert "BUDGET-TRUNCATED" in tree.truncation_notice
        assert "gridcell" in tree.truncation_notice
        assert tree.dropped_node_count > 0
        assert tree.yaml_linearized.endswith(tree.truncation_notice)

    def test_evicted_actionable_is_named_in_manifest(self):
        """Dropped affordances are named, so the caller knows what it cannot reach."""
        nodes = dense_results_with_open_dialog(rows=140)
        # Push an actionable button into the data region so it is a genuine eviction candidate.
        for i in range(40):
            nodes.append({
                "nodeId": str(500 + i),
                "role": {"value": "button"},
                "name": {"value": f"row_action_{i:03d}"},
                "childIds": [],
            })
        nodes[1]["childIds"] = list(nodes[1]["childIds"]) + [str(500 + i) for i in range(40)]

        tree = CDP_AXTree_Extractor().sanitize(nodes)

        if tree.dropped_actionable_count:
            assert "DROPPED-ACTIONABLE" in tree.truncation_notice
            # A caller must not be able to address an index that is no longer in the tree.
            for idx in tree.action_index_map:
                assert f"[#{idx}]" in tree.yaml_linearized

    def test_action_index_map_never_references_evicted_nodes(self):
        tree = CDP_AXTree_Extractor().sanitize(dense_results_with_open_dialog())

        for idx in tree.action_index_map:
            assert f"[#{idx}]" in tree.yaml_linearized, (
                f"index {idx} survived in action_index_map but not in the rendered tree"
            )
        assert tree.actionable_count == len(tree.action_index_map)

    def test_hard_cap_holds_under_adversarial_payload(self):
        """The cap is a hard ceiling: a pathological page must not exceed it, manifest included."""
        nodes = dense_results_with_open_dialog(rows=60)
        # Thousands of very long actionable names, all genuine eviction candidates.
        for i in range(300):
            nodes.append({
                "nodeId": str(2000 + i),
                "role": {"value": "gridcell"},
                "name": {"value": "x" * 400},
                "childIds": [],
            })
        nodes[1]["childIds"] = list(nodes[1]["childIds"]) + [str(2000 + i) for i in range(300)]

        tree = CDP_AXTree_Extractor().sanitize(nodes)

        assert tree.truncated is True
        assert tree.estimated_tokens <= MAX_TOKENS, (
            f"payload {tree.estimated_tokens} exceeded the hard cap of {MAX_TOKENS}"
        )

    def test_cap_holds_when_manifest_names_dropped_affordances(self):
        """The manifest's own size must not push the payload past the cap.

        Regression for a reviewer-found defect: the reserve covered a manifest whose
        DROPPED-ACTIONABLE entries were bounded per-name but not in aggregate, so a page
        that dropped *buttons* (rather than gridcells) emitted a manifest ~100 tokens
        larger than the reserve and finished 60 tokens over MAX_TOKENS.
        """
        # Tier-by-tier eviction drops every data cell before any button, and the compacted
        # tree (no content-derived cell names, no restated text CSS) fits more, so the
        # buttons alone must exceed the cap for DROPPED-ACTIONABLE entries to appear.
        for button_count in (40, 48, 60, 80):
            nodes = dense_results_with_open_dialog(rows=20)
            extra = [str(500 + i) for i in range(button_count)]
            nodes[1]["childIds"] = list(nodes[1]["childIds"]) + extra
            for i in range(button_count):
                # Long names so each DROPPED-ACTIONABLE entry is at its 60-char bound.
                nodes.append({
                    "nodeId": str(500 + i),
                    "role": {"value": "button"},
                    "name": {"value": f"row_action_{i:03d}_" + "B" * 120},
                    "childIds": [],
                })

            tree = CDP_AXTree_Extractor().sanitize(nodes)

            assert tree.truncated is True, f"buttons={button_count}: fixture must truncate"
            assert tree.dropped_actionable_count > 0, (
                f"buttons={button_count}: fixture must exercise DROPPED-ACTIONABLE entries"
            )
            assert tree.estimated_tokens <= MAX_TOKENS, (
                f"buttons={button_count}: payload {tree.estimated_tokens} exceeded "
                f"MAX_TOKENS={MAX_TOKENS} — the manifest reserve is too small"
            )

    def test_manifest_does_not_self_report_a_stale_token_count(self):
        """The notice must not state a token count that excludes the notice itself."""
        nodes = dense_results_with_open_dialog(rows=20)
        nodes[1]["childIds"] = list(nodes[1]["childIds"]) + [str(500 + i) for i in range(20)]
        for i in range(20):
            nodes.append({
                "nodeId": str(500 + i),
                "role": {"value": "button"},
                "name": {"value": f"row_action_{i:03d}_" + "B" * 120},
                "childIds": [],
            })

        tree = CDP_AXTree_Extractor().sanitize(nodes)
        notice = tree.truncation_notice or ""

        assert notice, "fixture must truncate"
        assert f"tokens~{tree.estimated_tokens}" not in notice, (
            "manifest reports a pre-manifest token count, under-reporting the payload size"
        )
        assert "dropped_nodes=" in notice and "cap=" in notice

    def test_manifest_stays_within_its_reserve(self):
        """The manifest is capped by construction, not merely asserted after the fact."""
        nodes = dense_results_with_open_dialog(rows=20)
        nodes[1]["childIds"] = list(nodes[1]["childIds"]) + [str(500 + i) for i in range(60)]
        for i in range(60):
            nodes.append({
                "nodeId": str(500 + i),
                "role": {"value": "button"},
                "name": {"value": f"row_action_{i:03d}_" + "B" * 120},
                "childIds": [],
            })

        tree = CDP_AXTree_Extractor().sanitize(nodes)

        assert tree.truncation_notice
        assert len(tree.truncation_notice) <= MANIFEST_TOKEN_RESERVE * 4, (
            f"manifest is {len(tree.truncation_notice)} chars, over its "
            f"{MANIFEST_TOKEN_RESERVE * 4}-char reserve"
        )


# ============================================================================
# Defect 5: a successful no-op is a stall, not progress
# ============================================================================

class TestVerifierNoopEscalates:
    """`success: true AND state_changed: false` on a mutating verb must reach the monitor."""

    @staticmethod
    def _noop(step_id: int, target: str) -> StepTelemetry:
        return StepTelemetry(
            step_id=step_id,
            verb="CLICK",
            target=target,
            success=True,
            state_changed=False,
            url_changed=False,
            hamming_distance=0,
            verification_is_stuck=True,
        )

    def test_two_consecutive_verifier_noops_escalate(self):
        monitor = StuckMonitor(window_size=5, stuck_threshold=0.75)
        target = "[data-testid='download-results-button']"

        first = monitor.evaluate_step(self._noop(1, target))
        assert not first.is_stuck, "a single no-op is recorded, not escalated"

        second = monitor.evaluate_step(self._noop(2, target))
        assert second.is_stuck, "two consecutive verifier no-ops must escalate"
        assert second.stuck_score >= 0.75
        assert second.evidence["verifier_noop"]["verifier_noop_streak"] == 2
        assert target in second.evidence["verifier_noop"]["targets"]

    def test_healthy_progress_is_not_flagged_as_noop(self):
        monitor = StuckMonitor(window_size=5, stuck_threshold=0.75)

        for i in range(1, 6):
            sig = monitor.evaluate_step(StepTelemetry(
                step_id=i,
                verb="CLICK",
                target=f"#tab-{i}",
                success=True,
                state_changed=True,
                hamming_distance=12,
                verification_is_stuck=False,
            ))
            assert not sig.is_stuck
            assert sig.stuck_score == 0.0

    def test_streak_breaks_when_state_advances(self):
        monitor = StuckMonitor(window_size=5, stuck_threshold=0.75)
        monitor.evaluate_step(self._noop(1, "#submit"))

        recovered = monitor.evaluate_step(StepTelemetry(
            step_id=2,
            verb="CLICK",
            target="#submit",
            success=True,
            state_changed=True,
            hamming_distance=9,
            verification_is_stuck=False,
        ))
        assert not recovered.is_stuck
        assert recovered.stuck_score == 0.0


# ============================================================================
# Defect 4: scroll must drive its resolved target
# ============================================================================

class _MockScrollLocator:
    """Locator mock exposing only the public API the executor is allowed to use."""

    def __init__(self, selector: str, result: Any = None, raises: bool = False):
        self.selector = selector
        self._result = result
        self._raises = raises
        self.evaluations: List[Any] = []

    def evaluate(self, script: str, arg: Any = None, timeout: Optional[float] = None) -> Any:
        if self._raises:
            raise RuntimeError(f"Timeout waiting for locator('{self.selector}')")
        self.evaluations.append(arg)
        return self._result


class _MockScrollPage:
    """Page mock recording whether the viewport wheel was used."""

    def __init__(self, locator: _MockScrollLocator):
        self.url = "https://metabase.local/question/2992"
        self._locator = locator
        self.wheel_calls: List[tuple] = []
        self.mouse = self

    def locator(self, selector: str) -> _MockScrollLocator:
        return self._locator

    def wheel(self, dx: int, dy: int) -> None:
        self.wheel_calls.append((dx, dy))


class TestScrollTargetsElement:
    """A virtualised container owns its overflow; the viewport wheel does not move it."""

    def test_targeted_scroll_uses_element_not_viewport(self):
        locator = _MockScrollLocator(
            "[data-testid='table-scroll-container']",
            result={
                "top_before": 0,
                "top_after": 400,
                "left_before": 0,
                "left_after": 0,
                "scroll_height": 816408,
                "client_height": 169,
            },
        )
        page = _MockScrollPage(locator)

        res = PlaywrightExecutor().execute(page, ActionPayload(
            verb=ActionVerb.SCROLL,
            target_selector="[data-testid='table-scroll-container']",
            scroll_delta=(0, 400),
        ))

        assert res.success is True
        assert res.metadata["scroll_mode"] == "element"
        assert res.metadata["scroll_applied"] is True
        assert page.wheel_calls == [], "a targeted scroll must not fall back to the viewport wheel"
        assert locator.evaluations == [[0, 400]]

    def test_delivered_noop_is_reported_not_hidden(self):
        """Already at the top: scrolling up changes nothing, and must say so."""
        locator = _MockScrollLocator(
            "#rows",
            result={
                "top_before": 0,
                "top_after": 0,
                "left_before": 0,
                "left_after": 0,
                "scroll_height": 5000,
                "client_height": 169,
            },
        )
        page = _MockScrollPage(locator)

        res = PlaywrightExecutor().execute(page, ActionPayload(
            verb=ActionVerb.SCROLL,
            target_selector="#rows",
            scroll_delta=(0, -400),
        ))

        assert res.success is True
        assert res.metadata["scroll_applied"] is False
        assert res.metadata["scroll_top_before"] == res.metadata["scroll_top_after"]

    def test_untargeted_scroll_still_uses_viewport(self):
        locator = _MockScrollLocator("#unused")
        page = _MockScrollPage(locator)

        res = PlaywrightExecutor().execute(
            page, ActionPayload(verb=ActionVerb.SCROLL, scroll_delta=(0, 300))
        )

        assert res.success is True
        assert res.metadata["scroll_mode"] == "viewport"
        assert page.wheel_calls == [(0, 300)]
        assert locator.evaluations == []

    def test_unresolvable_target_fails_loudly(self):
        locator = _MockScrollLocator("#missing", raises=True)
        page = _MockScrollPage(locator)

        res = PlaywrightExecutor().execute(page, ActionPayload(
            verb=ActionVerb.SCROLL,
            target_selector="#missing",
            scroll_delta=(0, 100),
        ))

        assert res.success is False
        assert res.error_message
        assert page.wheel_calls == []

    def test_document_fallback_is_reported_as_document_not_element(self):
        """A target with no scrollable ancestor must not be reported as an element scroll.

        Regression for a reviewer-found defect: the script fell through to
        `document.scrollingElement` but still reported `scroll_mode: "element"`, so the
        page scrolled while the caller was told the element did — the same defect class
        as the viewport-wheel bug, reached by a different path.
        """
        locator = _MockScrollLocator(
            "#plain",
            result={
                "top_before": 0,
                "top_after": 300,
                "left_before": 0,
                "left_after": 0,
                "scroll_height": 5000,
                "client_height": 800,
                "fell_back_to_document": True,
                "scrolled_node": "document",
            },
        )
        page = _MockScrollPage(locator)

        res = PlaywrightExecutor().execute(page, ActionPayload(
            verb=ActionVerb.SCROLL,
            target_selector="#plain",
            scroll_delta=(0, 300),
        ))

        assert res.success is True
        assert res.metadata["scroll_mode"] == "document"
        assert res.metadata["scroll_applied"] is True
        assert res.metadata["scrolled_node"] == "document"
        assert "scroll_fallback_reason" in res.metadata

    def test_genuine_element_scroll_reports_element_and_node(self):
        """The happy path must still be distinguishable from the document fallback."""
        locator = _MockScrollLocator(
            "#inner",
            result={
                "top_before": 0,
                "top_after": 300,
                "left_before": 0,
                "left_after": 0,
                "scroll_height": 90000,
                "client_height": 150,
                "fell_back_to_document": False,
                "scrolled_node": "#wrap",
            },
        )
        page = _MockScrollPage(locator)

        res = PlaywrightExecutor().execute(page, ActionPayload(
            verb=ActionVerb.SCROLL,
            target_selector="#inner",
            scroll_delta=(0, 300),
        ))

        assert res.metadata["scroll_mode"] == "element"
        assert res.metadata["scrolled_node"] == "#wrap"
        assert "scroll_fallback_reason" not in res.metadata


# ============================================================================
# Defect 2: the CLI must actually emit the perception payload
# ============================================================================

class TestPrintTreeEmitsPayload:
    """Printing only the header reduced the agent's whole perception channel to a summary."""

    @staticmethod
    def _tree():
        return CDP_AXTree_Extractor().sanitize(CDP_AXTree_Extractor().create_mock_complex_page())

    def test_yaml_branch_prints_node_list(self):
        tree = self._tree()
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli._print_tree(tree, "yaml")
        out = buf.getvalue()

        assert tree.yaml_linearized in out, "the linearized tree must reach stdout"
        assert "[#1]" in out, "actionable indices must be present"
        # Locators live in action_index_map; the YAML omits text-derived CSS that only
        # restates the name (the mock fixture has no id/testid attributes).
        assert all(e["css"] for e in tree.action_index_map.values()), "grounded locators must be present"

    def test_json_branch_reports_budget_fields(self):
        tree = self._tree()
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli._print_tree(tree, "json")
        payload = json.loads(buf.getvalue())

        assert payload["actionable_count"] == tree.actionable_count
        for field in ("truncated", "truncation_notice", "dropped_actionable_count", "dropped_node_count"):
            assert field in payload

    def test_empty_tree_warns_instead_of_reporting_success(self):
        empty = CDP_AXTree_Extractor().sanitize([])
        out, err = io.StringIO(), io.StringIO()

        with redirect_stdout(out), redirect_stderr(err):
            cli._print_tree(empty, "yaml", attempts=3, settle_ms=5000.0)

        assert "WARNING" in err.getvalue()
        assert "no actionable nodes" in err.getvalue()


# ============================================================================
# Defect 1: inspect must wait out SPA hydration
# ============================================================================

class _MockCdpSession:
    def __init__(self, pages: List[List[Dict[str, Any]]]):
        self._pages = pages
        self._index = 0

    def send(self, command: str, params: Any = None) -> Any:
        if command == "Accessibility.getFullAXTree":
            idx = min(self._index, len(self._pages) - 1)
            self._index += 1
            return {"nodes": self._pages[idx]}
        return {"root": None}


class _MockContext:
    def __init__(self, session: _MockCdpSession):
        self._session = session

    def new_cdp_session(self, page: Any) -> _MockCdpSession:
        return self._session


class _MockHydratingPage:
    """Page that renders nothing until the third extraction, like a hydrating SPA."""

    def __init__(self, shell: List[Dict[str, Any]], hydrated: List[Dict[str, Any]]):
        self.context = _MockContext(_MockCdpSession([shell, shell, hydrated]))
        self.settle_waits = 0
        self.networkidle_waits = 0

    def wait_for_load_state(self, state: str, timeout: Optional[float] = None) -> None:
        if state == "networkidle":
            self.networkidle_waits += 1
            raise TimeoutError("networkidle never reached (websocket-backed SPA)")

    def wait_for_timeout(self, timeout_ms: float) -> None:
        self.settle_waits += 1


class TestInspectWaitsForHydration:
    """DOMContentLoaded precedes hydration, so extracting immediately observes a shell."""

    SHELL = [{"nodeId": "1", "role": {"value": "RootWebArea"}, "name": {"value": "App"}, "childIds": []}]
    HYDRATED = [
        {"nodeId": "1", "role": {"value": "RootWebArea"}, "name": {"value": "App"}, "childIds": ["2"]},
        {"nodeId": "2", "role": {"value": "button"}, "name": {"value": "Sign in"}, "childIds": []},
    ]

    def test_retries_until_actionable_nodes_appear(self):
        page = _MockHydratingPage(self.SHELL, self.HYDRATED)

        tree, attempts = cli._settle_and_extract(page, CDP_AXTree_Extractor(), settle_ms=5000.0)

        assert tree.actionable_count > 0, "settle must wait out hydration"
        assert attempts > 1, "a shell must not be accepted as the final observation"
        assert page.networkidle_waits == 1, "network-idle wait is attempted but not required"

    def test_gives_up_at_the_budget_and_reports_what_it_saw(self):
        page = _MockHydratingPage(self.SHELL, self.SHELL)

        tree, attempts = cli._settle_and_extract(page, CDP_AXTree_Extractor(), settle_ms=0.0)

        assert tree.actionable_count == 0
        assert attempts >= 1, "the attempt count is reported even when nothing was found"

    def test_zero_budget_extracts_once_without_waiting(self):
        page = _MockHydratingPage(self.SHELL, self.HYDRATED)

        tree, attempts = cli._settle_and_extract(page, CDP_AXTree_Extractor(), settle_ms=0.0)

        assert attempts == 1
        assert page.settle_waits == 0
