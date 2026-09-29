"""Reflex policy: reply parsing, and the one-call-per-action loop driven by a scripted model."""

import pathlib

import pytest

from arc_cua.browser_session import BrowserSession
from arc_cua.reflex_policy import parse_action, run_episode

SOFT_NAV_URL = (pathlib.Path(__file__).parent / "fixtures" / "soft_nav_site.html").resolve().as_uri()


def test_parse_action_tolerates_fences_and_prose():
    assert parse_action('```json\n{"op":"click","index":"19"}\n```') == {"op": "click", "index": 19}
    assert parse_action('Sure: {"op":"fill","index":3,"value":"x","enter":true}')["enter"] is True


@pytest.mark.parametrize("reply", ["", "click 19", '{"op":"hover","index":1}'])
def test_parse_action_rejects_non_actions(reply):
    with pytest.raises(ValueError):
        parse_action(reply)


class ScriptedModel:
    """Stands in for ChatClient: returns canned replies and records what it was shown."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def complete(self, system, user):
        self.prompts.append(user)
        return {"text": self.replies.pop(0), "input_tokens": len(user) // 4, "output_tokens": 9}


@pytest.fixture
def session():
    pytest.importorskip("playwright.sync_api")
    s = BrowserSession()
    try:
        s.open(url="about:blank")
    except Exception as e:
        s.shutdown()
        pytest.skip(f"LIVE_BROWSER_SKIPPED: {e}")
    yield s
    s.shutdown()


def test_episode_is_one_model_call_per_action(session):
    model = ScriptedModel(['{"op":"click","index":1}', '{"op":"done"}'])
    ep = run_episode(session, model, "Open the Issues tab.", SOFT_NAV_URL, settle_ms=3000)
    assert ep.error is None and ep.finished
    assert [s.op for s in ep.steps] == ["click", "done"]
    assert ep.final_url.endswith("?tab=issues") and "Open issues" in ep.final_tree
    # The second prompt shows the new page and names what was clicked.
    assert "Open issues" in model.prompts[1]
    assert 'link "Issues 159"' in model.prompts[1] and "page changed" in model.prompts[1]


def test_invalid_reply_is_retried_not_fatal(session):
    model = ScriptedModel(["I think I should click", '{"op":"fail","value":"stuck"}'])
    ep = run_episode(session, model, "Anything.", SOFT_NAV_URL, settle_ms=1000)
    assert ep.error is None and not ep.finished
    assert ep.failed_reason == "stuck"
    assert "invalid reply" in model.prompts[1]
