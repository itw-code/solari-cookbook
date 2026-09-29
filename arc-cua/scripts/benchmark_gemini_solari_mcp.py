"""Same model, two harnesses: Gemini driving a Solari browser through Solari's own MCP.

The counterpart of `benchmark_reflex_policy.py --backend solari` with the model held fixed,
so any difference comes from the harness, not the model. This side is a standard
tool-calling agent: the model gets Solari's page tools (navigate, read_page, click, type,
key, evaluate) as functions, keeps the whole conversation, and works until it answers DONE.

The browser is created once and kept warm across tasks, as on the ARC side, so task time
excludes browser start-up. The harness injects the Solari sessionId into every call; the
model provider never sees it. The first navigation is timed but made by the harness (ARC's
run_episode also opens the start page itself). Success is judged from the page's URL and
innerText after the model stops, read outside the timed window.

Usage (both keys from the environment):
  python scripts/benchmark_gemini_solari_mcp.py [--model gemini-3.8-flash] [--repeat 3]
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

sys.path.insert(0, str(Path(__file__).parent))
from benchmark_reflex_policy import TASKS, judge  # noqa: E402

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
SOLARI_HOURLY_USD = 0.15  # docs/SOLARI_API.md
PRICES = {"gemini-3.8-flash": (0.75, 3.75), "gemini-3.5-flash-lite": (0.30, 2.50)}  # USD per 1M in / out
PAGE_TOOLS = ("solari_browser_navigate", "solari_browser_read_page", "solari_browser_click",
              "solari_browser_type", "solari_browser_key", "solari_browser_evaluate")
SCHEMA_KEYS = {"type", "properties", "required", "enum", "description", "minimum", "maximum", "items"}

SYSTEM = """\
You control a cloud web browser through the solari_browser_* tools. The browser is already open.
Read the page before acting, and use CSS selectors that match the page you read.
When the goal is visibly achieved, stop calling tools and reply with one line: DONE.
If it cannot be achieved, reply with one line: FAILED: reason."""


def clean_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Keep the JSON-schema subset Gemini's function declarations accept, minus sessionId."""
    out = {k: v for k, v in schema.items() if k in SCHEMA_KEYS}
    if "properties" in out:
        out["properties"] = {k: clean_schema(v) for k, v in out["properties"].items() if k != "sessionId"}
    if "required" in out:
        out["required"] = [r for r in out["required"] if r != "sessionId"]
    return out


def chat(key: str, body: Dict[str, Any], timeout: float = 60.0, retries: int = 2) -> Dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    for attempt in range(retries + 1):
        req = urllib.request.Request(GEMINI_URL, data=data, method="POST", headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}"
            if (e.code < 500 and e.code != 429) or attempt == retries:
                raise RuntimeError(detail) from None
        except (TimeoutError, urllib.error.URLError) as e:
            if attempt == retries:
                raise RuntimeError(f"request failed: {e}") from None
        time.sleep(2 * (attempt + 1))
    raise AssertionError("unreachable")


def text_of(res: Any) -> str:
    return "".join(getattr(c, "text", "") for c in res.content)


async def episode(sess: ClientSession, sid: str, tools: List[Dict[str, Any]], key: str, model: str,
                  goal: str, url: str, max_turns: int, max_result_chars: int) -> Dict[str, Any]:
    stats = {"turns": 0, "tool_calls": 0, "input_tokens": 0, "output_tokens": 0,
             "model_seconds": 0.0, "tool_seconds": 0.0, "actions": [], "claimed_done": False, "error": None}
    start = time.perf_counter()
    try:
        t = time.perf_counter()
        nav = text_of(await sess.call_tool("solari_browser_navigate", {"sessionId": sid, "url": url}))
        stats["tool_seconds"] += time.perf_counter() - t
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Goal: {goal}\n\nThe browser has opened {url}:\n{nav[:2000]}"}]
        for _ in range(max_turns):
            t = time.perf_counter()
            data = await asyncio.to_thread(chat, key, {
                "model": model, "messages": messages, "tools": tools, "temperature": 0,
                "reasoning_effort": "none" if "lite" not in model else "minimal"})
            stats["model_seconds"] += time.perf_counter() - t
            stats["turns"] += 1
            usage = data.get("usage") or {}
            stats["input_tokens"] += int(usage.get("prompt_tokens") or 0)
            stats["output_tokens"] += int(usage.get("completion_tokens") or 0)
            msg = (data.get("choices") or [{}])[0].get("message") or {}
            # Sent back as received: Gemini 3 tool calls carry thought signatures it expects returned.
            messages.append({k: v for k, v in msg.items() if v is not None})
            calls = msg.get("tool_calls") or []
            if not calls:
                reply = (msg.get("content") or "").strip()
                stats["claimed_done"] = reply.upper().startswith("DONE")
                if not stats["claimed_done"]:
                    stats["error"] = reply[:200] or "empty reply"
                break
            for call in calls:
                fn = call.get("function") or {}
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except ValueError:
                    args = {}
                stats["actions"].append(f"{name.removeprefix('solari_browser_')}"
                                        f"({', '.join(f'{k}={str(v)[:40]}' for k, v in args.items())})")
                t = time.perf_counter()
                if name in PAGE_TOOLS:
                    res = await sess.call_tool(name, {**args, "sessionId": sid})
                    out = text_of(res)
                    out = ("ERROR: " if res.is_error else "") + out
                else:
                    out = f"ERROR: unknown tool {name}"
                stats["tool_seconds"] += time.perf_counter() - t
                stats["tool_calls"] += 1
                if len(out) > max_result_chars:
                    out = out[:max_result_chars] + f"\n[... truncated by harness at {max_result_chars} chars]"
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": out})
        else:
            stats["error"] = f"no DONE after {max_turns} turns"
    except Exception as e:  # a crashed episode is a failed episode
        stats["error"] = f"{type(e).__name__}: {e}"[:300]
    stats["seconds"] = round(time.perf_counter() - start, 1)
    stats["model_seconds"] = round(stats["model_seconds"], 1)
    stats["tool_seconds"] = round(stats["tool_seconds"], 1)
    return stats


