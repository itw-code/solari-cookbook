"""Head-to-head: ARC MCP (`arc-cua-mcp`) vs Solari's official MCP (`@solarisdk/mcp`).

Both drive Solari cloud browsers (fast pool) over stdio, exactly as an agent host would.
No LLM is involved: each task is performed by a scripted policy that stands in for an
agent using that tool set, so the numbers measure what the tools hand the agent, not an
agent's reasoning.

Part A — perception cost: tokens (chars/4) of ARC `arc_inspect` vs Solari `read_page`
(text / links / html) per page, and the actionable handles each exposes.

Part B — grounding tasks: find a named element and act on it, then verify the end state.
  ARC policy:    arc_inspect -> match the named [#N] line -> arc_act by index.
  Solari policy: read_page 'links' for link targets, 'html' for form controls, derive a
                 CSS selector with an HTML parser -> solari_browser_click / _type.
Verification calls are excluded from the counted tool calls, tokens and timings.

Timing: wall seconds per task, the summed latency of counted tool calls, and the Chrome
DevTools Protocol commands each server sent to reach the result. CDP commands are counted
from the servers' own debug logs (Playwright `DEBUG=pw:protocol`, Puppeteer
`DEBUG=puppeteer:protocol:SEND*`) written to temporary files that are deleted afterwards.

Usage: SOLARI_API_KEY=... python scripts/benchmark_vs_solari_mcp.py [--out artifacts/benchmarks]
Cost: two fast-pool Solari sessions for a few minutes (a few cents on the free plan).
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
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PAGES = [
    "https://example.com",
    "https://news.ycombinator.com",
    "https://en.wikipedia.org/wiki/Web_browser",
    "https://github.com/microsoft/playwright",
    "https://docs.python.org/3/library/asyncio.html",
    "https://developer.mozilla.org/en-US/docs/Web/HTML/Element/input",
    "https://httpbin.org/forms/post",
    "https://todomvc.com/examples/react/dist/",
]


def tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


def text_of(result: Any) -> str:
    return "".join(getattr(c, "text", "") for c in result.content)


# --- MCP clients -------------------------------------------------------------------------------

CDP_SEND = re.compile(r"SEND ►")


class ProtocolLog:
    """Counts CDP commands in a server's stderr debug log.

    Uncounted verification calls also send CDP commands, so the count is sampled around
    each counted call rather than across the whole task.
    """

    def __init__(self, path: Path):
        self.path = path

    def sent(self) -> int:
        with contextlib.suppress(OSError):
            return len(CDP_SEND.findall(self.path.read_text(encoding="utf-8", errors="replace")))
        return 0


class Tool:
    """Counts calls, perception tokens, call latency and CDP commands for one MCP server."""

    def __init__(self, session: ClientSession, log: Optional[ProtocolLog] = None):
        self.s = session
        self.log = log
        self.reset()

    async def call(self, name: str, args: Dict[str, Any], perception: bool = False, counted: bool = True) -> str:
        before = self.log.sent() if counted and self.log else 0
        start = time.perf_counter()
        res = await self.s.call_tool(name, args)
        elapsed = time.perf_counter() - start
        out = text_of(res)
        if counted:
            self.calls += 1
            self.call_seconds += elapsed
            if self.log:
                await asyncio.sleep(0.2)  # let the server's stderr reach the log file
                self.cdp_commands += self.log.sent() - before
            if perception:
                self.perception_tokens += tokens(out)
        if res.is_error:
            raise RuntimeError(f"{name}: {out[:300]}")
        return out

    def reset(self) -> None:
        self.calls = 0
        self.perception_tokens = 0
        self.call_seconds = 0.0
        self.cdp_commands = 0


class Arc:
    def __init__(self, tool: Tool):
        self.t = tool

    async def open(self) -> None:
        await self.t.call("arc_open", {"backend": "solari"}, counted=False)

    async def goto(self, url: str) -> None:
        await self.t.call("arc_open", {"url": url, "backend": "solari"})

    async def inspect(self, counted: bool = True, query: Optional[str] = None) -> str:
        args: Dict[str, Any] = {"settle_ms": 4000}
        if query:
            args["query"] = query
        return await self.t.call("arc_inspect", args, perception=True, counted=counted)

    async def find(self, tree: str, role: str, name: str, query: str, nth: int = 0) -> Optional[int]:
        """Ground a named element: in the tree, else (truncated tree) via arc_inspect(query)."""
        idx = arc_index(tree, role, name, nth)
        if idx is None and "Truncated" in tree.splitlines()[1]:
            idx = arc_index(await self.inspect(query=query), role, name, nth)
        return idx

    async def act(self, observe: bool = False, **kw: Any) -> Dict[str, Any]:
        """arc_act; with observe, the post-action tree comes back under "tree" (counted as perception)."""
        out = await self.t.call("arc_act", {**kw, "observe": observe}, perception=observe)
        report, _, tree = out.partition("\n\n")
        result = json.loads(report)
        result["tree"] = tree
        return result

    async def url(self) -> str:
        return (await self.inspect(counted=False)).splitlines()[0].removeprefix("URL: ")

    async def page_text(self) -> str:
        return await self.inspect(counted=False)

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await self.t.call("arc_close", {}, counted=False)


class Solari:
    def __init__(self, tool: Tool):
        self.t = tool
        self.sid: Optional[str] = None

    async def open(self) -> None:
        out = await self.t.call("solari_browser_create", {"mode": "fast", "captcha": False}, counted=False)
        m = re.search(r'"?sessionId"?\s*[:=]\s*"?([A-Za-z0-9_.\-]+)', out)
        if not m:
            raise RuntimeError(f"no sessionId in create output: {out[:200]}")
        self.sid = m.group(1)

    async def goto(self, url: str) -> None:
        await self.t.call("solari_browser_navigate", {"sessionId": self.sid, "url": url})

    async def read(self, fmt: str, counted: bool = True) -> str:
        return await self.t.call("solari_browser_read_page", {"sessionId": self.sid, "format": fmt},
                                 perception=True, counted=counted)

    async def click(self, selector: str) -> None:
        await self.t.call("solari_browser_click", {"sessionId": self.sid, "selector": selector})

    async def type(self, selector: str, text: str, enter: bool = False) -> None:
        await self.t.call("solari_browser_type", {"sessionId": self.sid, "selector": selector, "text": text,
                                                  "clear": True, "pressEnter": enter})

    async def evaluate(self, expr: str) -> str:
        return await self.t.call("solari_browser_evaluate", {"sessionId": self.sid, "expression": expr}, counted=False)

    async def url(self) -> str:
        return (await self.evaluate("location.href")).strip().strip('"')

    async def page_text(self) -> str:
        return await self.evaluate("document.body.innerText")

    async def close(self) -> None:
        if self.sid:
            with contextlib.suppress(Exception):
                await self.t.call("solari_browser_close", {"sessionId": self.sid}, counted=False)


# --- Solari-side grounding helpers (what an agent must derive from raw output) -----------------

def parse_links(out: str) -> List[Dict[str, str]]:
    """Extract {text, href} pairs from read_page 'links' output (JSON or line-oriented)."""
    with contextlib.suppress(ValueError):
        data = json.loads(out)
        items = data.get("links", data) if isinstance(data, dict) else data
        if isinstance(items, list):
            return [{"text": str(i.get("text", "")).strip(), "href": str(i.get("href", ""))} for i in items if isinstance(i, dict)]
    links = []
    for m in re.finditer(r"\"text\"\s*:\s*\"(.*?)\"\s*,\s*\"href\"\s*:\s*\"(.*?)\"", out):
        links.append({"text": m.group(1).strip(), "href": m.group(2)})
    return links


class FormIndex(HTMLParser):
    """Collects form controls with the attributes an agent would build a selector from."""

    def __init__(self) -> None:
        super().__init__()
        self.controls: List[Dict[str, str]] = []
        self.labels: Dict[str, str] = {}
        self._label_for: Optional[str] = None
        self._label_text = ""
        self._label_controls: List[Dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: List[Any]) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag == "label":
            self._label_for, self._label_text, self._label_controls = a.get("for"), "", []
        elif tag in ("input", "textarea", "select", "button"):
            ctrl = {"tag": tag, **a, "label": ""}
            self.controls.append(ctrl)
            if self._label_for is not None or self._label_text is not None:
                self._label_controls.append(ctrl)

    def handle_data(self, data: str) -> None:
        if self._label_for is not None or self._label_controls is not None:
            self._label_text += data
        if self.controls and self.controls[-1]["tag"] == "button" and not self.controls[-1].get("text"):
            self.controls[-1]["text"] = data.strip()

    def handle_endtag(self, tag: str) -> None:
        if tag == "label":
            text = " ".join(self._label_text.split())
            for c in self._label_controls:
                c["label"] = text
            if self._label_for:
                self.labels[self._label_for] = text
            self._label_for, self._label_controls = None, []

    def find(self, pred: Callable[[Dict[str, str]], bool]) -> Optional[str]:
        for c in self.controls:
            if c.get("id") and c["id"] in self.labels:
                c["label"] = c["label"] or self.labels[c["id"]]
            if pred(c):
                if c.get("id"):
                    return f"#{c['id']}"
                if c.get("name") and c.get("value") and c.get("type") in ("radio", "checkbox"):
                    return f"{c['tag']}[name='{c['name']}'][value='{c['value']}']"
                if c.get("name"):
                    return f"{c['tag']}[name='{c['name']}']"
                if c.get("class"):
                    return f"{c['tag']}." + ".".join(c["class"].split())
                if c["tag"] == "button":
                    buttons = [b for b in self.controls if b["tag"] == "button"]
                    return "button" if len(buttons) == 1 else f"button:nth-of-type({buttons.index(c) + 1})"
        return None


def form_index(html: str) -> FormIndex:
    idx = FormIndex()
    idx.feed(html)
    return idx


# --- ARC-side grounding helper ------------------------------------------------------------------

def arc_index(tree: str, role: str, name: str, nth: int = 0) -> Optional[int]:
    """Index of the nth `[#N] role "name..."` line, including DROPPED-ACTIONABLE entries."""
    pattern = re.compile(rf'\[#(\d+)\] {re.escape(role)} "{name}')
    hits = [int(m.group(1)) for m in pattern.finditer(tree)]
    return hits[nth] if len(hits) > nth else None


# --- tasks --------------------------------------------------------------------------------------

@dataclass
class TaskResult:
    task: str
    tool: str
    success: bool
    calls: int
    perception_tokens: int
    seconds: float
    tool_seconds: float = 0.0
    cdp_commands: int = 0
    error: Optional[str] = None


async def run_task(name: str, tool_name: str, client: Any, tool: Tool, fn: Callable, check: Callable) -> TaskResult:
    tool.reset()
    start = time.perf_counter()
    try:
        await fn(client)
        ok = await check(client)
        err = None
    except Exception as e:  # a failed grounding step is a failed task
        ok, err = False, f"{type(e).__name__}: {e}"[:300]
    seconds = time.perf_counter() - start
    return TaskResult(name, tool_name, ok, tool.calls, tool.perception_tokens, round(seconds, 1),
                      round(tool.call_seconds, 1), tool.cdp_commands, err)


def need(value: Any, what: str) -> Any:
    if value is None:
        raise LookupError(f"could not ground {what}")
    return value


async def arc_hn_new(a: Arc):
    await a.goto("https://news.ycombinator.com")
    await a.act(action="click", index=need(arc_index(await a.inspect(), "link", "new\""), "'new' link"))


async def sol_hn_new(s: Solari):
    await s.goto("https://news.ycombinator.com")
    link = need(next((l for l in parse_links(await s.read("links")) if l["text"] == "new"), None), "'new' link")
    await s.click(f"a[href='{link['href'].split('ycombinator.com/')[-1]}']")


async def arc_hn_comments(a: Arc):
    await a.goto("https://news.ycombinator.com")
    tree = await a.inspect()
    idx = need(await a.find(tree, "link", r"\d+[  ]comments", "comments", 1), "2nd comments link")
    await a.act(action="click", index=idx)


async def sol_hn_comments(s: Solari):
    await s.goto("https://news.ycombinator.com")
    links = [l for l in parse_links(await s.read("links")) if re.fullmatch(r"\d+\s+comments", l["text"].replace(" ", " "))]
    link = need(links[1] if len(links) > 1 else None, "2nd comments link")
    await s.click(f"a[href='{link['href'].split('ycombinator.com/')[-1]}']")


async def arc_wiki_search(a: Arc):
    await a.goto("https://en.wikipedia.org/wiki/Web_browser")
    tree = await a.inspect()
    idx = arc_index(tree, "searchbox", "Search") or arc_index(tree, "combobox", "Search")
    if idx is None:  # narrow viewports collapse the box behind a "Search" button/link
        toggle = need(arc_index(tree, "button", "Search") or arc_index(tree, "link", "Search"), "search toggle")
        tree = (await a.act(action="click", index=toggle, observe=True))["tree"]
        idx = arc_index(tree, "searchbox", "Search") or arc_index(tree, "combobox", "Search")
    need(idx, "search box")
    await a.act(action="fill", index=idx, value="Playwright (software)")
    await a.act(action="press_key", value="Enter")


async def sol_wiki_search(s: Solari):
    await s.goto("https://en.wikipedia.org/wiki/Web_browser")
    sel = need(form_index(await s.read("html")).find(lambda c: c.get("name") == "search" and c["tag"] == "input"), "search box")
    await s.type(sel, "Playwright (software)", enter=True)


async def arc_form(a: Arc):
    await a.goto("https://httpbin.org/forms/post")
    tree = await a.inspect()
    await a.act(action="fill", index=need(arc_index(tree, "textbox", "Customer name"), "customer name"), value="Ada Lovelace")
    await a.act(action="click", index=need(arc_index(tree, "radio", "Medium"), "Medium radio"))
    await a.act(action="click", index=need(arc_index(tree, "button", "Submit order"), "submit"))


async def sol_form(s: Solari):
    await s.goto("https://httpbin.org/forms/post")
    idx = form_index(await s.read("html"))
    await s.type(need(idx.find(lambda c: "customer name" in c["label"].lower()), "customer name"), "Ada Lovelace")
    await s.click(need(idx.find(lambda c: c.get("type") == "radio" and c["label"].strip().lower() == "medium"), "Medium radio"))
    await s.click(need(idx.find(lambda c: c["tag"] == "button" and "submit order" in c.get("text", "").lower()), "submit"))


async def arc_github_issues(a: Arc):
    await a.goto("https://github.com/microsoft/playwright")
    tree = await a.inspect()
    await a.act(action="click", index=need(await a.find(tree, "link", "Issues", "issues"), "Issues tab"))


async def sol_github_issues(s: Solari):
    await s.goto("https://github.com/microsoft/playwright")
    # Several "Issues" links exist (marketing menu, repo tab); an agent picks the repo's own.
    link = need(next((l for l in parse_links(await s.read("links"))
                      if l["text"].startswith("Issues") and "/microsoft/playwright/issues" in l["href"]), None), "Issues tab")
    href = link["href"].replace("https://github.com", "")
    await s.click(f"a[href='{href}']")


async def arc_docs_link(a: Arc):
    await a.goto("https://docs.python.org/3/library/asyncio.html")
    tree = await a.inspect()
    await a.act(action="click", index=need(await a.find(tree, "link", "Coroutines and tasks", "coroutines tasks"), "Coroutines link"))


async def sol_docs_link(s: Solari):
    await s.goto("https://docs.python.org/3/library/asyncio.html")
    link = need(next((l for l in parse_links(await s.read("links")) if l["text"] == "Coroutines and tasks"), None), "Coroutines link")
    await s.click(f"a[href='{link['href'].split('/library/')[-1]}']")


async def arc_todo(a: Arc):
    await a.goto("https://todomvc.com/examples/react/dist/")
    tree = await a.inspect()
    idx = need(arc_index(tree, "textbox", "New Todo Input") or arc_index(tree, "textbox", "What needs"), "new todo input")
    await a.act(action="fill", index=idx, value="buy milk")
    await a.act(action="press_key", value="Enter")


async def sol_todo(s: Solari):
    await s.goto("https://todomvc.com/examples/react/dist/")
    sel = need(form_index(await s.read("html")).find(
        lambda c: c["tag"] == "input" and ("new-todo" in c.get("class", "") or "What needs" in c.get("placeholder", ""))), "new todo input")
    await s.type(sel, "buy milk", enter=True)


def url_has(fragment: str):
    async def check(c: Any) -> bool:
        return fragment in await c.url()
    return check


def text_has(*needles: str):
    async def check(c: Any) -> bool:
        body = await c.page_text()
        return all(n in body for n in needles)
    return check


TASKS = [
    ("hn_click_new", arc_hn_new, sol_hn_new, url_has("/newest")),
    ("hn_second_comments_link", arc_hn_comments, sol_hn_comments, url_has("item?id=")),
    ("wikipedia_search", arc_wiki_search, sol_wiki_search, url_has("Playwright")),
    ("httpbin_form_submit", arc_form, sol_form, text_has("Ada Lovelace", "medium")),
    ("github_issues_tab", arc_github_issues, sol_github_issues, url_has("/issues")),
    ("python_docs_link", arc_docs_link, sol_docs_link, url_has("asyncio-task")),
    ("todomvc_add_item", arc_todo, sol_todo, text_has("buy milk")),
]


# --- main ---------------------------------------------------------------------------------------

async def part_a(arc: Arc, sol: Solari) -> List[Dict[str, Any]]:
    rows = []
    for url in PAGES:
        row: Dict[str, Any] = {"url": url}
        try:
            await arc.goto(url)
            t = time.perf_counter()
            tree = await arc.inspect(counted=False)
            row["arc_ms"] = round((time.perf_counter() - t) * 1000)
            row["arc_tokens"] = tokens(tree)
            header = next((l for l in tree.splitlines() if l.startswith("# AXTree")), "")
            m = re.search(r"Actionable: (\d+)", header)
            d = re.search(r"dropped_actionable=(\d+)", tree)
            row["arc_actionable_visible"] = int(m.group(1)) if m else 0
            row["arc_actionable_total"] = row["arc_actionable_visible"] + (int(d.group(1)) if d else 0)
            row["arc_truncated"] = "Truncated" in header
        except Exception as e:
            row["arc_error"] = str(e)[:200]
        try:
            await sol.goto(url)
            for fmt in ("text", "links", "html"):
                t = time.perf_counter()
                out = await sol.read(fmt, counted=False)
                row[f"solari_{fmt}_ms"] = round((time.perf_counter() - t) * 1000)
                row[f"solari_{fmt}_tokens"] = tokens(out)
                row[f"solari_{fmt}_truncated"] = "truncat" in out.lower()[-400:]
                if fmt == "links":
                    row["solari_links"] = len(parse_links(out))
        except Exception as e:
            row["solari_error"] = str(e)[:200]
        rows.append(row)
        print(json.dumps(row), flush=True)
    return rows


async def part_b(arc: Arc, arc_tool: Tool, sol: Solari, sol_tool: Tool) -> List[TaskResult]:
    results = []
    for name, arc_fn, sol_fn, check in TASKS:
        for tool_name, client, tool, fn in (("arc", arc, arc_tool, arc_fn), ("solari", sol, sol_tool, sol_fn)):
            r = await run_task(name, tool_name, client, tool, fn, check)
            results.append(r)
            print(json.dumps(asdict(r)), flush=True)
    return results


def markdown(rows: List[Dict[str, Any]], results: List[TaskResult]) -> str:
    out = ["## Part A — perception cost per page (tokens ≈ chars/4)", "",
           "| Page | ARC inspect | ARC actionable (visible / total) | Solari text | Solari links | Solari html |",
           "|---|---:|---:|---:|---:|---:|"]
    for r in rows:
        out.append(
            f"| {r['url'].split('//')[1][:45]} | {r.get('arc_tokens', 'err')}{' (T)' if r.get('arc_truncated') else ''} | "
            f"{r.get('arc_actionable_visible', '-')} / {r.get('arc_actionable_total', '-')} | "
            f"{r.get('solari_text_tokens', 'err')}{' (T)' if r.get('solari_text_truncated') else ''} | "
            f"{r.get('solari_links_tokens', 'err')}{' (T)' if r.get('solari_links_truncated') else ''} | "
            f"{r.get('solari_html_tokens', 'err')}{' (T)' if r.get('solari_html_truncated') else ''} |")
    out += ["", "(T) = output truncated by the tool.", "",
            "s = summed latency of the counted tool calls; CDP = DevTools Protocol commands those calls sent.", "",
            "## Part B — grounding tasks", "",
            "| Task | ARC | Solari | ARC calls / tokens / s / CDP | Solari calls / tokens / s / CDP |", "|---|:-:|:-:|---:|---:|"]
    by_task: Dict[str, Dict[str, TaskResult]] = {}
    for r in results:
        by_task.setdefault(r.task, {})[r.tool] = r
    for task, pair in by_task.items():
        a, s = pair.get("arc"), pair.get("solari")
        out.append(f"| {task} | {'✅' if a and a.success else '❌'} | {'✅' if s and s.success else '❌'} | "
                   f"{a.calls} / {a.perception_tokens} / {a.tool_seconds} / {a.cdp_commands} | "
                   f"{s.calls} / {s.perception_tokens} / {s.tool_seconds} / {s.cdp_commands} |")
    for tool in ("arc", "solari"):
        rs = [r for r in results if r.tool == tool]
        out.append(f"\n**{tool}:** {sum(r.success for r in rs)}/{len(rs)} succeeded, "
                   f"{sum(r.perception_tokens for r in rs)} perception tokens, {sum(r.calls for r in rs)} tool calls, "
                   f"{sum(r.tool_seconds for r in rs):.1f} s in tool calls, {sum(r.cdp_commands for r in rs)} CDP commands.")
    failures = [r for r in results if not r.success]
    if failures:
        out += ["", "### Failures", ""] + [f"- `{r.tool}` `{r.task}`: {r.error or 'end state not reached'}" for r in failures]
    return "\n".join(out)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="artifacts/benchmarks")
    args = parser.parse_args()
    if not os.getenv("SOLARI_API_KEY"):
        sys.exit("SOLARI_API_KEY is required (both servers use Solari browsers).")

    env = {**os.environ, "DEBUG": "pw:protocol,puppeteer:protocol:SEND*", "DEBUG_COLORS": "0"}
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    arc_params = StdioServerParameters(command="arc-cua-mcp", args=[], env=env)
    sol_params = StdioServerParameters(command=npx, args=["-y", "@solarisdk/mcp"], env=env)

    # Protocol logs carry page content, so they live in a temp dir and never reach artifacts.
    with tempfile.TemporaryDirectory(prefix="arc_bench_") as tmp:
        logs = Path(tmp)
        with open(logs / "arc.log", "w", encoding="utf-8") as arc_err, \
                open(logs / "solari.log", "w", encoding="utf-8") as sol_err:
            rows, results = await run_all(arc_params, sol_params, arc_err, sol_err, logs)
        for name in ("arc", "solari"):
            if not ProtocolLog(logs / f"{name}.log").sent():
                print(f"WARNING: {name} protocol log is empty; its CDP counts are 0, not measured.", file=sys.stderr)
    write_report(args.out, rows, results)


async def run_all(arc_params: StdioServerParameters, sol_params: StdioServerParameters,
                  arc_err: Any, sol_err: Any, logs: Path) -> tuple:
    async with stdio_client(arc_params, errlog=arc_err) as (ar, aw), stdio_client(sol_params, errlog=sol_err) as (sr, sw):
        async with ClientSession(ar, aw) as arc_s, ClientSession(sr, sw) as sol_s:
            await arc_s.initialize()
            await sol_s.initialize()
            arc_tool = Tool(arc_s, ProtocolLog(logs / "arc.log"))
            sol_tool = Tool(sol_s, ProtocolLog(logs / "solari.log"))
            arc, sol = Arc(arc_tool), Solari(sol_tool)
            await arc.open()
            await sol.open()
            try:
                rows = await part_a(arc, sol)
                results = await part_b(arc, arc_tool, sol, sol_tool)
            finally:
                await arc.close()
                await sol.close()
    return rows, results


def write_report(out: str, rows: List[Dict[str, Any]], results: List[TaskResult]) -> None:
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (out_dir / f"vs_solari_mcp_{stamp}.json").write_text(
        json.dumps({"pages": rows, "tasks": [asdict(r) for r in results]}, indent=2), encoding="utf-8")
    report = markdown(rows, results)
    (out_dir / f"vs_solari_mcp_{stamp}.md").write_text(report, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")  # the report has non-ASCII; Windows consoles default to cp1252
    print("\n" + report)


if __name__ == "__main__":
    asyncio.run(main())
