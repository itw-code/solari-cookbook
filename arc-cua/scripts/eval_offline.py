"""Extraction eval with the model calls made elsewhere: write the prompts, grade the answers.

For models reached without an API key from this script (e.g. Claude subagents): `prompts`
writes each case's exact prompt (the block index's system prompt plus the bridge's task, as
LocalDocIndexClient.chat would send them), someone answers each one into
<answers>/<run>/<case>__<mode>.txt, and `grade` parses and grades every answer three ways:

  presence  the old check: the cited block contains the value
  evidence  evidence quote on the cited page, value in it, Denied/Paid and same-row rules
  rows      evidence + the uniqueness rule: no other table row on the page fits as well

Since all three grade the same answers, the difference between them is the check alone.

Modes: `default` is the prompt as shipped. `pick` removes the AMBIGUOUS option and tells the
model to give the best fit, so on two_denied it must choose a row: what the checks do when the
model does not flag the ambiguity itself.

  python scripts/eval_offline.py prompts artifacts/benchmarks/offline/prompts
  python scripts/eval_offline.py grade artifacts/benchmarks/offline/answers [--json out.json]
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

from arc_index.index_bridge import ArcIndexBridge
from arc_index.local_doc_index import SYSTEM, LocalDocIndexClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from eval_extraction import DECOY_CASES, case_schema, grade_fields  # noqa: E402
from run_arc_index_live import DOCS  # noqa: E402

CASES = [{"id": "SYN-DENIAL-BASE", "pdf": "synthetic_denial_letter.pdf", "schema": "healthcare_denial_appeal"}] \
    + DECOY_CASES
MODES = ("default", "pick")
CHECKS = ("presence", "evidence", "rows")

AMBIG_SYS = "If more than one different value fits a field, output: field_name: AMBIGUOUS\n"
AMBIG_TASK = "If more than one different value fits a field, write `field_name: AMBIGUOUS`."
PICK = "If more than one value fits a field, give the one that fits best."


class Captured:
    """Chat stand-in: records the prompt (prompts) or returns a stored answer (grade)."""

    def __init__(self, answer: str = ""):
        self.answer, self.system, self.user = answer, None, None

    def complete(self, system: str, user: str) -> dict:
        self.system, self.user = system, user
        return {"text": self.answer, "input_tokens": 0, "output_tokens": 0}


def apply_mode(system: str, user: str, mode: str) -> tuple:
    if mode == "pick":
        assert AMBIG_SYS in system and AMBIG_TASK in user
        system, user = system.replace(AMBIG_SYS, PICK + "\n"), user.replace(AMBIG_TASK, PICK)
    return system, user


class PresenceOnly:
    """The block index without page_lines: the bridge falls back to the presence check."""

    def __init__(self, inner: LocalDocIndexClient):
        self.inner = inner
        self.chat = inner.chat
        self.verify_citation = inner.verify_citation


def run_case(case: dict, answer: str, check: str) -> list:
    chat = Captured(answer)
    client = LocalDocIndexClient(chat=chat)
    doc_id = client.submit_document(str(DOCS / case["pdf"]))["doc_id"]
    schema = case_schema(case)
    if check != "rows":
        for spec in schema.fields:
            spec.row_start = None
    index = PresenceOnly(client) if check == "presence" else client
    return ArcIndexBridge(index).extract_action_fields(doc_id, schema, case["pdf"]), chat


def cmd_prompts(out: pathlib.Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for case in CASES:
        _, chat = run_case(case, "", "rows")
        for mode in MODES:
            system, user = apply_mode(SYSTEM.replace("DOC", case["pdf"]), chat.user, mode)
            (out / f"{case['id']}__{mode}.txt").write_text(
                f"=== SYSTEM ===\n{system}\n=== USER ===\n{user}\n", encoding="utf-8")
    print(f"wrote {len(CASES) * len(MODES)} prompts to {out}")


def cmd_grade(answers: pathlib.Path, json_out: pathlib.Path = None) -> int:
    tally = collections.defaultdict(collections.Counter)   # (case, mode, check, field) -> outcome counts
    wrong_vals = collections.defaultdict(collections.Counter)
    runs = sorted(p for p in answers.iterdir() if p.is_dir())
    for run in runs:
        for case in CASES:
            truth = {k: v for k, v in json.loads((DOCS / case["pdf"]).with_suffix(".truth.json")
                                                  .read_text(encoding="utf-8")).items() if not k.startswith("_")}
            for mode in MODES:
                f = run / f"{case['id']}__{mode}.txt"
                if not f.exists():
                    continue
                for check in CHECKS:
                    graded = grade_fields(run_case(case, f.read_text(encoding="utf-8"), check)[0], truth)
                    for name, (outcome, val) in graded.items():
                        tally[case["id"], mode, check, name][outcome] += 1
                        if outcome == "wrong":
                            wrong_vals[case["id"], mode, check, name][val] += 1
    print(f"{len(runs)} runs from {answers}")
    any_wrong = False
    for case in CASES:
        for mode in MODES:
            keys = [k for k in tally if k[0] == case["id"] and k[1] == mode]
            if not keys:
                continue
            n = sum(tally[keys[0]].values())
            print(f"\n[{case['id']}] mode={mode} n={n}      " + "   ".join(f"{c:>18}" for c in CHECKS))
            for name in dict.fromkeys(k[3] for k in keys):
                cells = []
                for check in CHECKS:
                    c = tally[case["id"], mode, check, name]
                    cells.append(f"ok={c['ok']:<2} wr={c['wrong']:<2} rj={c['rejected']:<2}")
                any_wrong |= bool(tally[case["id"], mode, "rows", name]["wrong"])
                print(f"  {name:16} " + "   ".join(cells))
    for check in CHECKS:
        total = sum(c["wrong"] for k, c in tally.items() if k[2] == check)
        print(f"wrong values accepted, {check:>8}: {total}")
    if json_out:
        json_out.write_text(json.dumps({
            "runs": len(runs),
            "cells": [{"case": k[0], "mode": k[1], "check": k[2], "field": k[3], **dict(v),
                       "wrong_values": dict(wrong_vals[k])} for k, v in sorted(tally.items())],
        }, indent=2), encoding="utf-8")
    return 1 if any_wrong else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prompts").add_argument("out", type=pathlib.Path)
    g = sub.add_parser("grade")
    g.add_argument("answers", type=pathlib.Path)
    g.add_argument("--json", type=pathlib.Path)
    args = ap.parse_args()
    if args.cmd == "prompts":
        cmd_prompts(args.out)
        return 0
    return cmd_grade(args.answers, args.json)


if __name__ == "__main__":
    sys.exit(main())
