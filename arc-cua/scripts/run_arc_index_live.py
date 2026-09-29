"""ARC Index live run: real PDFs -> grounded extraction -> portal fill on a real browser.

For each case: index the PDF, extract the schema's fields with block citations (Gemini over
pypdf blocks, see arc_index.local_doc_index), reject any value its cited block does not contain,
bind the rest to the portal's [#N] fields, fill and submit, then grade three things against
the case's ground truth:
  extraction - value and page match the truth file
  submission - what the portal actually received (it echoes its form data) matches the truth
  receipt    - the scraped confirmation code equals the one the portal rendered

The portal is loaded with page.set_content (BrowserSession rejects data: URLs on purpose),
so a Solari browser needs no public host.

Run:
  python scripts/run_arc_index_live.py --backend local
  python scripts/run_arc_index_live.py --backend solari      # billed Solari session, released at the end
Needs GEMINI_API_KEY (and SOLARI_API_KEY for --backend solari).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import re
import sys
import time
from typing import Any, Dict, List

from arc_cua.browser_session import BrowserSession
from arc_index.index_bridge import ArcIndexBridge, load_schema
from arc_index.local_doc_index import LocalDocIndexClient


def make_index(kind: str, model: str) -> Any:
    """'blocks': pypdf line blocks + one model call (block-level citations).
    'pageindex': the real PageIndex SDK in local mode (Flash tree, page-level citations),
    indexing into a fresh temp dir so every run pays the real indexing cost."""
    if kind == "pageindex":
        import tempfile
        from arc_index.pageindex_adapter import PageIndexAdapter
        return PageIndexAdapter(model=f"gemini/{model}", storage_path=tempfile.mkdtemp(prefix="pageindex-"))
    return LocalDocIndexClient(model=model)

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "tests" / "fixtures" / "documents"

PORTAL = """<!DOCTYPE html><html><head><title>{title}</title><style>
body {{ font-family: sans-serif; margin: 32px; }} .f {{ margin-bottom: 12px; }}
label {{ display: block; font-weight: bold; font-size: 13px; }} input {{ width: 360px; padding: 6px; }}
#ok {{ display: none; }}
</style></head><body>
<h2>{title}</h2>
<form id="form">{inputs}<button type="submit">Submit Appeal</button></form>
<div id="ok"><strong>Appeal Accepted.</strong>
<p>Confirmation Reference: <span id="code"></span></p><pre id="echo"></pre></div>
<script>
document.getElementById('form').addEventListener('submit', function (e) {{
  e.preventDefault();
  var data = Object.fromEntries(new FormData(e.target).entries());
  var code = 'APL-' + Date.now().toString(36).toUpperCase() + '-' + Math.floor(Math.random() * 9000 + 1000);
  document.getElementById('code').textContent = code;
  document.getElementById('echo').textContent = JSON.stringify(data);
  e.target.style.display = 'none';
  document.getElementById('ok').style.display = 'block';
}});
</script></body></html>"""

CASES = [
    {
        "id": "SYN-DENIAL-01",
        "pdf": "synthetic_denial_letter.pdf",
        "schema": "healthcare_denial_appeal",
        "title": "Provider Appeals Portal",
        "labels": {"claim_id": "Insurance Claim ID", "patient_name": "Patient Name",
                   "date_of_service": "Date of Service", "billed_amount": "Billed Amount",
                   "denial_code": "Denial Reason Code", "cpt_code": "CPT Procedure Code",
                   "notes": "Appeal Justification"},
    },
    {
        "id": "MED-CMS-01",
        "pdf": "cms_fiss_spr_example.pdf",
        "schema": "medicare_redetermination",
        "title": "Medicare Redetermination Request",
        "labels": {"patient_name": "Beneficiary Name", "mbi": "Medicare Beneficiary Identifier",
                   "from_date": "Service From Date", "thru_date": "Service Through Date",
                   "reason_code": "Claim Adjustment Reason Code", "remark_code": "Remittance Remark Code"},
    },
]


def _norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _matches(got: Any, want: Any) -> bool:
    wants = want if isinstance(want, list) else [want]
    return _norm(got) in {_norm(w) for w in wants}


def redact_session_ids(text: str) -> str:
    """Keep 8 characters of each Solari session id: enough to tell runs apart, while the full
    id is an opaque session token that has no place in a committed result file."""
    return re.sub(r'("solari_session_id": ")([^"]{8})[^"]*"', r'\1\2…"', text)


def _page_count(pdf: pathlib.Path) -> int:
    import pypdf
    return len(pypdf.PdfReader(str(pdf)).pages)


def portal_html(case: Dict[str, Any]) -> str:
    inputs = "".join(f'<div class="f"><label for="{k}">{v}</label><input id="{k}" name="{k}"></div>'
                     for k, v in case["labels"].items())
    return PORTAL.format(title=case["title"], inputs=inputs)


def run_case(case: Dict[str, Any], browser: BrowserSession, index: Any) -> Dict[str, Any]:
    pdf = DOCS / case["pdf"]
    truth = {k: v for k, v in json.loads(pdf.with_suffix(".truth.json").read_text(encoding="utf-8")).items()
             if not k.startswith("_")}
    schema = load_schema(case["schema"])
    bridge = ArcIndexBridge(index, browser)

    t0 = time.perf_counter()
    doc_id = bridge.ingest_document(str(pdf))
    t_index = time.perf_counter()
    fields = bridge.extract_action_fields(doc_id, schema, pdf.name)
    t_extract = time.perf_counter()

    extraction = []
    for name, spec in truth.items():
        f = next((x for x in fields if x.field_name == name), None)
        extraction.append({
            "field": name, "expected": spec["value"],
            "got": f.value if f else None,
            "grounded": bool(f and f.validation_status),
            "error": f.error_message if f else "not returned",
            "cited_page": f.citation.page if f else None,
            "cited_block": f.citation.block_id if f else None,
            "snippet": f.citation.text_snippet if f else None,
            "value_ok": bool(f and _matches(f.value, spec["value"])),
            "page_ok": bool(f and f.citation.page == spec["page"]),
        })

    # Pass the current backend: open() defaults to "local" and would swap a Solari browser out.
    browser.open("about:blank", backend=browser.backend)
    browser.page.set_content(portal_html(case))
    inspect = browser.inspect(settle_ms=1000)
    steps = bridge.bind_to_axtree(fields, schema, inspect["text"], inspect["action_index_map"])
    t_bind = time.perf_counter()
    receipt = bridge.execute_and_verify(steps, schema, document_name=pdf.name)
    t_exec = time.perf_counter()

    received = json.loads(browser.page.inner_text("#echo") or "{}") if browser.page.is_visible("#echo") else {}
    rendered_code = browser.page.inner_text("#code") if browser.page.is_visible("#code") else None
    submission = [{"field": name, "expected": spec["value"], "received": received.get(name),
                   "ok": _matches(received.get(name, ""), spec["value"])} for name, spec in truth.items()]

    field_steps = [s for s in receipt.step_log if s["field"] != "<submit>"]
    return {
        "case": case["id"], "document": pdf.name, "schema": schema.schema_id,
        "backend": browser.backend, "solari_session_id": receipt.solari_session_id,
        "index": type(index).__name__,
        "pages": _page_count(pdf),
        "extraction": extraction,
        "submission": submission,
        "receipt": dataclasses.asdict(receipt),
        "confirmation_rendered": rendered_code,
        "confirmation_ok": bool(rendered_code) and receipt.submission_confirmation_code == rendered_code,
        "all_fills_changed_state": all(s["success"] and s["state_changed"] for s in field_steps),
        "timing_ms": {
            "index": round((t_index - t0) * 1000, 1),
            "extract_llm": round((t_extract - t_index) * 1000, 1),
            "portal_load_inspect_bind": round((t_bind - t_extract) * 1000, 1),
            "fill_and_submit": round((t_exec - t_bind) * 1000, 1),
            "act_latency_per_step": [s["action_latency_ms"] for s in receipt.step_log],
        },
    }


def summarize(r: Dict[str, Any]) -> List[str]:
    ex, sub = r["extraction"], r["submission"]
    lines = [f"[{r['case']}] {r['document']} ({r['pages']} page(s)) -> {r['schema']}"
             f" | backend={r['backend']} solari_session={'yes' if r['solari_session_id'] else 'none'}"]
    for e in ex:
        mark = "ok " if e["value_ok"] and e["grounded"] else "BAD"
        lines.append(f"  {mark} {e['field']:16} got={e['got']!r:30} cite={e['cited_block']} page_ok={e['page_ok']}"
                     + (f"  ({e['error']})" if e["error"] else ""))
    lines.append(f"  extraction correct+grounded: {sum(e['value_ok'] and e['grounded'] for e in ex)}/{len(ex)}"
                 f" | portal received correct: {sum(s['ok'] for s in sub)}/{len(sub)}"
                 f" | confirmation match: {r['confirmation_ok']} ({r['confirmation_rendered']})"
                 f" | every fill changed state: {r['all_fills_changed_state']}")
    t = r["timing_ms"]
    lines.append(f"  timing ms: extract(LLM)={t['extract_llm']} fill+submit={t['fill_and_submit']}"
                 f" act/step={t['act_latency_per_step']}")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=["local", "solari"], default="local")
    ap.add_argument("--model", default="gemini-3.8-flash")
    ap.add_argument("--index", choices=["blocks", "pageindex"], default="blocks")
    ap.add_argument("--out", default="artifacts/benchmarks")
    args = ap.parse_args()

    index = make_index(args.index, args.model)
    browser = BrowserSession()
    t0 = time.perf_counter()
    results, session_id = [], None
    try:
        browser.open("about:blank", backend=args.backend)
        session_id = getattr(getattr(browser, "_solari_session", None), "session_id", None)
        for case in CASES:
            results.append(run_case(case, browser, index))
    finally:
        browser.shutdown()
    wall_s = time.perf_counter() - t0

    usage = getattr(index, "usage", None)
    report = {"backend": args.backend, "index": args.index, "model": args.model, "solari_session_id": session_id,
              "wall_s": round(wall_s, 1), "llm_usage": usage, "cases": results,
              "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"arc_index_live_{args.backend}_{args.index}_{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(redact_session_ids(json.dumps(report, indent=2, default=str)), encoding="utf-8")

    for r in results:
        print("\n".join(summarize(r)) + "\n")
    print(f"backend={args.backend} session={'yes' if session_id else 'none'} wall={wall_s:.1f}s "
          f"index={args.index} llm_tokens={usage} -> {path.relative_to(ROOT)}")
    ok = all(all(s["ok"] for s in r["submission"]) and r["confirmation_ok"]
             and r["backend"] == args.backend for r in results)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