async def create_browser(sess: ClientSession) -> str:
    out = text_of(await sess.call_tool("solari_browser_create", {"mode": "fast", "captcha": False}))
    m = re.search(r'"?sessionId"?\s*[:=]\s*"?([A-Za-z0-9_.\-]+)', out)
    if not m:
        raise RuntimeError("solari_browser_create returned no sessionId")
    return m.group(1)


async def run(args: argparse.Namespace, key: str) -> List[Dict[str, Any]]:
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    # No key in any file: the MCP server inherits SOLARI_API_KEY from this process.
    params = StdioServerParameters(command=npx, args=["-y", "@solarisdk/mcp"], env=dict(os.environ))
    wanted = {t for t in args.tasks.split(",") if t}
    tasks = [t for t in TASKS if not wanted or t[0] in wanted]
    price_in, price_out = PRICES.get(args.model, PRICES["gemini-3.8-flash"])
    rows: List[Dict[str, Any]] = []
    with tempfile.TemporaryFile("w+", encoding="utf-8") as errlog:
        async with stdio_client(params, errlog=errlog) as (r, w), ClientSession(r, w) as sess:
            await sess.initialize()
            listed = {t.name: t for t in (await sess.list_tools()).tools}
            tools = [{"type": "function", "function": {
                "name": n, "description": (listed[n].description or "")[:1000],
                "parameters": clean_schema(listed[n].input_schema)}} for n in PAGE_TOOLS if n in listed]
            sid: Optional[str] = await create_browser(sess)
            try:
                for rep in range(args.repeat):
                    for name, url, goal, check in tasks:
                        st = await episode(sess, sid, tools, key, args.model, goal, url, args.max_turns,
                                           args.max_result_chars)
                        try:
                            page = text_of(await sess.call_tool("solari_browser_evaluate", {
                                "sessionId": sid, "expression": 'location.href + "\\n" + document.body.innerText'}))
                        except Exception:
                            page = ""
                        page_url, _, page_text = page.strip().strip('"').replace("\\n", "\n").partition("\n")
                        ok = st["claimed_done"] and st["error"] is None and judge(check, page_url.strip(), page_text)
                        row = {"model": args.model, "harness": "solari_mcp", "task": name, "rep": rep,
                               "success": ok, **st, "final_url": page_url.strip()[:300],
                               "model_cost_usd": round((st["input_tokens"] * price_in
                                                        + st["output_tokens"] * price_out) / 1e6, 5),
                               "browser_cost_usd": round(st["seconds"] / 3600 * SOLARI_HOURLY_USD, 5)}
                        rows.append(row)
                        print(json.dumps({k: v for k, v in row.items() if k != "actions"}, ensure_ascii=False),
                              flush=True)
                        if st["error"] and ("Connection" in st["error"] or "closed" in st["error"].lower()):
                            with contextlib.suppress(Exception):
                                await sess.call_tool("solari_browser_close", {"sessionId": sid})
                            sid = await create_browser(sess)
            finally:
                if sid:
                    with contextlib.suppress(Exception):
                        await sess.call_tool("solari_browser_close", {"sessionId": sid})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gemini-3.8-flash")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--tasks", default="", help="comma-separated task names (default: all)")
    parser.add_argument("--max-turns", type=int, default=20)
    parser.add_argument("--max-result-chars", type=int, default=40000,
                        help="cap on one tool result in the conversation (Solari truncates large pages itself)")
    parser.add_argument("--out", default="artifacts/benchmarks")
    args = parser.parse_args()
    key = os.getenv("GEMINI_API_KEY")
    if not key or not os.getenv("SOLARI_API_KEY"):
        sys.exit("GEMINI_API_KEY and SOLARI_API_KEY must be set.")
    rows = asyncio.run(run(args, key))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"gemini_solari_mcp_{stamp}.json"
    path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{sum(r['success'] for r in rows)}/{len(rows)} passed -> {path}")


if __name__ == "__main__":
    main()
