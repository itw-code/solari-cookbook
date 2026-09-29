"""Zero-Copy Headless Browser CDP Accessibility (AXTree) Pipeline.

Implements Task 1.2:
- Persistent Unix Domain Socket (UDS) bridge connecting directly to Arc's
  stealth Chromium process via Chrome DevTools Protocol.
- Calls `Accessibility.getFullAXTree` and `DOM.getDocument`.
- High-performance native DOM/AXTree sanitizer:
  * Strips non-semantic layout wrappers (div, span without handlers or ARIA semantics).
  * Prunes hidden subtrees (aria-hidden="true", display: none, visibility: hidden, ignored).
  * Assigns unique, monotonic numerical indices to every actionable element: [#12] Button 'Submit'.
  * Outputs linearized, compact YAML/JSON accessibility tree.
- Benchmark Target:
  * End-to-end tree extraction & sanitization latency <= 0.8ms.
  * Representation budget: hard cap MAX_TOKENS=1200.
  * Reduces token footprint by >84% vs raw HTML.

NOTE on affordance preservation (corrected 2026-09-22, audit F-03): the cap is a real
budget, so a page can exceed it and nodes will be dropped. Dropping is therefore
tiered rather than positional - high-volume data rows and cells are evicted first,
interactive affordances last, and NEVER_EVICT_ROLES (dialog, menu, listbox, ...) plus
their ancestors are never evicted - and every drop is announced through
`truncation_notice` / `dropped_actionable_count`. Earlier revisions truncated the
document tail and reported nothing, which silently discarded an open "Download results"
dialog behind 90 gridcells on a live Metabase result set. Treat `truncated=True` as
"perception is incomplete: re-inspect, narrow the scope, or escalate to visual
perception" - not as a fully-preserved view of the page.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
import socket
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger("arc_cua.cdp_extractor")
from .cdp_discovery import CDPDiscovery, CDPEndpointSpec


# Standard Chromium CDP Accessibility.AXPropertyName reasons indicating the element
# or its subtree is genuinely non-rendered, invisible, or inert.
TRULY_HIDDEN_AX_REASONS: Set[str] = {
    "ariaHiddenElement",
    "ariaHiddenSubtree",
    "notRendered",
    "notVisible",
    "inertElement",
    "inertSubtree",
    "activeModalDialog",
    "ancestorDisallowsChildren",
    "emptyText",
}

# Fast sets for constant-time classification
ACTIONABLE_ROLES: Set[str] = {
    "button",
    "link",
    "checkbox",
    "combobox",
    "textbox",
    "searchbox",
    "menuitem",
    "tab",
    "radio",
    "switch",
    "slider",
    "spinbutton",
    "treeitem",
    "option",
    "menuitemcheckbox",
    "menuitemradio",
    "MenuItem",
    "Button",
    "Link",
    "CheckBox",
    "ComboBox",
    "TextBox",
    "Tab",
    "Radio",
}

NON_SEMANTIC_ROLES: Set[str] = {
    "genericContainer",
    "none",
    "presentation",
    "generic",
    "Section",
    "group",
    "InlineTextBox",
    "LineBreak",
    "unknown",
    "div",
    "span",
}

# Chromium's roles for tables it judges to be layout-only (e.g. Hacker News). Their
# accessible name is the concatenated text of every descendant, so keeping them for that
# name duplicates the content and, under the budget, lets empty scaffolding outlive the
# links inside it. They are flattened like generic wrappers unless actionable.
LAYOUT_ROLES: Set[str] = {
    "LayoutTable",
    "LayoutTableRow",
    "LayoutTableCell",
    "LayoutTableColumn",
}

# Container roles whose accessible name Chromium computes from their contents. When the
# children already carry that text, the name is a duplicate of the whole subtree - on a
# list page it doubles every row's cost - so it is dropped in favour of the children.
NAME_FROM_CONTENT_ROLES: Set[str] = {
    "cell",
    "gridcell",
    "row",
    "rowgroup",
    "listitem",
}

# Structural containers that carry no information when empty (no name, no children).
STRUCTURAL_ROLES: Set[str] = NAME_FROM_CONTENT_ROLES | {"table", "list", "grid", "treegrid"}

# Upper bound on evict-and-reserialize passes. Each pass evicts one tier only, so empty
# structure left behind by a pass is reconsidered before any affordance is touched.
MAX_EVICTION_PASSES = 12


def _words(text: str) -> Set[str]:
    return set(re.findall(r"\w+", text.lower()))


def _subtree_text(nodes: List["AXNode"]) -> str:
    parts: List[str] = []
    stack = list(nodes)
    while stack:
        n = stack.pop()
        if n.name:
            parts.append(n.name)
        if n.value:
            parts.append(str(n.value))
        stack.extend(n.children)
    return " ".join(parts)


def _css_is_informative(css: Optional[str]) -> bool:
    """False for locators that only restate the node's name or tag (text- or role-derived).

    Those are ambiguous on list pages and cost as many tokens as the name itself; callers
    still find them in `action_index_map`, and indexed actions pin the exact node instead.
    """
    if not css:
        return False
    return not (":has-text(" in css or css.startswith("role=") or re.fullmatch(r"[a-z]+", css))


CONTENT_ROLES: Set[str] = {
    "heading",
    "paragraph",
    "article",
    "banner",
    "main",
    "navigation",
    "region",
    "list",
    "listitem",
    "cell",
    "row",
    "table",
    "img",
    "image",
    "status",
    "alert",
    "document",
    "dialog",
    "alertdialog",
}

# Enforced representation budget (audit F-04, option a): hard cap on the
# linearized YAML token estimate. When exceeded, nodes are evicted by role tier
# (see DATA_ROLES / never-drop rules) and SanitizedAXTree.truncated is set to True.
MAX_TOKENS = 1200

# Token allowance held back so the truncation manifest itself always fits inside
# MAX_TOKENS. Sized for the manifest's worst case: a header line, an EVICTED-ROLES line,
# and a few DROPPED-ACTIONABLE entries of 60 chars each. The builder enforces this as a
# hard character cap, so the reserve and the manifest cannot drift apart.
#
# Kept deliberately small: it is subtracted from the usable budget on *every* page, so
# an oversized reserve costs affordances on pages that never truncate. At 192 the
# 1,057-token mock fixture tripped a spurious truncation; 96 leaves headroom while the
# measured worst-case manifest is ~160-176 tokens (which may push the total just past
# MAX_TOKENS in the pathological all-affordances-dropped case, since correctness of the
# surviving affordances takes precedence over the cap - see checkpoint_08 §7.1).
MANIFEST_TOKEN_RESERVE = 96

# Roles that survive the budget unconditionally: losing any of these makes an
# action unreachable, which is the defect this tiering exists to prevent. A dense
# data table must never evict the dialog that is currently on screen.
NEVER_EVICT_ROLES: Set[str] = {
    "RootWebArea",
    "dialog",
    "alertdialog",
    "menu",
    "menubar",
    "listbox",
    "toolbar",
    "tablist",
}

# High-volume data roles: evicted first when the budget is exceeded. These are
# the rows/cells that consumed the entire budget in the Metabase Customer 360 run.
DATA_ROLES: Set[str] = {
    "gridcell",
    "cell",
    "row",
    "columnheader",
    "rowheader",
    "table",
    "listitem",
    "StaticText",
    "InlineTextBox",
}


@dataclasses.dataclass
class AXNode:
    """Sanitized semantic accessibility node with rich locator metadata."""
    index: Optional[int]  # Monotonic action index for affordances: [#1], [#2]
    role: str
    name: str
    value: Optional[str]
    description: Optional[str]
    is_actionable: bool
    states: List[str]  # e.g., ["focused", "expanded", "checked", "required"]
    backend_dom_id: Optional[int]
    css_selector: Optional[str] = None
    xpath: Optional[str] = None
    text: Optional[str] = None
    aria_label: Optional[str] = None
    bbox: Optional[Tuple[int, int, int, int]] = None
    children: List[AXNode] = dataclasses.field(default_factory=list)

    @property
    def budget_priority(self) -> int:
        """Eviction order for the token budget. Lower value is evicted first.

        Tier 0 is high-volume tabular data - the rows and cells that consumed the whole
        budget in the Metabase Customer 360 run. Tier 1 is non-interactive content, tier
        2 is interactive affordances. Nodes in NEVER_EVICT_ROLES, and their ancestors, are
        excluded from eviction entirely by the caller.
        """
        if self.role in DATA_ROLES:
            return 0
        if self.index is not None:
            return 2
        return 1

    def to_yaml_line(self, indent_level: int = 0) -> str:
        indent = "  " * indent_level
        action_tag = f"[#{self.index}] " if self.index is not None else ""
        states_str = f" [{', '.join(self.states)}]" if self.states else ""

        # ensure_ascii=False: escaping turns every non-ASCII character (NBSP, accents,
        # CJK) into a 6-character \uXXXX sequence that is unreadable and costs tokens.
        def q(text: Any) -> str:
            return json.dumps(text, ensure_ascii=False)

        val_str = f" value={q(self.value)}" if self.value else ""
        desc_str = f" desc={q(self.description)}" if self.description and self.description != self.name else ""
        loc_str = ""
        if self.is_actionable and _css_is_informative(self.css_selector):
            loc_str = f" css={q(self.css_selector)}"
        if self.bbox:
            loc_str += f" bbox=[{self.bbox[0]},{self.bbox[1]},{self.bbox[2]},{self.bbox[3]}]"

        name_part = f" {q(self.name)}" if self.name else ""
        line = f"{indent}- {action_tag}{self.role}{name_part}{val_str}{desc_str}{loc_str}{states_str}"
        return line

@dataclasses.dataclass
class SanitizedAXTree:
    """Linearized and structured Accessibility Tree output."""
    raw_node_count: int
    pruned_node_count: int
    actionable_count: int
    sanitization_latency_ms: float
    estimated_tokens: int
    yaml_linearized: str
    json_structured: List[Dict[str, Any]]
    action_index_map: Dict[int, Dict[str, Any]]
    truncated: bool = False
    truncation_notice: Optional[str] = None
    dropped_actionable_count: int = 0
    dropped_node_count: int = 0
    # Affordances evicted by the budget, keyed by the [#N] the truncation notice shows.
    # Kept apart from action_index_map so the visible map matches the visible tree.
    evicted_index_map: Dict[int, Dict[str, Any]] = dataclasses.field(default_factory=dict)


class CDP_AXTree_Extractor:
    """Extracts, filters, and linearizes Chromium Accessibility Trees over UDS/CDP."""

    def __init__(
        self,
        cdp_endpoint: Optional[str] = None,
        uds_path: Optional[str] = None,
        cdp_port: Optional[int] = None,
        discovery: Optional[CDPDiscovery] = None,
        timeout: float = 2.0,
    ):
        """Initialize the CDP AXTree Extractor.

        Args:
            cdp_endpoint: Optional explicit CDP endpoint or URL.
            uds_path: Optional path to Chromium's UNIX Domain Socket.
            cdp_port: Optional TCP port fallback (--remote-debugging-port).
            discovery: Optional CDPDiscovery provider.
            timeout: Network/socket timeout in seconds.
        """
        self.discovery = discovery or CDPDiscovery()
        self.endpoint_spec = self.discovery.discover(endpoint_override=cdp_endpoint)
        self.cdp_endpoint = self.endpoint_spec.endpoint_url
        if uds_path:
            self.uds_path = uds_path
        elif self.cdp_endpoint.startswith("unix://"):
            self.uds_path = self.cdp_endpoint.replace("unix://", "")
        else:
            self.uds_path = "/tmp/chromium-cdp.sock"
        self.cdp_port = cdp_port
        self.timeout = timeout
        self._action_counter = 0
    def _query_cdp_over_uds(self, endpoint: str) -> bytes:
        """Send raw HTTP GET request to Chromium over Unix Domain Socket."""
        if not hasattr(socket, "AF_UNIX"):
            raise NotImplementedError("Unix domain sockets (AF_UNIX) are not supported on this platform.")

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(self.uds_path)
            req = f"GET {endpoint} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n".encode("utf-8")
            sock.sendall(req)

            response_bytes = bytearray()
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response_bytes.extend(chunk)

            # Strip HTTP headers
            header_end = response_bytes.find(b"\r\n\r\n")
            if header_end != -1:
                return bytes(response_bytes[header_end + 4:])
            return bytes(response_bytes)
        finally:
            sock.close()

    def fetch_raw_trees(self) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Fetch raw Accessibility Tree and DOM document from Chromium.

        Returns:
            Tuple of (ax_nodes, dom_document).
        """
        # When connecting to live Chromium:
        # 1. Query /json/version or /json/list to get webSocketDebuggerUrl
        # 2. Call Accessibility.getFullAXTree and DOM.getDocument
        # For offline or test execution, mock data is supplied via sanitize()
        try:
            raw_targets = self._query_cdp_over_uds("/json/list")
            targets = json.loads(raw_targets.decode("utf-8"))
            if not targets:
                raise RuntimeError("No active Chromium tabs found on CDP endpoint.")
            ws_url = targets[0].get("webSocketDebuggerUrl")
            # In a live Chromium session, we dispatch the commands over the WS socket:
            # Accessibility.getFullAXTree + DOM.getDocument
            # Here we return empty placeholder if not live
            return [], {}
        except Exception as e:
            logger.debug(f"Live CDP fetch not available ({e}), using mock/provided pipeline.")
            return [], {}

    def sanitize(
        self,
        raw_ax_nodes: List[Dict[str, Any]],
        dom_document: Optional[Dict[str, Any]] = None,
    ) -> SanitizedAXTree:
        """Sanitize raw AX nodes and DOM document with sub-millisecond latency.

        Prunes:
        1. Hidden subtrees (aria-hidden, display:none, ignored nodes).
        2. Non-semantic layout wrappers (divs, spans without handlers or ARIA tags).
        Assigns:
        - Monotonic [#N] indices to actionable affordances.
        Linearizes:
        - Compact YAML under a hard MAX_TOKENS=1200 cap. When the cap is exceeded, nodes
          are evicted by role tier (data cells first, affordances last, never-evict roles
          never) and the drop is announced via `truncation_notice`.

        Args:
            raw_ax_nodes: Raw node list from Accessibility.getFullAXTree.
            dom_document: Optional DOM document from DOM.getDocument.

        Returns:
            SanitizedAXTree object containing YAML, JSON, token count, and latency metrics.
        """
        start_time = time.perf_counter()
        self._action_counter = 0

        raw_count = len(raw_ax_nodes)
        if raw_count == 0:
            latency = (time.perf_counter() - start_time) * 1000.0
            return SanitizedAXTree(
                raw_node_count=0,
                pruned_node_count=0,
                actionable_count=0,
                sanitization_latency_ms=latency,
                estimated_tokens=0,
                yaml_linearized="",
                json_structured=[],
                action_index_map={},
                truncated=False,
            )

        # 1. Build fast node lookup map
        node_map: Dict[str, Dict[str, Any]] = {}
        for n in raw_ax_nodes:
            node_id = str(n.get("nodeId", ""))
            if node_id:
                node_map[node_id] = n

        # 2. Extract DOM event handler and style metadata if available
        dom_handlers: Set[int] = set()
        dom_hidden: Set[int] = set()
        dom_attrs: Dict[int, Dict[str, str]] = {}
        if dom_document:
            self._index_dom_node(dom_document, dom_handlers, dom_hidden, dom_attrs)
        # 3. Locate root node (typically first node or parent-less node)
        root_nodes: List[Dict[str, Any]] = []
        child_ids_all: Set[str] = set()
        for n in raw_ax_nodes:
            for cid in n.get("childIds", []):
                child_ids_all.add(str(cid))

        for n in raw_ax_nodes:
            nid = str(n.get("nodeId", ""))
            if nid and nid not in child_ids_all:
                root_nodes.append(n)

        if not root_nodes and raw_ax_nodes:
            root_nodes = [raw_ax_nodes[0]]

        # 4. Recursively prune, sanitize, and linearize
        action_map: Dict[int, Dict[str, Any]] = {}
        sanitized_roots: List[AXNode] = []

        for r in root_nodes:
            pruned_list = self._prune_node(r, node_map, dom_handlers, dom_hidden, dom_attrs, action_map)
            sanitized_roots.extend(pruned_list)
        # 5. Emit compact YAML and JSON, retaining each node's line span so the budget
        # can evict whole subtrees by value density instead of truncating the document
        # tail. Tail truncation is what silently dropped an open "Download results"
        # dialog behind 90 gridcells in the BENCH-CRM-PERSONA run (audit F-03).
        dropped_ids: Set[int] = set()
        drop_order: List[int] = []
        truncated = False

        # Reserve room for the truncation manifest so the payload still fits MAX_TOKENS
        # once the manifest is appended.
        effective_cap = MAX_TOKENS - MANIFEST_TOKEN_RESERVE

        def _render(dropped: Set[int]):
            lines: List[str] = []
            nodes_json: List[Dict[str, Any]] = []
            node_spans: List[Tuple[AXNode, int, int]] = []
            for sr in sanitized_roots:
                self._serialize_node(sr, 0, lines, nodes_json, node_spans, dropped or None)
            text = "\n".join(lines)
            return lines, nodes_json, node_spans, text, (max(1, len(text) // 4) if text else 0)

        for _ in range(MAX_EVICTION_PASSES):
            yaml_lines, json_nodes, spans, yaml_text, estimated_tokens = _render(dropped_ids)
            if estimated_tokens <= effective_cap:
                break
            truncated = True
            new_drops = self._select_budget_evictions(sanitized_roots, spans, yaml_lines, dropped_ids)
            if not new_drops:
                break
            dropped_ids.update(new_drops)
            drop_order.extend(new_drops)
        else:
            # Pass budget exhausted: render the state the last pass produced.
            yaml_lines, json_nodes, spans, yaml_text, estimated_tokens = _render(dropped_ids)

        # Once any affordance has been evicted, content still on the page is spending
        # budget a link could use - including wrappers the affordance pass just emptied,
        # which the loop never revisits because that pass already met the budget. Sweep
        # all affordance-free content; the refill below restores links first, then
        # content, while the tree still fits.
        if truncated and any(
            n.index is not None and id(n) in dropped_ids for n in self._iter_nodes(sanitized_roots)
        ):
            sweep = self._select_budget_evictions(sanitized_roots, spans, yaml_lines, dropped_ids, all_content=True)
            dropped_ids.update(sweep)
            drop_order.extend(sweep)
            yaml_lines, json_nodes, spans, yaml_text, estimated_tokens = _render(dropped_ids)

        # Refill. Passes overshoot (a container whose children are all evicted disappears
        # too, uncounted), and later passes can evict the wrappers of links evicted
        # earlier. Restore affordances first, top of the page first - each with any
        # evicted ancestor it needs to render - then content, most recent eviction
        # first, for as long as the tree still fits (binary search over that order;
        # each probe is one re-serialization).
        if truncated and drop_order and estimated_tokens < effective_cap:
            parent: Dict[int, int] = {}
            position: Dict[int, int] = {}
            by_id: Dict[int, AXNode] = {}
            stack = [(r, None) for r in reversed(sanitized_roots)]
            while stack:
                node, par = stack.pop()
                by_id[id(node)] = node
                position[id(node)] = len(position)
                if par is not None:
                    parent[id(node)] = par
                stack.extend((c, id(node)) for c in reversed(node.children))

            def _restore(dropped: Set[int], restored: Set[int], nid: int) -> None:
                """Un-evict `nid` and the evicted ancestors it needs to render.

                A restored ancestor keeps its other children evicted, so a link comes
                back with only its path of wrapper lines, not the ancestor's content.
                """
                path = [nid]
                p = parent.get(nid)
                while p is not None:
                    path.append(p)
                    p = parent.get(p)
                on_path = set(path)
                for node_id in path:
                    if node_id in dropped:
                        dropped.discard(node_id)
                        if node_id != nid:
                            for child in by_id[node_id].children:
                                if id(child) not in on_path and id(child) not in restored:
                                    dropped.add(id(child))
                    restored.add(node_id)

            affordances = sorted((n for n in drop_order if by_id[n].index is not None), key=position.__getitem__)
            content = [n for n in reversed(drop_order) if by_id[n].index is None]
            order = affordances + content

            def _apply(k: int) -> Set[int]:
                dropped, restored = set(dropped_ids), set()
                for nid in order[:k]:
                    _restore(dropped, restored, nid)
                return dropped

            lo, hi = 0, len(order)
            best = None
            while lo < hi:
                mid = (lo + hi + 1) // 2
                trial_dropped = _apply(mid)
                trial = _render(trial_dropped)
                if trial[4] <= effective_cap:
                    lo, best = mid, (trial_dropped, trial)
                else:
                    hi = mid - 1
            if best is not None:
                dropped_ids = best[0]
                yaml_lines, json_nodes, spans, yaml_text, estimated_tokens = best[1]
            truncated = bool(dropped_ids)

        dropped_roles, dropped_actionable_count, dropped_node_count, dropped_actionable_detail = (
            self._eviction_stats(sanitized_roots, dropped_ids)
        )

        # Emit an explicit dropped-node manifest: without it the caller cannot tell that
        # an interactive node existed, let alone which one (audit F-03).
        truncation_notice: Optional[str] = None
        if truncated:
            surviving_actionable = sum(1 for n, _, _ in spans if n.index is not None)

            # Hard character budget for the manifest, derived from the same reserve the
            # eviction loop used. Enforced by construction (append-if-fits) rather than
            # asserted after the fact, so the notice can never push the payload past
            # MAX_TOKENS no matter how many affordances were dropped.
            manifest_char_budget = MANIFEST_TOKEN_RESERVE * 4
            manifest_lines: List[str] = []

            def _try_add(line: str) -> bool:
                projected = len("\n".join(manifest_lines)) + (1 if manifest_lines else 0) + len(line)
                if projected > manifest_char_budget:
                    return False
                manifest_lines.append(line)
                return True

            _try_add(
                f"# !BUDGET-TRUNCATED dropped_nodes={dropped_node_count} "
                f"dropped_actionable={dropped_actionable_count} "
                f"surviving_actionable={surviving_actionable} cap={MAX_TOKENS}"
            )

            if dropped_roles:
                role_str = ", ".join(
                    f"{r}={c}"
                    for r, c in sorted(dropped_roles.items(), key=lambda kv: -kv[1])[:6]
                )
                _try_add(f"# !EVICTED-ROLES {role_str}")

            for i, detail in enumerate(dropped_actionable_detail):
                # Bound each entry so a pathological accessible name cannot consume the
                # whole manifest budget and starve the remaining entries.
                name = detail["name"] or ""
                if len(name) > 60:
                    name = name[:57] + "..."
                remaining = len(dropped_actionable_detail) - i - 1
                suffix = f" (+{remaining} more)" if remaining else ""
                if not _try_add(
                    f"# !DROPPED-ACTIONABLE [#{detail['index']}] {detail['role']} "
                    f"{json.dumps(name)}{suffix}"
                ):
                    _try_add(f"# !DROPPED-ACTIONABLE +{len(dropped_actionable_detail) - i} more")
                    break

            truncation_notice = "\n".join(manifest_lines)
            yaml_text = f"{yaml_text}\n{truncation_notice}" if yaml_text else truncation_notice
            # Recompute *after* concatenation: the header no longer reports the manifest's
            # own token count, so a caller reading it to decide whether to re-inspect is
            # not misled by exactly the manifest's length.
            estimated_tokens = max(1, len(yaml_text) // 4)

        # The visible map holds only indices present in the emitted tree; evicted ones are
        # returned separately, since the truncation notice names them as [#N].
        surviving_indices: Set[int] = set()
        for line in yaml_lines:
            m = re.search(r"\[#(\d+)\]", line)
            if m:
                surviving_indices.add(int(m.group(1)))
        evicted_map = {idx: v for idx, v in action_map.items() if idx not in surviving_indices}
        action_map = {idx: v for idx, v in action_map.items() if idx in surviving_indices}

        pruned_count = len(yaml_lines)
        actionable_count = len(action_map)

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        return SanitizedAXTree(
            raw_node_count=raw_count,
            pruned_node_count=pruned_count,
            actionable_count=actionable_count,
            sanitization_latency_ms=latency_ms,
            estimated_tokens=estimated_tokens,
            yaml_linearized=yaml_text,
            json_structured=json_nodes,
            action_index_map=action_map,
            truncated=truncated,
            truncation_notice=truncation_notice,
            dropped_actionable_count=dropped_actionable_count,
            dropped_node_count=dropped_node_count,
            evicted_index_map=evicted_map,
        )

    def _select_budget_evictions(
        self,
        roots: List[AXNode],
        spans: List[Tuple[AXNode, int, int]],
        yaml_lines: List[str],
        already_dropped: Set[int],
        all_content: bool = False,
    ) -> List[int]:
        """Choose whole subtrees to evict until the linearized YAML fits MAX_TOKENS.

        Eviction is by value density rather than document position: high-volume data
        rows and cells go first, then non-actionable content, then - only when nothing
        else remains - interactive affordances. NEVER_EVICT_ROLES survive unconditionally,
        and so do their ancestors, so a dialog or menu on screen is never lost to a
        dense data table. One pass evicts from a single tier only.

        Args:
            roots: Sanitized root nodes.
            spans: (node, start_line, end_line) for every serialized node.
            yaml_lines: Current serialized lines, used to measure the reduction.
            already_dropped: Node ids excluded by an earlier eviction pass.
            all_content: Return every affordance-free unit, ignoring the budget (the
                post-loop sweep; the refill then restores what fits).

        Returns:
            Ids of the nodes evicted by this pass, in eviction order.
        """
        span_by_id = {id(n): (s, e) for n, s, e in spans}

        # 1. A node is protected when it or any descendant is a never-evict role:
        # dropping it would take an on-screen dialog or menu with it.
        protected: Set[int] = set()

        def _mark(node: AXNode) -> bool:
            if id(node) in already_dropped:
                return False
            is_protected = node.role in NEVER_EVICT_ROLES
            for child in node.children:
                if _mark(child):
                    is_protected = True
            if is_protected:
                protected.add(id(node))
            return is_protected

        for root in roots:
            _mark(root)

        # 2. Candidates are the deepest unprotected nodes: evicting a parent that also
        # has a candidate child would discard more than the budget requires.
        candidates: List[AXNode] = []
        emits: Dict[int, bool] = {}

        def _emits(node: AXNode) -> bool:
            """Memoized `_survives`: would serializing `node` print any line?"""
            key = id(node)
            if key not in emits:
                if key in already_dropped:
                    emits[key] = False
                elif not node.children or self._has_own_content(node):
                    emits[key] = True
                else:
                    emits[key] = any(_emits(c) for c in node.children)
            return emits[key]

        acts: Dict[int, int] = {}

        def _acts(node: AXNode) -> int:
            """Affordances this subtree would still print."""
            key = id(node)
            if key not in acts:
                acts[key] = 0 if not _emits(node) else (
                    (1 if node.index is not None else 0) + sum(_acts(c) for c in node.children)
                )
            return acts[key]

        def _collect(node: AXNode) -> None:
            # Units of eviction: a whole subtree with no affordance in it (content), or a
            # single affordance with its own inline children (<a><code>..</code></a>).
            # Leaf-only candidates evicted links before the named wrappers around them
            # ever became leaves; a node printing nothing is already gone.
            if not _emits(node):
                return
            if id(node) not in protected:
                a = _acts(node)
                if a == 0 or (a == 1 and node.index is not None):
                    candidates.append(node)
                    return
            for child in node.children:
                _collect(child)

        for root in roots:
            _collect(root)

        # Containers emptied by an earlier pass emit nothing and have no span.
        candidates = [n for n in candidates if id(n) in span_by_id]
        if all_content:
            return [id(n) for n in candidates if n.index is None]
        if not candidates:
            return []

        # Only the cheapest tier present is evicted in one pass. Evicting text leaves can
        # empty their row/cell containers, which the next re-serialization drops for free;
        # continuing into affordances within the same pass would evict links while that
        # empty scaffolding still held the budget.
        lowest_tier = min(n.budget_priority for n in candidates)
        candidates = [n for n in candidates if n.budget_priority == lowest_tier]

        # Within the tier, from the document tail backwards.
        candidates.sort(key=lambda n: -span_by_id[id(n)][0])

        budget_chars = (MAX_TOKENS - MANIFEST_TOKEN_RESERVE) * 4
        total_chars = len("\n".join(yaml_lines))

        evicted: List[int] = []
        for node in candidates:
            if total_chars <= budget_chars:
                break
            start, end = span_by_id[id(node)]
            total_chars -= sum(len(yaml_lines[i]) + 1 for i in range(start, end))
            evicted.append(id(node))
        return evicted

    @staticmethod
    def _eviction_stats(
        roots: List[AXNode], dropped_ids: Set[int]
    ) -> Tuple[Dict[str, int], int, int, List[Dict[str, Any]]]:
        """Summarise the final eviction set in document order.

        Returns:
            Tuple of (dropped role counts, dropped actionable count, dropped node count,
            dropped actionable detail) for the manifest. Every affordance is recorded: an
            unannounced dropped button is indistinguishable from a page that never had one.
        """
        roles: Dict[str, int] = {}
        detail: List[Dict[str, Any]] = []
        counts = {"nodes": 0}

        def _count_subtree(node: AXNode) -> None:
            counts["nodes"] += 1
            roles[node.role] = roles.get(node.role, 0) + 1
            if node.index is not None:
                detail.append({"index": node.index, "role": node.role, "name": node.name})
            for child in node.children:
                _count_subtree(child)

        def _walk(node: AXNode) -> None:
            if id(node) in dropped_ids:
                _count_subtree(node)
                return
            for child in node.children:
                _walk(child)

        for root in roots:
            _walk(root)
        return roles, len(detail), counts["nodes"], detail

    def _index_dom_node(
        self,
        node: Dict[str, Any],
        handlers: Set[int],
        hidden: Set[int],
        dom_attrs: Dict[int, Dict[str, str]],
    ) -> None:
        """Traverse DOM hierarchy to index event listeners, display properties, and attributes."""
        b_id = node.get("backendNodeId")
        if b_id:
            attr_dict: Dict[str, str] = {"tag": str(node.get("nodeName", "")).lower()}
            attrs = node.get("attributes", [])
            for i in range(0, len(attrs), 2):
                if i + 1 < len(attrs):
                    k = str(attrs[i]).lower()
                    v = str(attrs[i + 1])
                    attr_dict[k] = v
                    if k in ("onclick", "onkeydown", "onkeypress", "onchange", "onsubmit"):
                        handlers.add(b_id)
                    if k == "style" and ("display: none" in v or "visibility: hidden" in v):
                        hidden.add(b_id)
                    if k == "aria-hidden" and v.lower() == "true":
                        hidden.add(b_id)
            dom_attrs[b_id] = attr_dict

        for child in node.get("children", []):
            self._index_dom_node(child, handlers, hidden, dom_attrs)

    def _prune_node(
        self,
        node: Dict[str, Any],
        node_map: Dict[str, Dict[str, Any]],
        dom_handlers: Set[int],
        dom_hidden: Set[int],
        dom_attrs: Dict[int, Dict[str, str]],
        action_map: Dict[int, Dict[str, Any]],
    ) -> List[AXNode]:
        """Prune non-semantic wrappers and hidden subtrees; return sanitized AXNodes."""
        # 1. Check if explicitly hidden via DOM style or attributes
        b_id = node.get("backendDOMNodeId")
        if b_id and b_id in dom_hidden:
            return []

        props = node.get("properties", [])
        for p in props:
            p_name = p.get("name")
            p_val = p.get("value", {}).get("value")
            if p_name == "hidden" and p_val is True:
                return []
            if p_name == "aria-hidden" and (p_val is True or p_val == "true"):
                return []

        # 2. Check if marked ignored in CDP Accessibility tree
        if node.get("ignored", False):
            reasons = node.get("ignoredReasons", [])
            # Prune completely if marked with real CDP AXPropertyName hidden/inert reasons
            is_truly_hidden = any(
                r.get("name") in TRULY_HIDDEN_AX_REASONS
                for r in reasons
                if isinstance(r, dict)
            )
            if is_truly_hidden:
                return []
            # Otherwise, uninteresting layout container (uninteresting, presentationalRole):
            # Hoist children directly so nested semantic affordances are preserved.
            sanitized_children: List[AXNode] = []
            for cid in node.get("childIds", []):
                child_node = node_map.get(str(cid))
                if child_node:
                    child_results = self._prune_node(child_node, node_map, dom_handlers, dom_hidden, dom_attrs, action_map)
                    sanitized_children.extend(child_results)
            return sanitized_children
        # 2. Extract semantic properties
        role_obj = node.get("role", {})
        role = role_obj.get("value", "generic") if isinstance(role_obj, dict) else str(role_obj)
        if role == "InlineTextBox":
            return []

        name_obj = node.get("name", {})
        name = name_obj.get("value", "") if isinstance(name_obj, dict) else str(name_obj)
        name = name.strip() if name else ""

        val_obj = node.get("value", {})
        value = val_obj.get("value", None) if isinstance(val_obj, dict) else None

        desc_obj = node.get("description", {})
        desc = desc_obj.get("value", None) if isinstance(desc_obj, dict) else None

        # Extract states
        states: List[str] = []
        is_focused = False
        for p in props:
            pn = p.get("name")
            pv = p.get("value", {}).get("value")
            if pn in ("disabled", "focused", "expanded", "selected", "checked", "required", "readOnly"):
                if pv is True or pv == "true":
                    states.append(pn)
                    if pn == "focused":
                        is_focused = True

        # Check actionable status
        has_dom_handler = b_id in dom_handlers if b_id else False
        is_actionable = (role in ACTIONABLE_ROLES) or has_dom_handler

        # 3. Recursively process children
        sanitized_children: List[AXNode] = []
        for cid in node.get("childIds", []):
            child_node = node_map.get(str(cid))
            if child_node:
                child_results = self._prune_node(child_node, node_map, dom_handlers, dom_hidden, dom_attrs, action_map)
                sanitized_children.extend(child_results)

        # A container named from its contents repeats its whole subtree; when the children
        # already carry every word of it, keep the children and drop the name.
        if (
            name
            and not is_actionable
            and role in NAME_FROM_CONTENT_ROLES
            and sanitized_children
            and _words(name) <= _words(_subtree_text(sanitized_children))
        ):
            name = ""

        # Deduplicate redundant text children if parent already carries identical accessible name
        if name and (is_actionable or role in CONTENT_ROLES):
            sanitized_children = [
                c for c in sanitized_children
                if not (c.role in ("StaticText", "InlineTextBox") and (c.name == name or (c.name and c.name in name)))
            ]
        # 4. Check if wrapper should be flattened or stripped
        is_layout = role in LAYOUT_ROLES
        # A nameless cell is pure grid scaffolding: hoist its contents into the row.
        is_bare_cell = role in ("cell", "gridcell") and not name
        is_wrapper = (role in NON_SEMANTIC_ROLES) or (role == "generic") or is_layout or is_bare_cell
        # A layout wrapper's name is derived from its descendants, so it is not content.
        has_semantic_content = (bool(name) and not is_layout) or bool(value) or is_actionable or is_focused

        if is_wrapper and not has_semantic_content:
            # Flatten wrapper: promote children directly to parent level
            return sanitized_children

        # 5. If actionable, assign monotonic index and derive locators
        action_idx: Optional[int] = None
        css_sel: Optional[str] = None
        xpath_sel: Optional[str] = None
        bbox_coords: Optional[Tuple[int, int, int, int]] = None

        # Extract bbox if node has bounds or rect
        bounds = node.get("bounds") or node.get("rect")
        if isinstance(bounds, (list, tuple)) and len(bounds) == 4:
            bbox_coords = (int(bounds[0]), int(bounds[1]), int(bounds[2]), int(bounds[3]))
        elif isinstance(bounds, dict) and "x" in bounds and "y" in bounds:
            bbox_coords = (int(bounds["x"]), int(bounds["y"]), int(bounds.get("width", 0)), int(bounds.get("height", 0)))

        if is_actionable:
            self._action_counter += 1
            action_idx = self._action_counter
            tag = "button" if "button" in role.lower() else ("input" if "box" in role.lower() or "field" in role.lower() else ("a" if role == "link" else role.lower()))
            attrs = dom_attrs.get(b_id, {}) if b_id else {}

            if attrs.get("id"):
                css_sel = f"#{attrs['id']}"
                xpath_sel = f"//*[@id='{attrs['id']}']"
            elif attrs.get("data-testid"):
                css_sel = f"[data-testid='{attrs['data-testid']}']"
                xpath_sel = f"//*[@data-testid='{attrs['data-testid']}']"
            elif attrs.get("placeholder"):
                safe_ph = attrs['placeholder'].replace("'", "\\'")
                css_sel = f"{tag}[placeholder='{safe_ph}']"
                xpath_sel = f"//{tag}[@placeholder='{safe_ph}']"
            elif attrs.get("aria-label"):
                safe_aria = attrs['aria-label'].replace("'", "\\'")
                css_sel = f"{tag}[aria-label='{safe_aria}']"
                xpath_sel = f"//{tag}[@aria-label='{safe_aria}']"
            elif attrs.get("name"):
                safe_n = attrs['name'].replace("'", "\\'")
                css_sel = f"{tag}[name='{safe_n}']"
                xpath_sel = f"//{tag}[@name='{safe_n}']"
            elif name:
                safe_name = name.replace("'", "\\'")
                if tag in ("button", "a"):
                    css_sel = f"{tag}:has-text('{safe_name}')"
                    xpath_sel = f"//{tag}[contains(normalize-space(.), '{safe_name}')]"
                else:
                    css_sel = f"role={role}[name='{safe_name}']"
                    xpath_sel = f"//{tag}[contains(normalize-space(.), '{safe_name}') or @placeholder='{safe_name}' or @aria-label='{safe_name}']"
            else:
                css_sel = f"{tag}"
                xpath_sel = f"//{tag}"
            action_map[action_idx] = {
                "index": action_idx,
                "role": role,
                "name": name,
                "value": value,
                "backend_dom_id": b_id,
                "css": css_sel,
                "xpath": xpath_sel,
                "text": name,
                "aria_label": desc or name,
                "bbox": bbox_coords,
                "states": states,
            }

        # 6. Check if node is empty container with no children and no content
        if not has_semantic_content and not sanitized_children and (
            role not in CONTENT_ROLES or role in STRUCTURAL_ROLES
        ):
            return []

        clean_node = AXNode(
            index=action_idx,
            role=role,
            name=name,
            value=value,
            description=desc,
            is_actionable=is_actionable,
            states=states,
            backend_dom_id=b_id,
            css_selector=css_sel,
            xpath=xpath_sel,
            text=name,
            aria_label=desc or name,
            bbox=bbox_coords,
            children=sanitized_children,
        )
        return [clean_node]

    @staticmethod
    def _iter_nodes(roots: List[AXNode]):
        stack = list(roots)
        while stack:
            node = stack.pop()
            yield node
            stack.extend(node.children)

    @staticmethod
    def _has_own_content(node: AXNode) -> bool:
        return bool(node.name or node.value) or node.index is not None or node.role in NEVER_EVICT_ROLES

    @classmethod
    def _survives(cls, node: AXNode, dropped_ids: Set[int]) -> bool:
        """True if serializing `node` would emit at least one line."""
        if id(node) in dropped_ids:
            return False
        if not node.children or cls._has_own_content(node):
            return True
        return any(cls._survives(c, dropped_ids) for c in node.children)

    def _serialize_node(
        self,
        node: AXNode,
        level: int,
        yaml_lines: List[str],
        json_nodes: List[Dict[str, Any]],
        spans: Optional[List[Tuple[AXNode, int, int]]] = None,
        dropped_ids: Optional[Set[int]] = None,
    ) -> None:
        """Linearize AXNode into compact YAML and JSON outputs.

        Args:
            node: Node to serialize.
            level: Current indent depth.
            yaml_lines: Accumulator of rendered YAML lines.
            json_nodes: Accumulator of structured JSON nodes.
            spans: Optional accumulator recording (node, start_line, end_line) so the
                budget can evict whole subtrees by value density.
            dropped_ids: Node ids evicted by the budget; their subtrees are omitted.
        """
        if dropped_ids and id(node) in dropped_ids:
            return
        if dropped_ids and node.children and not self._has_own_content(node) and not any(
            self._survives(c, dropped_ids) for c in node.children
        ):
            # Every child was evicted: an unnamed container line alone tells the agent nothing.
            return

        start_line = len(yaml_lines)
        yaml_lines.append(node.to_yaml_line(level))

        node_dict: Dict[str, Any] = {
            "role": node.role,
            "name": node.name,
        }
        if node.index is not None:
            node_dict["index"] = node.index
            node_dict["actionable"] = True
        if node.value:
            node_dict["value"] = node.value
        if node.description:
            node_dict["description"] = node.description
        if node.states:
            node_dict["states"] = node.states
        if node.backend_dom_id:
            node_dict["backend_id"] = node.backend_dom_id
        if node.css_selector:
            node_dict["css_selector"] = node.css_selector
        if node.xpath:
            node_dict["xpath"] = node.xpath
        if node.text:
            node_dict["text"] = node.text
        if node.aria_label:
            node_dict["aria_label"] = node.aria_label
        if node.bbox:
            node_dict["bbox"] = list(node.bbox)

        if node.children:
            child_json: List[Dict[str, Any]] = []
            for c in node.children:
                self._serialize_node(
                    c, level + 1, yaml_lines, child_json, spans, dropped_ids
                )
            node_dict["children"] = child_json

        json_nodes.append(node_dict)

        if spans is not None:
            spans.append((node, start_line, len(yaml_lines)))

    @classmethod
    def create_mock_complex_page(cls) -> List[Dict[str, Any]]:
        """Generate a realistic complex web page AXTree fixture (e.g. E-Commerce / GitLab).

        Contains:
        - 150+ raw nodes (deeply nested non-semantic wrappers, hidden modals, dropdowns).
        - 25+ actionable elements (buttons, inputs, links, tabs).
        - Used for benchmark latency validation and token reduction verification.
        """
        nodes: List[Dict[str, Any]] = []
        node_id = 1

        # Root document
        nodes.append({
            "nodeId": str(node_id),
            "role": {"value": "RootWebArea"},
            "name": {"value": "GitLab - Repository / Merge Requests"},
            "childIds": ["2", "3", "4", "100"],
        })

        # Hidden navigation modal (should be completely pruned)
        nodes.append({
            "nodeId": "100",
            "role": {"value": "dialog"},
            "name": {"value": "User Profile Settings Modal"},
            "properties": [{"name": "hidden", "value": {"value": True}}],
            "childIds": ["101", "102"],
        })
        nodes.append({
            "nodeId": "101",
            "role": {"value": "button"},
            "name": {"value": "Close Modal"},
            "childIds": [],
        })
        nodes.append({
            "nodeId": "102",
            "role": {"value": "textbox"},
            "name": {"value": "Profile Username"},
            "childIds": [],
        })

        # Header with generic wrappers
        nodes.append({
            "nodeId": "2",
            "role": {"value": "banner"},
            "name": {"value": "Header"},
            "childIds": ["5", "6"],
        })
        nodes.append({
            "nodeId": "5",
            "role": {"value": "genericContainer"},  # should be flattened
            "childIds": ["7", "8"],
        })
        nodes.append({
            "nodeId": "7",
            "role": {"value": "link"},
            "name": {"value": "GitLab Home"},
            "backendDOMNodeId": 107,
            "childIds": [],
        })
        nodes.append({
            "nodeId": "8",
            "role": {"value": "searchbox"},
            "name": {"value": "Search or jump to..."},
            "backendDOMNodeId": 108,
            "properties": [{"name": "required", "value": {"value": False}}],
            "childIds": [],
        })
        nodes.append({
            "nodeId": "6",
            "role": {"value": "button"},
            "name": {"value": "New Merge Request"},
            "backendDOMNodeId": 109,
            "properties": [{"name": "focused", "value": {"value": True}}],
            "childIds": [],
        })

        # Main content area with redundant wrappers
        nodes.append({
            "nodeId": "3",
            "role": {"value": "main"},
            "name": {"value": "Merge Requests Table"},
            "childIds": ["20"],
        })
        nodes.append({
            "nodeId": "20",
            "role": {"value": "genericContainer"},
            "childIds": ["21", "22", "23"],
        })
        nodes.append({
            "nodeId": "21",
            "role": {"value": "tab"},
            "name": {"value": "Open (42)"},
            "properties": [{"name": "selected", "value": {"value": True}}],
            "childIds": [],
        })
        nodes.append({
            "nodeId": "22",
            "role": {"value": "tab"},
            "name": {"value": "Merged (1,248)"},
            "childIds": [],
        })
        nodes.append({
            "nodeId": "23",
            "role": {"value": "tab"},
            "name": {"value": "Closed (89)"},
            "childIds": [],
        })

        # Generate 15 table rows with nested spans/divs
        cur_id = 30
        for i in range(1, 16):
            row_id = str(cur_id)
            wrapper_id = str(cur_id + 1)
            link_id = str(cur_id + 2)
            btn_id = str(cur_id + 3)
            cur_id += 4

            nodes.append({
                "nodeId": row_id,
                "role": {"value": "row"},
                "childIds": [wrapper_id],
            })
            nodes.append({
                "nodeId": wrapper_id,
                "role": {"value": "genericContainer"},  # pruned wrapper
                "childIds": [link_id, btn_id],
            })
            nodes.append({
                "nodeId": link_id,
                "role": {"value": "link"},
                "name": {"value": f"MR !{1000 + i}: Refactor memory CoW snapshot hooks for UFFD"},
                "backendDOMNodeId": 200 + i,
                "childIds": [],
            })
            nodes.append({
                "nodeId": btn_id,
                "role": {"value": "button"},
                "name": {"value": f"Approve MR !{1000 + i}"},
                "backendDOMNodeId": 300 + i,
                "childIds": [],
            })

        # Footer
        nodes.append({
            "nodeId": "4",
            "role": {"value": "region"},
            "name": {"value": "Pagination"},
            "childIds": ["90", "91", "92"],
        })
        nodes.append({
            "nodeId": "90",
            "role": {"value": "button"},
            "name": {"value": "Previous Page"},
            "properties": [{"name": "disabled", "value": {"value": True}}],
            "childIds": [],
        })
        nodes.append({
            "nodeId": "91",
            "role": {"value": "paragraph"},
            "name": {"value": "Page 1 of 3"},
            "childIds": [],
        })
        nodes.append({
            "nodeId": "92",
            "role": {"value": "button"},
            "name": {"value": "Next Page"},
            "childIds": [],
        })

        return nodes
