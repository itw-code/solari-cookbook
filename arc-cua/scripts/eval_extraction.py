"""Repeat the extraction step N times per case and count right / wrong / rejected per field.

One live run says little about a model's reliability: the CMS reason code was found in half
of the runs, and a prompt change once made the synthetic letter's CPT code wrong 7 times in 10
while single runs looked fine. No browser is involved; this is only index + extract + grounding.

  wrong    = grounded (the cited block contains it) but not the expected value. These are
             the dangerous ones: grounding lets them through to the portal.
  rejected = NOT_FOUND, no citation, or the cited block does not contain the value.
A field whose truth value is null has no single right answer (e.g. two denied lines): it must
be rejected, so rejected counts as ok and any accepted value as wrong.

Besides the live-run CASES this runs the decoy variants of the synthetic letter
(scripts/make_denial_fixture.py). --no-descriptions drops the schema's field descriptions,
which is the prompt that once made the paid line's CPT code pass as grounded.

Run: python scripts/eval_extraction.py -n 20 [--case MED-CMS-01] [--effort low] [--no-descriptions]
Needs GEMINI_API_KEY. Each run is one model call (~1.1k tokens).
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import sys
from concurrent.futures import ThreadPoolExecutor

from arc_index.index_bridge import ArcIndexBridge, load_schema
from arc_index.local_doc_index import LocalDocIndexClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from run_arc_index_live import CASES, DOCS, make_index  # noqa: E402

DECOY_CASES = [{"id": f"SYN-DENIAL-{v.upper()}", "pdf": f"synthetic_denial_letter_{v}.pdf",
                "schema": "healthcare_denial_appeal"} for v in ("swapped", "two_denied", "decoy_first")]


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def case_schema(case: dict, descriptions: bool = True):
    schema = load_schema(case["schema"])
    if not descriptions:
        for f in schema.fields:
            f.description = None
    return schema


def grade_once(case: dict, model: str, effort: str, shared=None, descriptions: bool = True) -> dict:
    """Grade one extraction. `shared` = (client, doc_id) reuses an indexed document, so only
    the question is repeated (PageIndex indexing takes 10-20 s per document)."""
    pdf = DOCS / case["pdf"]
    truth = {k: v for k, v in json.loads(pdf.with_suffix(".truth.json").read_text(encoding="utf-8")).items()
             if not k.startswith("_")}
    if shared:
        client, doc_id = shared
    else:
        client = LocalDocIndexClient(model=model)
        client.chat_client.extra = {"reasoning_effort": effort}
        doc_id = client.submit_document(str(pdf))["doc_id"]
    fields = ArcIndexBridge(client).extract_action_fields(doc_id, case_schema(case, descriptions), pdf.name)
    return grade_fields(fields, truth)


def grade_fields(extracted, truth: dict) -> dict:
    """{field: ("ok" | "wrong" | "rejected", wrong value or None)} for each field in the truth file."""
    fields = {f.field_name: f for f in extracted}
    out = {}
    for name, spec in truth.items():
        f = fields.get(name)
        want = spec["value"] if isinstance(spec["value"], list) else [spec["value"]]
        if spec["value"] is None:
            out[name] = ("ok", None) if not f or not f.validation_status else ("wrong", f.value)
        elif not f or not f.validation_status:
            out[name] = ("rejected", None)
        elif _norm(f.value) in {_norm(w) for w in want}:
            out[name] = ("ok", None)
        else:
            out[name] = ("wrong", f.value)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=10)
    ap.add_argument("--case", action="append", help="case id (repeatable); default all")
    ap.add_argument("--model", default="gemini-3.8-flash")
    ap.add_argument("--effort", default="low")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--index", choices=["blocks", "pageindex"], default="blocks",
                    help="pageindex: index once per case, repeat only the question (--effort ignored)")
    ap.add_argument("--no-descriptions", action="store_true", help="drop the schema field descriptions")
    args = ap.parse_args()

    cases = [c for c in CASES + DECOY_CASES if not args.case or c["id"] in args.case]
    desc = not args.no_descriptions
    any_wrong = False
    for case in cases:
        shared = None
        if args.index == "pageindex":
            client = make_index("pageindex", args.model)
            shared = (client, client.submit_document(str(DOCS / case["pdf"]))["doc_id"])
        with ThreadPoolExecutor(args.workers) as ex:
            runs = list(ex.map(lambda _: grade_once(case, args.model, args.effort, shared, desc), range(args.n)))
        print(f"[{case['id']}] n={args.n} index={args.index} model={args.model} descriptions={desc}"
              + ("" if shared else f" effort={args.effort}"))
        for name in runs[0]:
            counts = collections.Counter(r[name][0] for r in runs)
            wrong_values = collections.Counter(r[name][1] for r in runs if r[name][0] == "wrong")
            any_wrong |= bool(wrong_values)
            print(f"  {name:16} ok={counts['ok']:<3} wrong={counts['wrong']:<3} rejected={counts['rejected']:<3}"
                  + (f" wrong values: {dict(wrong_values)}" if wrong_values else ""))
    return 1 if any_wrong else 0


if __name__ == "__main__":
    sys.exit(main())
