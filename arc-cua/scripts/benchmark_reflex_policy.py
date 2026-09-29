"""Reflex policy benchmark: one model call per action on ARC, across fast models.

Same 7 tasks as the head-to-head plus Google Flights (the task Browser Use's Jev demo
times at 7.1 s). Each step is one direct chat-completions call (goal + tree + last actions
-> one JSON action) and one ARC action; see `arc_cua.reflex_policy`.

The browser is local headless Chromium, launched once and kept warm across tasks, so task
time excludes browser start-up. Success is judged from ARC's final page (URL or tree text).

Usage:
  KENARI_API_KEY=... python scripts/benchmark_reflex_policy.py \\
      --models laguna-xs-2-1:free,glm-4-7-flash:free [--base-url https://kenari.id/v1] [--repeat 1]
  GEMINI_API_KEY=... python scripts/benchmark_reflex_policy.py --key-env GEMINI_API_KEY \\
      --base-url https://generativelanguage.googleapis.com/v1beta/openai --models gemini-2.5-flash-lite
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
import statistics
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlparse

from arc_cua.browser_session import BrowserSession
from arc_cua.reflex_policy import ChatClient, run_episode

TASKS = [
    ("hn_click_new", "https://news.ycombinator.com", "Click the 'new' link in the top bar.",
     {"url_has": "/newest"}),
    ("hn_second_comments_link", "https://news.ycombinator.com", "Click the second 'N comments' link on the page.",
     {"url_has": "item?id="}),
    ("wikipedia_search", "https://en.wikipedia.org/wiki/Web_browser", "Search the site for 'Playwright (software)'.",
     {"url_has": "Playwright"}),
    ("httpbin_form_submit", "https://httpbin.org/forms/post",
     "Enter customer name 'Ada Lovelace', choose pizza size Medium, and submit the order.",
     {"text_has": ["Ada Lovelace", "medium"]}),
    ("github_issues_tab", "https://github.com/microsoft/playwright", "Open the repository's Issues tab.",
     {"url_has": "/issues"}),
    ("python_docs_link", "https://docs.python.org/3/library/asyncio.html", "Click the 'Coroutines and tasks' link.",
     {"url_has": "asyncio-task"}),
    ("todomvc_add_item", "https://todomvc.com/examples/react/dist/", "Add a todo item 'buy milk'.",
     {"text_has": ["buy milk"]}),
    ("google_flights_search", "https://www.google.com/travel/flights?hl=en",
     "Search one-way flights from Zurich to London on October 20, 2026, and show the results.",
     # The results URL alone would pass a search for the wrong route or date. Its `tfs` parameter
     # encodes the search: the date plus Freebase ids for Zurich (/m/08966) and London (/m/04jpl).
     {"url_has": "/travel/flights/search", "tfs_has": ["2026-10-20", "/m/08966", "/m/04jpl"]}),
]


def flights_query(url: str) -> str:
    """Printable strings inside Google Flights' base64 protobuf `tfs` parameter."""
    tfs = parse_qs(urlparse(url).query).get("tfs", [""])[0]
    try:
        raw = base64.urlsafe_b64decode(tfs + "=" * (-len(tfs) % 4))
    except (ValueError, binascii.Error):
        return ""
    return " ".join(m.decode() for m in re.findall(rb"[ -~]{4,}", raw))


def judge(check: Dict[str, Any], url: str, tree: str) -> bool:
    text = tree.lower()
    query = flights_query(url) if "tfs_has" in check else ""
    return (check.get("url_has", "") in url
            and all(n in query for n in check.get("tfs_has", []))
            and all(n.lower() in text for n in check.get("text_has", []))
            and (not check.get("text_any") or any(n.lower() in text for n in check["text_any"])))


