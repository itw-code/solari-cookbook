"""Perception on layout-table pages (Hacker News shape) and index precision.

Regression for the 2026-09-26 live run where the budgeted tree kept 1 of ~227 actionable
nodes on news.ycombinator.com: LayoutTable* wrappers carried whole-row text as their
names and survived leaf-first eviction as scaffolding.
"""

import pathlib

import pytest

from arc_cua.browser_session import BrowserSession
from arc_cua.cdp_extractor import CDP_AXTree_Extractor

FIXTURE_URL = (pathlib.Path(__file__).parent / "fixtures" / "layout_table_site.html").resolve().as_uri()


def ax(node_id, role, name="", children=(), **extra):
    node = {"nodeId": str(node_id), "role": {"value": role}, "childIds": [str(c) for c in children]}
    if name:
        node["name"] = {"value": name}
    node.update(extra)
    return node


# --- offline extractor units -------------------------------------------------------------------

def test_layout_table_wrappers_are_transparent():
    nodes = [
        ax(1, "RootWebArea", "News", [2]),
        ax(2, "LayoutTable", "", [3]),
        ax(3, "LayoutTableRow", "1. Story one (example.com)", [4, 5]),
        ax(4, "LayoutTableCell", "1.", [6]),
        ax(5, "LayoutTableCell", "Story one (example.com)", [7, 8]),
        ax(6, "StaticText", "1."),
        ax(7, "link", "Story one", backendDOMNodeId=70),
        ax(8, "StaticText", "(example.com)"),
    ]
    tree = CDP_AXTree_Extractor().sanitize(nodes)
    assert "LayoutTable" not in tree.yaml_linearized
    assert '[#1] link "Story one"' in tree.yaml_linearized
    assert '"1."' in tree.yaml_linearized and '"(example.com)"' in tree.yaml_linearized


def test_actionable_layout_cell_is_kept():
    nodes = [
        ax(1, "RootWebArea", "News", [2]),
        ax(2, "LayoutTableCell", "Clickable cell", [], backendDOMNodeId=20),
    ]
    dom = {"backendNodeId": 20, "nodeName": "TD", "attributes": ["onclick", "go()"], "children": []}
    tree = CDP_AXTree_Extractor().sanitize(nodes, dom)
    assert tree.actionable_count == 1
    assert "LayoutTableCell" in tree.yaml_linearized


def test_evicted_indices_remain_addressable():
    links = [ax(100 + i, "link", f"Link number {i} " + "x" * 40, backendDOMNodeId=1000 + i) for i in range(200)]
    nodes = [ax(1, "RootWebArea", "Big", [100 + i for i in range(200)])] + links
    tree = CDP_AXTree_Extractor().sanitize(nodes)
    assert tree.truncated and tree.dropped_actionable_count > 0
    visible = set(tree.action_index_map)
    evicted = set(tree.evicted_index_map)
    assert evicted and not (visible & evicted)
    assert visible | evicted == set(range(1, 201))


def test_names_are_not_json_escaped_and_desc_is_not_repeated():
    nodes = [
        ax(1, "RootWebArea", "Café", [2, 3]),
        ax(2, "link", "96 comments", backendDOMNodeId=20),
        ax(3, "generic", "Run example", [], description={"value": "Run example"}),
    ]
    tree = CDP_AXTree_Extractor().sanitize(nodes)
    assert '"Café"' in tree.yaml_linearized
    assert '"96 comments"' in tree.yaml_linearized
    assert "\\u00" not in tree.yaml_linearized
    assert "desc=" not in tree.yaml_linearized


