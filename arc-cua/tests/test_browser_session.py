"""BrowserSession: one long-lived browser behind open / inspect / act / close.

Runs against real headless Chromium on the local eval fixture; skips if Chromium is unavailable.
"""

import pathlib

import pytest

from arc_cua.browser_session import BrowserSession, BrowserSessionError

FIXTURE_URL = (pathlib.Path(__file__).parent / "fixtures" / "eval_site.html").resolve().as_uri()


@pytest.fixture
def session():
    pytest.importorskip("playwright.sync_api")
    s = BrowserSession()
    try:
        s.open(url=FIXTURE_URL)
    except Exception as e:  # Chromium binary missing
        s.shutdown()
        pytest.skip(f"LIVE_BROWSER_SKIPPED: {e}")
    yield s
    # shutdown, not close: a still-running sync Playwright blocks the next test from starting one.
    s.shutdown()


def index_of(tree: dict, name: str) -> int:
    for idx, entry in tree["action_index_map"].items():
        if entry.get("name") == name:
            return int(idx)
    raise AssertionError(f"{name!r} not in action map: {[e.get('name') for e in tree['action_index_map'].values()]}")


def test_act_before_open_is_a_clear_error():
    with pytest.raises(BrowserSessionError, match="arc_open|open"):
        BrowserSession().act("click", index=1)


def test_open_reports_backend_and_page(session):
    info = session.status()
    assert info["open"] is True
    assert info["backend"] == "local"
    assert info["url"] == FIXTURE_URL
    assert info["title"]


def test_inspect_returns_indexed_tree(session):
    tree = session.inspect(settle_ms=2000)
    assert tree["actionable_count"] > 0
    assert "Submit Form" in tree["text"]
    assert "[#" in tree["text"]
    index_of(tree, "Submit Form")


def test_act_by_index_changes_state(session):
    tree = session.inspect(settle_ms=2000)
    result = session.act("click", index=index_of(tree, "Submit Form"))
    assert result["success"] is True
    assert result["state_changed"] is True
    assert result["stall_suspected"] is False


def test_type_then_read_back(session):
    tree = session.inspect(settle_ms=2000)
    result = session.act("fill", target="#user-name", value="arc-agent")
    assert result["success"] is True
    assert session.page.input_value("#user-name") == "arc-agent"


def test_repeated_noop_is_flagged_as_stall(session):
    session.inspect(settle_ms=2000)
    # Clicking a static heading "succeeds" but changes nothing, every time.
    results = [session.act("click", target="#suite-title") for _ in range(3)]
    assert [r["noop_streak"] for r in results] == [1, 2, 3]
    assert results[-1]["stall_suspected"] is True


def test_state_persists_across_calls_without_reconnect(session):
    session.act("fill", target="#user-email", value="a@b.co")
    browser_before = session.browser
    session.inspect(settle_ms=500)
    assert session.browser is browser_before
    assert session.page.input_value("#user-email") == "a@b.co"


def test_unknown_index_is_a_clear_error(session):
    session.inspect(settle_ms=2000)
    with pytest.raises(BrowserSessionError, match="9999"):
        session.act("click", index=9999)


def test_index_without_inspect_is_a_clear_error(session):
    with pytest.raises(BrowserSessionError, match="inspect"):
        session.act("click", index=1)


def test_unsupported_action_rejected_before_dispatch(session):
    with pytest.raises(BrowserSessionError, match="Unknown action 'hover'"):
        session.act("hover", target="#suite-title")


def test_dangerous_navigation_rejected(session):
    with pytest.raises(BrowserSessionError, match="scheme"):
        session.act("goto", value="javascript:alert(1)")


def test_close_is_idempotent(session):
    assert session.close()["closed"] is True
    assert session.close()["closed"] is False
    assert session.status()["open"] is False


def test_observe_returns_post_action_tree_with_live_indices(session):
    tree = session.inspect(settle_ms=2000)
    result = session.act("click", index=index_of(tree, "Submit Form"), observe=True)
    assert result["tree"].startswith("URL: ") and "# AXTree" in result["tree"]
    # The returned tree's indices are now the current map: act on one without inspecting.
    line = next(l for l in result["tree"].splitlines() if "Submit Form" in l and "[#" in l)
    again = session.act("click", index=int(line.split("[#", 1)[1].split("]", 1)[0]))
    assert again["success"] is True and "tree" not in again


SOFT_NAV_URL = (pathlib.Path(__file__).parent / "fixtures" / "soft_nav_site.html").resolve().as_uri()


def test_observe_waits_for_client_routed_link_navigation(session):
    """GitHub shape: the link pushes its URL after a fetch, so the tree taken right after
    the click is the old page. The returned tree must show where the click led."""
    session.act("goto", value=SOFT_NAV_URL)
    tree = session.inspect(settle_ms=1000)
    result = session.act("click", index=index_of(tree, "Issues 159"), observe=True)
    assert result["url_changed"] is True and result["url"].endswith("?tab=issues")
    assert "Open issues" in result["tree"] and "New issue" in result["tree"]
