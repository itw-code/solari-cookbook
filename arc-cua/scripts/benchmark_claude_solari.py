"""Side A of the head-to-head: Claude Code driving a Solari browser through Solari's own MCP.

Each task runs `claude -p` headless, with Solari's MCP (`@solarisdk/mcp`) as its only tools,
in a clean workspace (no user hooks or CLAUDE.md), and reports time, tokens and the cost
Claude Code itself reports (`total_cost_usd`).

Browser create/close calls and CLI start-up are timed separately and excluded from task time,
matching side B (`benchmark_reflex_policy.py --backend solari`), whose browser stays warm.
Success is judged from one final `solari_browser_evaluate` the agent is asked to run
(URL + page text); it is included in the counts.

Usage: SOLARI_API_KEY=... python scripts/benchmark_claude_solari.py --workspace DIR [--model claude-opus-5-5]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).parent))
from benchmark_reflex_policy import TASKS, judge  # noqa: E402

SOLARI_HOURLY_USD = 0.15  # free/pay-as-you-go browser rate, docs/SOLARI_API.md

PROMPT = """\
Use only the solari tools.
1. Create a browser with solari_browser_create (mode "fast", captcha false).
2. Open {url} and do this: {goal}
3. When the goal is reached, call solari_browser_evaluate once with the expression
   location.href + "\\n" + document.body.innerText.slice(0, 3000)
4. Call solari_browser_close, then reply with one line: DONE or FAILED."""

SETUP_TOOLS = ("solari_browser_create", "solari_browser_close")


def run(claude: str, workspace: Path, mcp_config: Path, model: str, url: str, goal: str,
        timeout: int, budget: float) -> Tuple[List[Tuple[float, Dict[str, Any]]], float]:
    cmd = [claude, "-p", PROMPT.format(url=url, goal=goal), "--output-format", "stream-json", "--verbose",
           "--model", model, "--mcp-config", str(mcp_config), "--strict-mcp-config",
           "--allowedTools", "mcp__solari__*", "--setting-sources", "project",
           "--no-session-persistence", "--max-budget-usd", str(budget)]
    start = time.perf_counter()
    # `npx @solarisdk/mcp` can take over 30 s to start, Claude Code's default MCP connect timeout.
    env = {**os.environ, "MCP_TIMEOUT": "120000"}
    proc = subprocess.Popen(cmd, cwd=workspace, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, encoding="utf-8", errors="replace", env=env)
    timer = threading.Timer(timeout, proc.kill)
    timer.start()
    events = []
    try:
        for line in proc.stdout:
            try:
                events.append((time.perf_counter() - start, json.loads(line)))
            except ValueError:
                pass
        proc.wait()
    finally:
        timer.cancel()
    return events, time.perf_counter() - start


def analyse(events: List[Tuple[float, Dict[str, Any]]], wall: float) -> Dict[str, Any]:
    started: Dict[str, Tuple[float, str]] = {}
    setup_s, tools, last_eval = 0.0, [], ""
    init_at = next((t for t, e in events if e.get("type") == "system"), 0.0)
    result = next((e for _, e in events if e.get("type") == "result"), {})
    for t, e in events:
        content = (e.get("message") or {}).get("content") or []
        if not isinstance(content, list):
            continue
        for c in content:
            if c.get("type") == "tool_use":
                name = c.get("name", "").removeprefix("mcp__solari__")
                started[c.get("id")] = (t, name)
                tools.append(name)
            elif c.get("type") == "tool_result" and c.get("tool_use_id") in started:
                began, name = started.pop(c["tool_use_id"])
                if name in SETUP_TOOLS:
                    setup_s += t - began
                if name == "solari_browser_evaluate":
                    body = c.get("content")
                    last_eval = body if isinstance(body, str) else "".join(
                        x.get("text", "") for x in body or [] if isinstance(x, dict))
    usage = result.get("usage") or {}
    return {
        "task_seconds": round(wall - init_at - setup_s, 1),
        "setup_seconds": round(setup_s, 1), "startup_seconds": round(init_at, 1), "wall_seconds": round(wall, 1),
        "tool_calls": len([x for x in tools if x not in SETUP_TOOLS]), "tools": tools,
        "turns": result.get("num_turns"),
        "input_tokens": int(usage.get("input_tokens") or 0) + int(usage.get("cache_read_input_tokens") or 0)
        + int(usage.get("cache_creation_input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
        "model_cost_usd": round(float(result.get("total_cost_usd") or 0), 4),
        "final_text": str(result.get("result") or "")[:120], "evaluate": last_eval,
        "is_error": bool(result.get("is_error")) or not result,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--model", default="claude-opus-5-5")
    parser.add_argument("--tasks", default="")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--budget", type=float, default=1.0, help="max USD per task (claude --max-budget-usd)")
    parser.add_argument("--out", default="artifacts/benchmarks")
    args = parser.parse_args()
    claude = shutil.which("claude") or shutil.which("claude.exe")
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    workspace = Path(args.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    # No key in this file: the MCP server inherits SOLARI_API_KEY from the environment.
    mcp_config = workspace / "solari-mcp.json"
    mcp_config.write_text(json.dumps({"mcpServers": {"solari": {"command": npx, "args": ["-y", "@solarisdk/mcp"]}}}),
                          encoding="utf-8")
    wanted = {t for t in args.tasks.split(",") if t}
    rows = []
    for name, url, goal, check in TASKS:
        if wanted and name not in wanted:
            continue
        events, wall = run(claude, workspace, mcp_config, args.model, url, goal, args.timeout, args.budget)
        a = analyse(events, wall)
        page_url, _, page_text = a.pop("evaluate").partition("\n")
        row = {"model": args.model, "task": name,
               "success": not a["is_error"] and judge(check, page_url.strip().strip('"'), page_text),
               "final_url": page_url.strip()[:300], **a}
        row["browser_cost_usd"] = round((row["task_seconds"] + row["setup_seconds"]) / 3600 * SOLARI_HOURLY_USD, 5)
        rows.append(row)
        print(json.dumps({k: v for k, v in row.items() if k != "tools"}, ensure_ascii=False), flush=True)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (out_dir / f"claude_solari_{stamp}.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
