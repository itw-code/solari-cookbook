"""arc_screenshot: viewport capture with [#N] marks, and coordinate clicks from it."""

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
    except Exception as e:
        s.shutdown()
        pytest.skip(f"LIVE_BROWSER_SKIPPED: {e}")
    yield s
    s.shutdown()


def jpeg_size(data: bytes) -> tuple[int, int]:
    """(width, height) from a JPEG's SOF marker, no imaging library needed."""
    i = 2
    while i < len(data):
        marker, length = data[i + 1], int.from_bytes(data[i + 2:i + 4], "big")
        if marker in (0xC0, 0xC2):
            return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
        i += 2 + length
    raise AssertionError("no SOF marker")


def test_screenshot_before_open_is_a_clear_error():
    with pytest.raises(BrowserSessionError, match="arc_open"):
        BrowserSession().screenshot()


def test_plain_screenshot_is_viewport_jpeg_in_css_pixels(session):
    shot = session.screenshot(marks=False)
    assert shot["image"][:2] == b"\xff\xd8"
    assert shot["format"] == "jpeg"
    assert jpeg_size(shot["image"]) == (shot["viewport"]["width"], shot["viewport"]["height"])
    assert shot["marked"] == 0


def test_marks_label_visible_affordances_and_leave_page_clean(session):
    session.inspect(settle_ms=1000)
    shot = session.screenshot(marks=True)
    assert shot["marked"] >= 3
    assert all(m["index"] in {**session._index_map, **session._evicted_map} for m in shot["marks"])
    # The overlay is removed after capture.
    assert session.page.evaluate("document.querySelectorAll('[data-arc-overlay]').length") == 0


def test_marks_without_prior_inspect_runs_one(session):
    shot = session.screenshot(marks=True)
    assert shot["marked"] > 0
    assert session._index_map, "screenshot with marks must leave a usable index map"


def test_mark_box_supports_coordinate_click(session):
    session.inspect(settle_ms=1000)
    shot = session.screenshot(marks=True)
    submit_idx = next(i for i, e in session._index_map.items() if e.get("name") == "Submit Form")
    box = next(m for m in shot["marks"] if m["index"] == submit_idx)
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    result = session.act("click", target=f"coords:{x},{y}")
    assert result["success"] is True
    assert result["state_changed"] is True