def test_links_inside_named_wrappers_outrank_the_wrappers():
    """MDN shape: generic "Run example..." > link "Play". When links must go, the wrappers
    they leave behind must not keep the budget that the refill could give back to links."""
    kids = []
    nodes = [ax(1, "RootWebArea", "Docs", [])]
    for i in range(120):
        wrap, link = 100 + i, 1000 + i
        kids.append(wrap)
        nodes += [
            ax(wrap, "generic", f"Run example number {i} in the playground (opens in new tab)", [link]),
            ax(link, "link", f"Play {i}", backendDOMNodeId=link),
        ]
    nodes[0]["childIds"] = [str(k) for k in kids]
    tree = CDP_AXTree_Extractor().sanitize(nodes)
    assert tree.truncated and tree.estimated_tokens <= 1200
    wrappers_without_link = [
        l for l in tree.yaml_linearized.splitlines() if l.strip().startswith('- generic "Run example')
    ]
    # Every wrapper line kept must be carrying its link.
    assert len(wrappers_without_link) <= tree.actionable_count
    assert tree.actionable_count >= 25


def test_cap_holds_when_links_wrap_unnamed_inline_text():
    """MDN shape: link > code > StaticText. Once the text is evicted the unnamed <code>
    prints nothing; it must not shield its link from eviction (was 8,753 tokens on MDN)."""
    nodes = [ax(1, "RootWebArea", "Docs", [10 + i for i in range(300)])]
    for i in range(300):
        link, code, text = 10 + i, 1000 + i, 5000 + i
        nodes += [
            ax(link, "link", f"HTMLInputElement.property_number_{i}", [code], backendDOMNodeId=link),
            ax(code, "code", "", [text]),
            ax(text, "StaticText", f"property_number_{i} with a long enough label"),
        ]
    tree = CDP_AXTree_Extractor().sanitize(nodes)
    assert tree.truncated
    assert tree.estimated_tokens <= 1200, tree.estimated_tokens
    assert tree.actionable_count > 20


# --- live Chromium -----------------------------------------------------------------------------

@pytest.fixture
def session():
    pytest.importorskip("playwright.sync_api")
    s = BrowserSession()
    try:
        s.open(url=FIXTURE_URL)
    except Exception as e:
        s.shutdown()
        pytest.skip(f"LIVE_BROWSER_SKIPPED: {e}")
    yield s
    s.shutdown()


def find_index(session, tree, name, nth=0):
    """Index of the nth actionable named `name`, visible or evicted."""
    entries = sorted(
        (int(i), e) for i, e in {**session._evicted_map, **tree["action_index_map"]}.items()
        if e.get("name") == name
    )
    return entries[nth][0]


def test_layout_page_keeps_most_affordances(session):
    tree = session.inspect(settle_ms=1000)
    # 40 rows x (vote, story, hide, comments) + 8 header links = 168 affordances.
    assert tree["actionable_count"] + tree["dropped_actionable_count"] >= 160
    assert tree["actionable_count"] >= 40, tree["text"][:600]
    assert "LayoutTable" not in tree["text"]


def test_duplicate_text_links_click_the_exact_row(session):
    tree = session.inspect(settle_ms=1000)
    idx = find_index(session, tree, "hide", nth=2)  # third "hide" link -> row 3
    result = session.act("click", index=idx)
    assert result["success"] is True, result
    assert session.page.text_content("#last-action") == "hide 3"


def test_query_finds_evicted_affordances(session):
    full = session.inspect(settle_ms=1000)
    assert "Story number 38" not in full["text"] or full["truncated"]
    found = session.inspect(settle_ms=500, query="story number 38")
    line = next(l for l in found["text"].splitlines() if "Story number 38" in l)
    idx = int(line.split("[#", 1)[1].split("]", 1)[0])
    result = session.act("click", index=idx)
    assert result["success"] is True
    assert session.page.text_content("#last-action") == "story 38"


def test_evicted_index_listed_in_notice_is_actionable(session):
    tree = session.inspect(settle_ms=1000)
    assert tree["truncated"], "fixture should exceed the budget"
    evicted = sorted(session._evicted_map)
    assert evicted
    result = session.act("click", index=evicted[-1])
    assert result["success"] is True, result
    assert session.page.text_content("#last-action") != "none"
