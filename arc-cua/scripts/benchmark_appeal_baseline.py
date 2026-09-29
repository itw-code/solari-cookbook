"""Traditional agent vs ARC Index on the denial-appeal task: accuracy, tokens, dollars, time.

Same letters, same stand-in portal, Solari cloud browsers on both sides:

  baseline  A standard tool-calling agent. The model gets the letter's text and the goal, and
            drives the portal with Solari's page tools (read_page, click, type, key, evaluate)
            served by scripts/appeal_tool_server.py. It is told to leave a field blank when the
            letter lacks it or more than one value fits. Nothing checks what it types.
  arc       ARC Index: one extraction call over the block-tagged letter, the grounding checks
            (evidence, row rules, uniqueness), then one batched fill + submit
            (run_arc_index_live.run_case on a Solari BrowserSession).

Models: Gemini 3.8 Flash through its API (tokens from the API's usage), and Claude Sonnet 5.5
through Claude Code subagents (no key). Subagent runs have no per-call usage, so their tokens are
*estimated* the way a bare API agent would be billed: every turn resends the conversation so far,
counted as chars/4 from the tool server's log. ARC-with-Sonnet reuses the extraction answers in
artifacts/benchmarks/offline/answers (scripts/eval_offline.py, mode `default`).

Each submitted field is graded against the truth file: ok, blank (safe), or wrong (typed into the
portal and not the right value; on two_denied any CPT code or billed amount is wrong).

  python scripts/benchmark_appeal_baseline.py baseline-gemini -n 5
  python scripts/benchmark_appeal_baseline.py arc-gemini -n 5
  python scripts/benchmark_appeal_baseline.py arc-sonnet -n 5
  python scripts/benchmark_appeal_baseline.py sonnet-start -n 3        # starts episodes, writes prompts
  python scripts/benchmark_appeal_baseline.py sonnet-finish            # after the subagents are done
  python scripts/benchmark_appeal_baseline.py report
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import time
import urllib.request
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from benchmark_gemini_solari_mcp import chat as gemini_chat  # noqa: E402
from run_arc_index_live import DOCS, ROOT, redact_session_ids, run_case  # noqa: E402

SERVER = "http://127.0.0.1:8765"
OUT = ROOT / "artifacts" / "benchmarks" / "appeal"
TOOL_LOG = OUT / "appeal_tools.jsonl"
PRICES = {"gemini-3.8-flash": (0.75, 3.75),   # USD per 1M in / out (benchmark_gemini_solari_mcp.py)
          "claude-sonnet-5-5": (2.00, 10.00)}  # claude.com/pricing, 2026-09-29
SOLARI_HOURLY_USD = 0.15                       # docs/SOLARI_API.md
LABELS = {"claim_id": "Insurance Claim ID", "patient_name": "Patient Name",
          "date_of_service": "Date of Service", "billed_amount": "Billed Amount",
          "denial_code": "Denial Reason Code", "cpt_code": "CPT Procedure Code",
          "notes": "Appeal Justification"}
CASES = [
    {"id": "SYN-DENIAL-01", "pdf": "synthetic_denial_letter.pdf", "offline": "SYN-DENIAL-BASE"},
    {"id": "SYN-DENIAL-TWO_DENIED", "pdf": "synthetic_denial_letter_two_denied.pdf", "offline": "SYN-DENIAL-TWO_DENIED"},
]
for c in CASES:
    c.update(schema="healthcare_denial_appeal", title="Provider Appeals Portal", labels=LABELS)

SYSTEM = """\
You control a cloud web browser through the browser tools. The browser is already open.
Read the page before acting, and use CSS selectors that match the page you read.
When the goal is visibly achieved, stop calling tools and reply with one line: DONE.
If it cannot be achieved, reply with one line: FAILED: reason."""


def letter_text(pdf: str) -> str:
    import pypdf
    pages = pypdf.PdfReader(str(DOCS / pdf)).pages
    return "\n".join(f"--- page {n} ---\n{p.extract_text() or ''}" for n, p in enumerate(pages, 1))


def goal(case: Dict[str, Any]) -> str:
    return ("File an appeal for the denial described in the letter below, in the Provider Appeals Portal "
            "that is open in the browser. Fill each form field with the value from the letter, then submit "
            "the form. If a field's value is not in the letter, or more than one different value fits it, "
            "leave that field blank.\n\nThe letter (text extracted from the PDF, page by page):\n"
            + letter_text(case["pdf"]))


def truth_of(case: Dict[str, Any]) -> Dict[str, Any]:
    t = json.loads((DOCS / case["pdf"]).with_suffix(".truth.json").read_text(encoding="utf-8"))
    return {k: v["value"] for k, v in t.items() if not k.startswith("_")}


def _norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def grade(received: Dict[str, Any], truth: Dict[str, Any]) -> Dict[str, str]:
    out = {}
    for name, want in truth.items():
        got = str(received.get(name) or "").strip()
        if not got:
            out[name] = "blank"
        elif want is None:
            out[name] = "wrong"
        else:
            wants = want if isinstance(want, list) else [want]
            out[name] = "ok" if _norm(got) in {_norm(w) for w in wants} else "wrong"
    return out


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(SERVER + path, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=240) as resp:
        return json.loads(resp.read().decode("utf-8"))


def save(name: str, rows: List[Dict[str, Any]]) -> pathlib.Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}_{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(redact_session_ids(json.dumps(rows, indent=2, ensure_ascii=False, default=str)), encoding="utf-8")
    return path


# ---- baseline, Gemini through its API -------------------------------------------------

def baseline_gemini(n: int, model: str, max_turns: int) -> List[Dict[str, Any]]:
    key = os.environ["GEMINI_API_KEY"]
    with urllib.request.urlopen(SERVER + "/tools", timeout=30) as resp:
        tools = json.loads(resp.read())
    price_in, price_out = PRICES[model]
    rows = []
    for rep in range(n):
        for case in CASES:
            ep = f"gemini-{case['id']}-{rep}-{int(time.time())}"
            post("/start", {"ep": ep, "case": case["id"]})
            st = {"turns": 0, "tool_calls": 0, "input_tokens": 0, "output_tokens": 0,
                  "model_seconds": 0.0, "tool_seconds": 0.0, "claimed_done": False, "error": None, "actions": []}
            messages = [{"role": "system", "content": SYSTEM},
                        {"role": "user", "content": f"Goal: {goal(case)}"}]
            t0 = time.perf_counter()
            try:
                for _ in range(max_turns):
                    t = time.perf_counter()
                    data = gemini_chat(key, {"model": model, "messages": messages, "tools": tools,
                                             "temperature": 0, "reasoning_effort": "none"}, timeout=90)
                    st["model_seconds"] += time.perf_counter() - t
                    st["turns"] += 1
                    usage = data.get("usage") or {}
                    st["input_tokens"] += int(usage.get("prompt_tokens") or 0)
                    st["output_tokens"] += int(usage.get("completion_tokens") or 0)
                    msg = (data.get("choices") or [{}])[0].get("message") or {}
                    messages.append({k: v for k, v in msg.items() if v is not None})
                    calls = msg.get("tool_calls") or []
                    if not calls:
                        reply = (msg.get("content") or "").strip()
                        st["claimed_done"] = reply.upper().startswith("DONE")
                        if not st["claimed_done"]:
                            st["error"] = reply[:200] or "empty reply"
                        break
                    for call in calls:
                        fn = call.get("function") or {}
                        try:
                            args = json.loads(fn.get("arguments") or "{}")
                        except ValueError:
                            args = {}
                        st["actions"].append(f"{fn.get('name')}({json.dumps(args)[:80]})")
                        r = post("/tool", {"ep": ep, "name": fn.get("name", ""), "args": args})
                        st["tool_seconds"] += r.get("seconds", 0)
                        st["tool_calls"] += 1
                        messages.append({"role": "tool", "tool_call_id": call.get("id", ""),
                                         "content": r.get("result", r.get("error", ""))})
                else:
                    st["error"] = f"no DONE after {max_turns} turns"
            except Exception as e:
                st["error"] = f"{type(e).__name__}: {e}"[:300]
            st["seconds"] = round(time.perf_counter() - t0, 2)
            fin = post("/finish", {"ep": ep})
            g = grade(fin["received"], truth_of(case))
            row = {"harness": "baseline", "model": model, "tokens": "api usage", "case": case["id"], "rep": rep,
                   **st, "model_seconds": round(st["model_seconds"], 2), "tool_seconds": round(st["tool_seconds"], 2),
                   "submitted": fin["submitted"], "received": fin["received"], "grades": g,
                   "model_cost_usd": round((st["input_tokens"] * price_in + st["output_tokens"] * price_out) / 1e6, 6),
                   "browser_cost_usd": round(st["seconds"] / 3600 * SOLARI_HOURLY_USD, 6)}
            rows.append(row)
            print(json.dumps({k: row[k] for k in ("case", "rep", "turns", "tool_calls", "input_tokens",
                                                  "output_tokens", "seconds", "submitted", "grades")}), flush=True)
    return rows


# ---- ARC Index on Solari ----------------------------------------------------------------

class Canned:
    """Chat stand-in that returns a stored extraction answer (for the Sonnet subagent answers)."""

    def __init__(self, answer: str):
        self.answer, self.system, self.user = answer, "", ""

    def complete(self, system: str, user: str) -> dict:
        self.system, self.user = system, user
        return {"text": self.answer, "input_tokens": 0, "output_tokens": 0}


def arc(n: int, model: str, sonnet: bool) -> List[Dict[str, Any]]:
    from arc_cua.browser_session import BrowserSession
    from arc_index.local_doc_index import LocalDocIndexClient

    price_in, price_out = PRICES["claude-sonnet-5-5" if sonnet else model]
    answers = sorted((ROOT / "artifacts" / "benchmarks" / "offline" / "answers").iterdir()) if sonnet else []
    rows = []
    browser = BrowserSession()
    try:
        browser.open("about:blank", backend="solari")
        for rep in range(n):
            for case in CASES:
                if sonnet:
                    chat = Canned((answers[rep] / f"{case['offline']}__default.txt").read_text(encoding="utf-8"))
                    index = LocalDocIndexClient(chat=chat)
                else:
                    index = LocalDocIndexClient(model=model)
                r = run_case(case, browser, index)
                received = {s["field"]: s["received"] for s in r["submission"]}
                # run_case reads what the portal received for truth fields only; notes is not graded.
                g = grade(received, truth_of(case))
                if sonnet:   # estimated as one bare API call: the prompt in, the answer out, chars/4
                    tin, tout, how = (len(chat.system) + len(chat.user)) // 4, len(chat.answer) // 4, "estimated chars/4"
                else:
                    tin, tout, how = index.usage["input_tokens"], index.usage["output_tokens"], "api usage"
                tm = r["timing_ms"]
                secs = (tm["extract_llm"] * (0 if sonnet else 1) + tm["portal_load_inspect_bind"] + tm["fill_and_submit"]) / 1000
                row = {"harness": "arc", "model": "claude-sonnet-5-5" if sonnet else model, "tokens": how,
                       "case": case["id"], "rep": rep, "turns": 1, "tool_calls": 0,
                       "input_tokens": tin, "output_tokens": tout, "seconds": round(secs, 2),
                       "timing_ms": tm, "submitted": bool(r["confirmation_rendered"]),
                       "confirmation_ok": r["confirmation_ok"], "received": received, "grades": g,
                       "rejected": {e["field"]: e["error"] for e in r["extraction"] if not e["grounded"]},
                       "model_cost_usd": round((tin * price_in + tout * price_out) / 1e6, 6),
                       "browser_cost_usd": round(secs / 3600 * SOLARI_HOURLY_USD, 6),
                       "solari_session_id": r["solari_session_id"]}
                rows.append(row)
                print(json.dumps({k: row[k] for k in ("case", "rep", "input_tokens", "output_tokens",
                                                      "seconds", "submitted", "grades")}), flush=True)
    finally:
        browser.shutdown()
    return rows


# ---- baseline, Sonnet through Claude Code subagents -------------------------------------

AGENT_PROMPT = """\
You are the model inside a standard browser agent. Your system prompt and goal are below. The only
way to act is the browser tools, called from the shell (Bash) exactly like this:

  python scripts/appeal_tool.py {ep} TOOL '<json args>'

