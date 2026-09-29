"""MCP server: tool surface and an end-to-end open → inspect → act → close over real Chromium."""

import json
import pathlib

import pytest

pytest.importorskip("mcp")

from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

from arc_cua.mcp_server import build_server  # noqa: E402

FIXTURE_URL = (pathlib.Path(__file__).parent / "fixtures" / "eval_site.html").resolve().as_uri()
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def text_of(result) -> str:
    return "".join(c.text for c in result.content if getattr(c, "type", None) == "text")


async def test_tool_surface():
    server, _ = build_server()
    names = {t.name for t in await server.list_tools()}
    assert names == {"arc_open", "arc_inspect", "arc_act", "arc_screenshot", "arc_close"}


async def test_act_before_open_returns_tool_error():
    server, worker = build_server()
    try:
        with pytest.raises(ToolError, match="arc_open"):
            await server.call_tool("arc_act", {"action": "click", "index": 1})
    finally:
        await worker.shutdown()


async def test_solari_without_key_returns_tool_error(monkeypatch):
    monkeypatch.delenv("SOLARI_API_KEY", raising=False)
    server, worker = build_server()
    try:
        with pytest.raises(ToolError, match="SOLARI_API_KEY"):
            await server.call_tool("arc_open", {"backend": "solari"})
    finally:
        await worker.shutdown()


async def test_end_to_end_local():
    pytest.importorskip("playwright.sync_api")
    server, worker = build_server()
    try:
        try:
            opened = json.loads(text_of(await server.call_tool("arc_open", {"url": FIXTURE_URL})))
        except ToolError as e:
            pytest.skip(f"LIVE_BROWSER_SKIPPED: {e}")
        assert opened["backend"] == "local"

        tree_text = text_of(await server.call_tool("arc_inspect", {"settle_ms": 2000}))
        assert "Submit Form" in tree_text
        line = next(l for l in tree_text.splitlines() if "Submit Form" in l and "[#" in l)
        index = int(line.split("[#", 1)[1].split("]", 1)[0])

        report, _, after = text_of(await server.call_tool("arc_act", {"action": "click", "index": index})).partition("\n\n")
        acted = json.loads(report)
        assert acted["success"] is True and acted["state_changed"] is True
        # The post-action tree comes back with the result, and its indices are live without arc_inspect.
        assert after.startswith("URL: ") and "# AXTree" in after
        line = next(l for l in after.splitlines() if "Submit Form" in l and "[#" in l)
        again = json.loads(text_of(await server.call_tool(
            "arc_act", {"action": "click", "index": int(line.split("[#", 1)[1].split("]", 1)[0]), "observe": False})))
        assert again["success"] is True and "tree" not in again

        shot = await server.call_tool("arc_screenshot", {"marks": True})
        kinds = [c.type for c in shot.content]
        assert kinds == ["image", "text"]
        assert shot.content[0].mime_type == "image/jpeg"
        assert json.loads(shot.content[1].text)["marked"] > 0

        closed = json.loads(text_of(await server.call_tool("arc_close", {})))
        assert closed["closed"] is True
    finally:
        await worker.shutdown()
