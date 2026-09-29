"""Live contract check against the real Solari API (costs ~$0.01 per run on the free plan).

Opt-in: runs only when SOLARI_LIVE_TESTS=1 and SOLARI_API_KEY are both set.
"""

import os

import pytest

from arc_cua.cloud.solari_driver import SessionStatus, SolariCloudDriver

pytestmark = pytest.mark.skipif(
    os.getenv("SOLARI_LIVE_TESTS") != "1" or not os.getenv("SOLARI_API_KEY"),
    reason="SOLARI_LIVE_SKIPPED: set SOLARI_LIVE_TESTS=1 and SOLARI_API_KEY to run",
)


def test_live_create_attach_release():
    playwright = pytest.importorskip("playwright.sync_api")

    with SolariCloudDriver() as driver:
        session = driver.provision_browser()
        assert session.cdp_endpoint.startswith("wss://")
        assert session.expires_at

        with playwright.sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(session.cdp_endpoint, timeout=30000)
            try:
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                page = context.pages[0] if context.pages else context.new_page()
                page.goto("https://example.com", timeout=30000)
                assert page.title() == "Example Domain"
            finally:
                browser.close()

        assert driver.terminate(session.session_id) is True
        assert session.status == SessionStatus.TERMINATED
