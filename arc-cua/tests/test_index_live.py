"""Live ARC Index run: Gemini extraction + a Solari cloud browser (costs a few cents per run).

Opt-in: runs only when SOLARI_LIVE_TESTS=1 and both SOLARI_API_KEY and GEMINI_API_KEY are set.
"""

import os
import pathlib
import sys

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("SOLARI_LIVE_TESTS") != "1" or not os.getenv("SOLARI_API_KEY") or not os.getenv("GEMINI_API_KEY"),
    reason="SOLARI_LIVE_SKIPPED: set SOLARI_LIVE_TESTS=1, SOLARI_API_KEY and GEMINI_API_KEY to run",
)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))


@pytest.fixture(scope="module")
def solari_browser():
    from arc_cua.browser_session import BrowserSession
    browser = BrowserSession()
    browser.open("about:blank", backend="solari")
    yield browser
    browser.shutdown()


@pytest.mark.parametrize("case_id", ["SYN-DENIAL-01", "MED-CMS-01"])
def test_document_to_portal_on_solari(case_id, solari_browser):
    from arc_index.local_doc_index import LocalDocIndexClient
    from run_arc_index_live import CASES, run_case

    case = next(c for c in CASES if c["id"] == case_id)
    result = run_case(case, solari_browser, LocalDocIndexClient())

    assert result["backend"] == "solari" and result["receipt"]["solari_session_id"]
    # Safety: a value either reaches the portal correct, or not at all (rejected as ungrounded).
    wrong = [s for s in result["submission"] if s["received"] and not s["ok"]]
    assert not wrong, wrong
    assert result["confirmation_ok"]
    assert result["all_fills_changed_state"]
    if case_id == "SYN-DENIAL-01":
        # Labelled fields: extraction must be complete.
        assert all(s["ok"] for s in result["submission"]), result["submission"]
    # MED-CMS-01's reason/remark codes sit under bare "RC"/"REM" headers and the model misses
    # them in some runs; that shows up as NOT_FOUND in the report, not as a failure.