def median(xs: List[float]) -> float:
    return round(statistics.median(xs), 1) if xs else float("nan")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", required=True, help="comma-separated model ids as the endpoint names them")
    parser.add_argument("--base-url", default=os.getenv("KENARI_BASE_URL", "https://kenari.id/v1"))
    parser.add_argument("--key-env", default="KENARI_API_KEY", help="environment variable holding the API key")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--tasks", default="", help="comma-separated task names (default: all)")
    parser.add_argument("--max-steps", type=int, default=10)
    parser.add_argument("--backend", choices=["local", "solari"], default="local", help="solari needs SOLARI_API_KEY")
    parser.add_argument("--settle-ms", type=float, default=3000.0, help="ARC settle budget per page/action")
    parser.add_argument("--pause", type=float, default=0.0, help="seconds between tasks (free tiers rate-limit per minute)")
    parser.add_argument("--extra", default="", help='JSON merged into each request, e.g. {"reasoning_effort": "none"}')
    parser.add_argument("--out", default="artifacts/benchmarks")
    args = parser.parse_args()
    key = os.getenv(args.key_env)
    if not key:
        sys.exit(f"{args.key_env} is not set.")
    wanted = {t for t in args.tasks.split(",") if t}
    tasks = [t for t in TASKS if not wanted or t[0] in wanted]

    session = BrowserSession()
    session.open(url="about:blank", backend=args.backend)  # warm browser: task times exclude Chromium start-up
    rows: List[Dict[str, Any]] = []
    try:
        for model in [m for m in args.models.split(",") if m]:
            client = ChatClient(args.base_url, key, model, extra=json.loads(args.extra) if args.extra else None)
            for rep in range(args.repeat):
                for name, url, goal, check in tasks:
                    ep = run_episode(session, client, goal, url, max_steps=args.max_steps, settle_ms=args.settle_ms)
                    if ep.error and "Page.goto" in ep.error:
                        # A network drop can leave the tab mid-navigation, failing every later task
                        # instantly; start a fresh browser so one blip costs one task.
                        session.shutdown()
                        session = BrowserSession()
                        session.open(url="about:blank", backend=args.backend)
                    # A run the model itself gave up on never counts, even if the end state happens to match.
                    ok = judge(check, ep.final_url, ep.final_tree) and ep.error is None and ep.failed_reason is None
                    row = {
                        "model": model, "task": name, "rep": rep, "success": ok,
                        "seconds": round(ep.seconds, 1), "model_seconds": round(ep.model_seconds, 1),
                        "act_seconds": round(ep.act_seconds, 1), "steps": len(ep.steps),
                        "claimed_done": ep.finished, "error": ep.error or ep.failed_reason,
                        "actions": [f"{s.op}{'#' + str(s.index) if s.index is not None else ''}"
                                    f"{'=' + str(s.value)[:30] if s.value else ''}{' !' + s.note if s.note else ''}"
                                    for s in ep.steps],
                        "model_ms_per_step": [round(s.model_ms) for s in ep.steps],
                        "final_url": ep.final_url,
                        "backend": args.backend,
                        "input_tokens": sum(s.input_tokens for s in ep.steps),
                        "output_tokens": sum(s.output_tokens for s in ep.steps),
                    }
                    rows.append(row)
                    time.sleep(args.pause)
                    print(json.dumps(row, ensure_ascii=False), flush=True)
    finally:
        session.shutdown()

    out = ["## Reflex policy on ARC — one model call per action (local Chromium, warm)", "",
           "| Model | Success | Median s / task | Median model s / step | Median steps | Google Flights |",
           "|---|:-:|---:|---:|---:|---|"]
    for model in dict.fromkeys(r["model"] for r in rows):
        rs = [r for r in rows if r["model"] == model]
        per_step = [ms / 1000 for r in rs for ms in r["model_ms_per_step"]]
        gf = [r for r in rs if r["task"] == "google_flights_search"]
        gf_txt = ", ".join(f"{'✅' if r['success'] else '❌'} {r['seconds']} s" for r in gf) or "-"
        out.append(f"| `{model}` | {sum(r['success'] for r in rs)}/{len(rs)} | {median([r['seconds'] for r in rs])} | "
                   f"{median(per_step)} | {median([r['steps'] for r in rs])} | {gf_txt} |")
    out += ["", "| Model | Task | Result | s | Model s | ARC s | Steps | Actions |", "|---|---|:-:|---:|---:|---:|---:|---|"]
    for r in rows:
        out.append(f"| `{r['model']}` | {r['task']} | {'✅' if r['success'] else '❌'} | {r['seconds']} | "
                   f"{r['model_seconds']} | {r['act_seconds']} | {r['steps']} | {' → '.join(r['actions'])} |")
    report = "\n".join(out)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (out_dir / f"reflex_policy_{stamp}.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / f"reflex_policy_{stamp}.md").write_text(report, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")  # the report has non-ASCII; Windows consoles default to cp1252
    print("\n" + report)


if __name__ == "__main__":
    main()