Tools: read_page {{"format": "text"|"html"|"links"|...}}, click {{"selector": "..."}},
type {{"selector": "...", "text": "...", "clear": true}}, key {{"key": "Enter"}},
evaluate {{"expression": "..."}}. Run `python scripts/appeal_tool.py --tools` once for the full schemas
if you need them. Work from the working directory {root}.

Rules: use only these tool calls (one per Bash command) and nothing else: do not read or write
files, do not look at the repository. Everything you need is below.

=== SYSTEM ===
{system}

=== USER ===
Goal: {goal}

When you are finished, reply with exactly one line: DONE, or FAILED: reason.
"""


def sonnet_start(n: int) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    plan = []
    for rep in range(n):
        for case in CASES:
            ep = f"sonnet-{case['id']}-{rep}"
            post("/start", {"ep": ep, "case": case["id"]})
            f = OUT / "sonnet_prompts" / f"{ep}.txt"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(AGENT_PROMPT.format(ep=ep, root=ROOT.as_posix(), system=SYSTEM, goal=goal(case)),
                         encoding="utf-8")
            plan.append({"ep": ep, "case": case["id"], "rep": rep, "prompt": str(f)})
    (OUT / "sonnet_plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print(json.dumps(plan, indent=1))


def estimate_tokens(base_chars: int, calls: List[Dict[str, Any]]) -> tuple:
    """What a bare API agent loop would be billed: turn k resends the base prompt and every earlier
    call and result; each turn outputs one tool call (~args + 40 chars), the last one "DONE"."""
    tin, conv = 0, base_chars
    for c in calls:
        tin += conv
        conv += c["args_chars"] + 40 + c["result_chars"]
    tin += conv
    tout = sum(c["args_chars"] + 40 for c in calls) + 4
    return tin // 4, tout // 4


def sonnet_finish(asrun: Optional[pathlib.Path]) -> List[Dict[str, Any]]:
    plan = json.loads((OUT / "sonnet_plan.json").read_text(encoding="utf-8"))
    log = [json.loads(l) for l in TOOL_LOG.read_text(encoding="utf-8").splitlines() if l.strip()]
    asrun_tokens = json.loads(asrun.read_text(encoding="utf-8")) if asrun else {}
    price_in, price_out = PRICES["claude-sonnet-5-5"]
    rows = []
    for p in plan:
        case = next(c for c in CASES if c["id"] == p["case"])
        fin = post("/finish", {"ep": p["ep"]})
        calls = [r for r in log if r.get("ep") == p["ep"] and r["event"] == "tool"]
        base = len(SYSTEM) + len("Goal: " + goal(case))
        tin, tout = estimate_tokens(base, calls)
        tool_s = sum(c["seconds"] for c in calls)
        g = grade(fin["received"], truth_of(case))
        rows.append({"harness": "baseline", "model": "claude-sonnet-5-5", "tokens": "estimated chars/4",
                     "case": p["case"], "rep": p["rep"], "turns": len(calls) + 1, "tool_calls": len(calls),
                     "input_tokens": tin, "output_tokens": tout, "tool_seconds": round(tool_s, 2),
                     "seconds": None, "subagent_tokens_as_run": asrun_tokens.get(p["ep"]),
                     "actions": [f"{c['name']}({json.dumps(c['args'])[:80]})" for c in calls],
                     "submitted": fin["submitted"], "received": fin["received"], "grades": g,
                     "model_cost_usd": round((tin * price_in + tout * price_out) / 1e6, 6),
                     "browser_cost_usd": None})
        print(json.dumps({k: rows[-1][k] for k in ("case", "rep", "tool_calls", "input_tokens", "submitted", "grades")}))
    return rows


# ---- report ------------------------------------------------------------------------------

def report() -> None:
    rows = []
    for f in sorted(OUT.glob("*.json")):
        if f.name.startswith(("baseline_", "arc_")):
            rows += json.loads(f.read_text(encoding="utf-8"))
    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault((r["model"], r["harness"]), []).append(r)
    summary = []
    for (model, harness), rs in sorted(groups.items()):
        cells = [v for r in rs for v in r["grades"].values()]
        by_case = {}
        for r in rs:
            by_case.setdefault(r["case"], []).append(r)
        mean = lambda xs: round(sum(xs) / len(xs), 6) if xs else None  # noqa: E731
        s = {"model": model, "harness": harness, "runs": len(rs), "tokens": rs[0]["tokens"],
             "fields": len(cells), "ok": cells.count("ok"), "blank": cells.count("blank"),
             "wrong": cells.count("wrong"),
             "wrong_by_case": {c: sum(v == "wrong" for r in x for v in r["grades"].values()) for c, x in by_case.items()},
             "submitted": sum(bool(r["submitted"]) for r in rs),
             "input_tokens_mean": mean([r["input_tokens"] for r in rs]),
             "output_tokens_mean": mean([r["output_tokens"] for r in rs]),
             "model_cost_usd_mean": mean([r["model_cost_usd"] for r in rs]),
             "tool_calls_mean": mean([r["tool_calls"] for r in rs]),
             "seconds_mean": mean([r["seconds"] for r in rs if r.get("seconds") is not None]),
             "browser_cost_usd_mean": mean([r["browser_cost_usd"] for r in rs if r.get("browser_cost_usd") is not None])}
        summary.append(s)
        print(f"{model:18} {harness:8} runs={s['runs']:<2} ok={s['ok']:<3} blank={s['blank']:<3} wrong={s['wrong']:<3}"
              f" {s['wrong_by_case']}  in={s['input_tokens_mean']} out={s['output_tokens_mean']}"
              f" ${s['model_cost_usd_mean']}  s={s['seconds_mean']}  calls={s['tool_calls_mean']}  [{s['tokens']}]")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["baseline-gemini", "arc-gemini", "arc-sonnet", "sonnet-start", "sonnet-finish", "report"])
    ap.add_argument("-n", type=int, default=5)
    ap.add_argument("--model", default="gemini-3.8-flash")
    ap.add_argument("--max-turns", type=int, default=25)
    ap.add_argument("--asrun", type=pathlib.Path, help="JSON {episode: subagent tokens} from the task notifications")
    args = ap.parse_args()
    if args.cmd == "baseline-gemini":
        print(save("baseline_gemini", baseline_gemini(args.n, args.model, args.max_turns)))
    elif args.cmd == "arc-gemini":
        print(save("arc_gemini", arc(args.n, args.model, sonnet=False)))
    elif args.cmd == "arc-sonnet":
        print(save("arc_sonnet", arc(args.n, args.model, sonnet=True)))
    elif args.cmd == "sonnet-start":
        sonnet_start(args.n)
    elif args.cmd == "sonnet-finish":
        print(save("baseline_sonnet", sonnet_finish(args.asrun)))
    else:
        report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
