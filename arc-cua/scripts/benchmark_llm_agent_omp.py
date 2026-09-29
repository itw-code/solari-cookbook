"""A real LLM agent driving ARC: the head-to-head's 7 tasks, with a fast model choosing actions.

The head-to-head (`benchmark_vs_solari_mcp.py`) uses scripted policies. This runs the same
tasks with an actual model in the loop, through the Oh My Pi coding agent (`omp`) with
`arc-cua-mcp` as its only tools, and reports wall time, model time, tool time and turns per
task.

Setup:
- `omp` on PATH, with a provider for `--model` (e.g. `kenari_2/laguna-xs-2-1:free`).
- A workspace holding `.omp/mcp.json` that registers `arc-cua-mcp` (pass it as --workspace).
  omp's built-in tools are disabled, so the model can only use the five ARC tools.
- Backend is the local Chromium: every omp run starts a fresh ARC server, and on Solari
  each would be a separately billed session. Local also keeps model latency separate from
  network latency.

Success is judged from the agent's own tool results (the browser closes when omp exits):
the last URL ARC reported, or the text of the last page ARC showed.

Usage: python scripts/benchmark_llm_agent_omp.py --workspace DIR [--model M] [--out artifacts/benchmarks]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SYSTEM_PROMPT = """\
You operate a web browser through the arc tools. Always open pages with backend "local".
Work in as few tool calls as possible:
- mcp__arc_open(url) then mcp__arc_inspect once to see the page as a tree of [#N] elements.
- mcp__arc_act(action, index=N, value=...) performs an action and RETURNS the page after it,
  with fresh [#N] indices. Do not call mcp__arc_inspect after mcp__arc_act; read its result.
- If the tree says Truncated and you cannot see the element, use mcp__arc_inspect(query="words").
- To submit a search or a text field, use action "press_key" with value "Enter" after "fill".
When the goal is reached reply with one line starting DONE. If it is impossible reply FAILED and why.
Never call mcp__arc_close."""

TASKS = [
    ("hn_click_new", "Open https://news.ycombinator.com and click the 'new' link in the top bar.",
     {"url_has": "/newest"}),
    ("hn_second_comments_link", "Open https://news.ycombinator.com and click the second 'N comments' link on the page.",
     {"url_has": "item?id="}),
    ("wikipedia_search", "Open https://en.wikipedia.org/wiki/Web_browser and use the site's search box to search for 'Playwright (software)'.",
     {"url_has": "Playwright"}),
    ("httpbin_form_submit", "Open https://httpbin.org/forms/post, enter customer name 'Ada Lovelace', choose pizza size Medium, and submit the order.",
     {"text_has": ["Ada Lovelace", "medium"]}),
    ("github_issues_tab", "Open https://github.com/microsoft/playwright and open the repository's Issues tab.",
     {"url_has": "/issues"}),
    ("python_docs_link", "Open https://docs.python.org/3/library/asyncio.html and click the 'Coroutines and tasks' link.",
     {"url_has": "asyncio-task"}),
    ("todomvc_add_item", "Open https://todomvc.com/examples/react/dist/ and add a todo item 'buy milk'.",
     {"text_has": ["buy milk"]}),
]


@dataclass
class AgentRun:
    task: str
    success: bool
    wall_seconds: float
    model_seconds: float
    tool_seconds: float
    turns: int
    tool_calls: int
    tools: List[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    final_text: str = ""
    error: Optional[str] = None


def text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(c.get("text", "") for c in content if isinstance(c, dict))
    return ""


def last_url(tool_texts: List[str]) -> str:
    for text in reversed(tool_texts):
        m = re.search(r'^URL: (\S+)', text, re.M) or re.search(r'"url":\s*"([^"]+)"', text)
        if m:
            return m.group(1)
    return ""


def judge(check: Dict[str, Any], tool_texts: List[str]) -> bool:
    if "url_has" in check:
        return check["url_has"] in last_url(tool_texts)
    trees = [t for t in tool_texts if "# AXTree" in t]
    return bool(trees) and all(n.lower() in trees[-1].lower() for n in check["text_has"])


def parse_events(lines: List[Tuple[float, str]]) -> Dict[str, Any]:
    """Pull timings and tool traffic out of omp's --mode json event stream.

    Tool events carry no timestamps, so each line is stamped when it arrives on stdout.
    """
    out: Dict[str, Any] = {"model_ms": 0.0, "turns": 0, "tools": [], "tool_texts": [], "in": 0, "out": 0,
                           "final": "", "tool_ms": 0.0}
    starts: Dict[str, float] = {}
    for arrived, line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        t = e.get("type")
        if t == "message_end":
            msg = e.get("message", {})
            if msg.get("role") == "assistant":
                out["turns"] += 1
                out["model_ms"] += float(msg.get("duration") or 0)
                usage = msg.get("usage") or {}
                out["in"] += int(usage.get("input") or 0) + int(usage.get("cacheRead") or 0)
                out["out"] += int(usage.get("output") or 0)
                text = text_of(msg.get("content"))
                if text.strip():
                    out["final"] = text.strip()
            elif msg.get("role") in ("toolResult", "tool"):
                out["tool_texts"].append(text_of(msg.get("content")))
        elif t == "tool_execution_start":
            starts[e.get("toolCallId", "")] = arrived
            out["tools"].append(e.get("toolName", "?"))
        elif t == "tool_execution_end":
            began = starts.pop(e.get("toolCallId", ""), None)
            if began is not None:
                out["tool_ms"] += (arrived - began) * 1000
            result = e.get("result")
            if isinstance(result, dict):
                out["tool_texts"].append(text_of(result.get("content")))
    return out


def run_task(omp: str, workspace: Path, model: str, name: str, goal: str, check: Dict[str, Any],
             timeout: int, keep: Path) -> AgentRun:
    cmd = [omp, "-p", "--mode", "json", "--no-session", "--no-tools", "--no-extensions", "--no-skills",
           "--no-rules", "--no-lsp", "--model", model, "--system-prompt", SYSTEM_PROMPT, goal]
    start = time.perf_counter()
    lines: List[Tuple[float, str]] = []
    err = None
    err_path = keep / f"{name}.stderr.txt"
    err_file = open(err_path, "w", encoding="utf-8")
    proc = subprocess.Popen(cmd, cwd=workspace, stdout=subprocess.PIPE, stderr=err_file,
                            text=True, encoding="utf-8", errors="replace")
    timer = threading.Timer(timeout, proc.kill)
    timer.start()
    try:
        for line in proc.stdout:
            lines.append((time.perf_counter(), line))
        proc.wait()
    finally:
        timer.cancel()
        err_file.close()
    if proc.returncode != 0:
        killed = f" (killed after {timeout}s)" if time.perf_counter() - start >= timeout else ""
        tail = " ".join(err_path.read_text(encoding="utf-8", errors="replace").split())[-200:]
        err = f"omp exited {proc.returncode}{killed}" + (f": {tail}" if tail else "")
    wall = time.perf_counter() - start
    (keep / f"{name}.jsonl").write_text("".join(l for _, l in lines), encoding="utf-8")
    ev = parse_events(lines)
    return AgentRun(
        task=name, success=judge(check, ev["tool_texts"]), wall_seconds=round(wall, 1),
        model_seconds=round(ev["model_ms"] / 1000, 1), tool_seconds=round(ev["tool_ms"] / 1000, 1),
        turns=ev["turns"], tool_calls=len(ev["tools"]), tools=ev["tools"], input_tokens=ev["in"],
        output_tokens=ev["out"], final_text=ev["final"][:200], error=err,
    )


def markdown(model: str, runs: List[AgentRun]) -> str:
    out = [f"## LLM agent on ARC — `{model}` via omp, local Chromium", "",
           "| Task | Result | Wall s | Model s | Tool s | Turns | Tool calls | Tokens in / out |",
           "|---|:-:|---:|---:|---:|---:|---:|---:|"]
    for r in runs:
        out.append(f"| {r.task} | {'✅' if r.success else '❌'} | {r.wall_seconds} | {r.model_seconds} | "
                   f"{r.tool_seconds} | {r.turns} | {r.tool_calls} | {r.input_tokens:,} / {r.output_tokens:,} |")
    ok = [r for r in runs if r.success]
    out.append(f"\n**{len(ok)}/{len(runs)} succeeded.** Median wall time {median([r.wall_seconds for r in runs])} s "
               f"(successful: {median([r.wall_seconds for r in ok])} s); median model time "
               f"{median([r.model_seconds for r in runs])} s; median tool calls {median([r.tool_calls for r in runs])}.")
    out.append("\nWall time includes omp start-up and launching Chromium. Model s = summed model response time; "
               "Tool s = summed ARC tool time.")
    fails = [r for r in runs if not r.success]
    if fails:
        out += ["", "### Failures", ""] + [f"- `{r.task}`: {r.error or r.final_text or 'end state not reached'} "
                                           f"(tools: {', '.join(r.tools) or 'none'})" for r in fails]
    return "\n".join(out)


def median(xs: List[float]) -> Any:
    if not xs:
        return "-"
    s = sorted(xs)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else round((s[mid - 1] + s[mid]) / 2, 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, help="directory with .omp/mcp.json registering arc-cua-mcp")
    parser.add_argument("--model", default="kenari_2/laguna-xs-2-1:free")
    parser.add_argument("--out", default="artifacts/benchmarks")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--tasks", default="", help="comma-separated task names (default: all)")
    args = parser.parse_args()
    omp = shutil.which("omp") or shutil.which("omp.exe")
    if not omp:
        raise SystemExit("omp not found on PATH")
    workspace = Path(args.workspace)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    keep = workspace / f"transcripts_{stamp}"  # transcripts hold page content; kept out of the repo
    keep.mkdir(parents=True, exist_ok=True)
    wanted = {t for t in args.tasks.split(",") if t}
    runs = []
    for name, goal, check in TASKS:
        if wanted and name not in wanted:
            continue
        r = run_task(omp, workspace, args.model, name, goal, check, args.timeout, keep)
        runs.append(r)
        print(json.dumps(asdict(r)), flush=True)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"llm_agent_omp_{stamp}.json").write_text(
        json.dumps({"model": args.model, "runs": [asdict(r) for r in runs]}, indent=2), encoding="utf-8")
    report = markdown(args.model, runs)
    (out_dir / f"llm_agent_omp_{stamp}.md").write_text(report, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")  # the report has non-ASCII; Windows consoles default to cp1252
    print("\n" + report)


if __name__ == "__main__":
    main()
