"""Browser tools for the traditional-agent baseline on the denial-appeal task, over HTTP.

Holds one Solari MCP session (`npx @solarisdk/mcp`, as in benchmark_gemini_solari_mcp.py) and
serves its page tools on localhost, so any agent (the Gemini loop in benchmark_appeal_baseline.py,
or a Claude Code subagent calling scripts/appeal_tool.py) drives the same tools on the same
kind of browser. Each episode gets its own Solari browser with the stand-in portal written into
it (the portal from run_arc_index_live.py). Every tool call is logged with its argument and
result sizes and latency, which is what the token estimates for subagent runs are built from.

  POST /start  {"ep": "...", "case": "SYN-DENIAL-01"}   -> new browser, portal loaded
  POST /tool   {"ep": "...", "name": "read_page", "args": {...}}  -> tool result text
  POST /finish {"ep": "..."}   -> {"received": {...form data...}, "code": "..."}, browser closed
  GET  /tools  -> the tool schemas (sessionId removed), for function calling

Run: python scripts/appeal_tool_server.py [--port 8765] [--log artifacts/benchmarks/appeal_tools.jsonl]
Needs SOLARI_API_KEY (inherited by the MCP server; never written to a file).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

sys.path.insert(0, str(Path(__file__).parent))
from benchmark_gemini_solari_mcp import clean_schema, create_browser, text_of  # noqa: E402
from run_arc_index_live import portal_html  # noqa: E402

# The model gets these (navigate is left out: the portal is already open and has no URL).
TOOLS = ("solari_browser_read_page", "solari_browser_click", "solari_browser_type",
         "solari_browser_key", "solari_browser_evaluate")
MAX_RESULT_CHARS = 40000

APPEAL_LABELS = {"claim_id": "Insurance Claim ID", "patient_name": "Patient Name",
                 "date_of_service": "Date of Service", "billed_amount": "Billed Amount",
                 "denial_code": "Denial Reason Code", "cpt_code": "CPT Procedure Code",
                 "notes": "Appeal Justification"}
CASES = {
    "SYN-DENIAL-01": "synthetic_denial_letter.pdf",
    "SYN-DENIAL-TWO_DENIED": "synthetic_denial_letter_two_denied.pdf",
}


def portal_for(case_id: str) -> str:
    return portal_html({"title": "Provider Appeals Portal", "labels": APPEAL_LABELS})


class Hub:
    def __init__(self, log_path: Path):
        self.loop = asyncio.new_event_loop()
        self.sess: ClientSession = None  # type: ignore[assignment]
        self.tools: list = []
        self.eps: Dict[str, str] = {}      # episode -> Solari sessionId
        self.lock = asyncio.Lock()
        self.log = log_path.open("a", encoding="utf-8")
        self.ready = threading.Event()

    def run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._main())

    async def _main(self) -> None:
        npx = shutil.which("npx") or shutil.which("npx.cmd")
        params = StdioServerParameters(command=npx, args=["-y", "@solarisdk/mcp"], env=dict(os.environ))
        with tempfile.TemporaryFile("w+", encoding="utf-8") as errlog:
            async with stdio_client(params, errlog=errlog) as (r, w), ClientSession(r, w) as sess:
                await sess.initialize()
                self.sess = sess
                listed = {t.name: t for t in (await sess.list_tools()).tools}
                self.tools = [{"type": "function", "function": {
                    "name": n.removeprefix("solari_browser_"), "description": (listed[n].description or "")[:1000],
                    "parameters": clean_schema(listed[n].input_schema)}} for n in TOOLS if n in listed]
                self.ready.set()
                await asyncio.Event().wait()   # serve until the process exits

    def call(self, coro) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout=180)

    def write(self, rec: Dict[str, Any]) -> None:
        self.log.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.log.flush()

    async def start(self, ep: str, case: str) -> Dict[str, Any]:
        t = time.perf_counter()
        async with self.lock:          # one create at a time; tool calls on browsers run in parallel
            sid = await create_browser(self.sess)
        self.eps[ep] = sid
        html = portal_for(case)
        await self.sess.call_tool("solari_browser_evaluate", {"sessionId": sid, "expression":
            f"document.open(); document.write({json.dumps(html)}); document.close(); 'ok'"})
        self.write({"ep": ep, "event": "start", "case": case, "seconds": round(time.perf_counter() - t, 2),
                    "ts": time.time()})
        return {"ok": True}

    async def tool(self, ep: str, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        full = "solari_browser_" + name.removeprefix("solari_browser_")
        t = time.perf_counter()
        if full not in TOOLS:
            out, err = f"ERROR: unknown tool {name}", True
        else:
            res = await self.sess.call_tool(full, {**args, "sessionId": self.eps[ep]})
            out, err = text_of(res), bool(res.is_error)
            out = ("ERROR: " if err else "") + out
        if len(out) > MAX_RESULT_CHARS:
            out = out[:MAX_RESULT_CHARS] + f"\n[... truncated by harness at {MAX_RESULT_CHARS} chars]"
        secs = time.perf_counter() - t
        self.write({"ep": ep, "event": "tool", "name": name, "args": args,
                    "args_chars": len(json.dumps(args)), "result_chars": len(out),
                    "seconds": round(secs, 3), "error": err, "ts": time.time()})
        return {"result": out, "seconds": round(secs, 3)}

    async def finish(self, ep: str) -> Dict[str, Any]:
        sid = self.eps.pop(ep)
        out = text_of(await self.sess.call_tool("solari_browser_evaluate", {"sessionId": sid, "expression":
            "JSON.stringify({echo: (document.getElementById('echo')||{}).textContent || '',"
            " code: (document.getElementById('code')||{}).textContent || '',"
            " submitted: (document.getElementById('ok')||{style:{}}).style.display === 'block'})"}))
        try:
            await self.sess.call_tool("solari_browser_close", {"sessionId": sid})
        except Exception:
            pass
        m = re.search(r"\{.*\}", out, re.S)
        page = {}
        if m:
            try:
                page = json.loads(m.group(0))
            except ValueError:
                page = {}
        received = {}
        if page.get("echo"):
            try:
                received = json.loads(page["echo"])
            except ValueError:
                pass
        rec = {"ep": ep, "event": "finish", "submitted": bool(page.get("submitted")), "received": received,
               "code": page.get("code") or None, "ts": time.time()}
        self.write(rec)
        return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--log", default="artifacts/benchmarks/appeal_tools.jsonl")
    args = ap.parse_args()
    if not os.getenv("SOLARI_API_KEY"):
        sys.exit("SOLARI_API_KEY must be set.")
    hub = Hub(Path(args.log))
    threading.Thread(target=hub.run, daemon=True).start()
    if not hub.ready.wait(120):
        sys.exit("Solari MCP server did not start")

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def reply(self, code: int, obj: Any) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self.reply(200, hub.tools if self.path == "/tools" else {"eps": list(hub.eps)})

        def do_POST(self):
            try:
                req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                if self.path == "/start":
                    self.reply(200, hub.call(hub.start(req["ep"], req["case"])))
                elif self.path == "/tool":
                    self.reply(200, hub.call(hub.tool(req["ep"], req["name"], req.get("args") or {})))
                elif self.path == "/finish":
                    self.reply(200, hub.call(hub.finish(req["ep"])))
                else:
                    self.reply(404, {"error": "unknown path"})
            except Exception as e:
                self.reply(500, {"error": f"{type(e).__name__}: {e}"[:500]})

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), H)
    print(f"appeal tool server on http://127.0.0.1:{args.port} ({len(hub.tools)} tools), log {args.log}", flush=True)
    try:
        srv.serve_forever()
    finally:
        for sid in list(hub.eps.values()):
            try:
                hub.call(hub.sess.call_tool("solari_browser_close", {"sessionId": sid}))
            except Exception:
                pass


if __name__ == "__main__":
    main()
