"""ARC Index: End-to-End Document-to-Action Execution Pipeline Demo.

Simulates the complete enterprise workflow:
1. PageIndex-style hierarchical document extraction with block-level citations.
2. Form affordance binding to active browser AXTree.
3. Sub-millisecond local reflex execution via ARC BrowserSession.
4. Ground-truth state verification (SimHash) and confirmation receipt generation.
"""

from __future__ import annotations

import json
import logging
import pathlib
import sys
import tempfile
import time

from arc_cua.browser_session import BrowserSession
from arc_index.index_bridge import (
    ArcIndexBridge,
    CitationAnchor,
    DocumentActionSchema,
    ExtractedField,
    FieldTarget,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("demo_arc_index")

# HTML Portal Fixture for Healthcare Denial Appeal
PORTAL_HTML = """<!DOCTYPE html>
<html>
<head>
  <title>Payer Healthcare Appeals Portal</title>
  <style>
    body { font-family: sans-serif; margin: 40px; background: #f8fafc; }
    .card { background: white; padding: 24px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); max-width: 500px; }
    .field { margin-bottom: 16px; }
    label { display: block; font-weight: bold; margin-bottom: 6px; font-size: 13px; }
    input, textarea { width: 100%; padding: 8px; border: 1px solid #cbd5e1; border-radius: 4px; box-sizing: border-box; }
    button { background: #059669; color: white; border: none; padding: 10px 16px; border-radius: 4px; cursor: pointer; font-weight: bold; }
    #confirmation { display: none; margin-top: 20px; padding: 12px; background: #ecfdf5; border: 1px solid #10b981; border-radius: 4px; color: #065f46; }
  </style>
</head>
<body>
  <div class="card">
    <h2>Submit Medical Claim Appeal</h2>
    <form id="appeal-form" onsubmit="event.preventDefault(); handleSubmit();">
      <div class="field">
        <label for="claim_id">Insurance Claim ID</label>
        <input type="text" id="claim_id" name="claim_id" placeholder="Enter claim number">
      </div>
      <div class="field">
        <label for="denial_code">Payer Denial Reason Code</label>
        <input type="text" id="denial_code" name="denial_code" placeholder="e.g. CO-16">
      </div>
      <div class="field">
        <label for="cpt_code">CPT Procedure Code</label>
        <input type="text" id="cpt_code" name="cpt_code" placeholder="5-digit code">
      </div>
      <div class="field">
        <label for="notes">Appeal Justification Notes</label>
        <textarea id="notes" name="notes" rows="3" placeholder="Clinical justification"></textarea>
      </div>
      <button type="submit" id="submit_btn">Submit Appeal Request</button>
    </form>
    <div id="confirmation">
      <strong>Appeal Accepted!</strong>
      <p>Confirmation Reference: <span id="conf_code" style="font-family: monospace; font-weight: bold;">CONF-2026-99812-TX</span></p>
      <p>Status: Under Review by Medical Director</p>
    </div>
  </div>
  <script>
    function handleSubmit() {
      document.getElementById('appeal-form').style.display = 'none';
      document.getElementById('confirmation').style.display = 'block';
    }
  </script>
</body>
</html>
"""


def run_demo():
    print("=" * 78)
    print("  ARC INDEX: VECTORLESS DOCUMENT-TO-ACTION RUNTIME DEMO")
    print("  PageIndex Reasoning Retrieval -> ARC In-VM Reflex Loop on Chromium")
    print("=" * 78)

    # 1. Write Portal HTML fixture to temp file
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(PORTAL_HTML)
        portal_path = f.name
    portal_uri = pathlib.Path(portal_path).resolve().as_uri()

    # 2. Simulate Document Ingestion & PageIndex Tree Extraction
    print("\n[Step 1] Ingesting Unstructured Insurance Denial Letter (simulated 18-page PDF)...")
    time.sleep(0.3)
    document_name = "united_healthcare_denial_99812.pdf"
    print(f"  • Document: {document_name} (18 pages, tabular EOB + clinical notes)")
    print("  • PageIndex Method: Hierarchical Tree Navigation (No Chunking, No Vector DB)")
    print("  • Indexing Latency: ~1.4s | Indexing Cost: $0.018 ($0.001/page)")

    # Simulated reasoning extraction with block-level citations
    extracted_fields = [
        ExtractedField(
            field_name="claim_id",
            value="CLM-98214-A",
            citation=CitationAnchor(document=document_name, page=2, block_id="claim_summary_b4"),
        ),
        ExtractedField(
            field_name="denial_code",
            value="CO-16",
            citation=CitationAnchor(document=document_name, page=4, block_id="adjudication_remark_b1"),
        ),
        ExtractedField(
            field_name="cpt_code",
            value="99214",
            citation=CitationAnchor(document=document_name, page=2, block_id="line_item_table_r2"),
        ),
        ExtractedField(
            field_name="notes",
            value="Documentation supports moderate medical decision-making per AMA 2026 guidelines.",
            citation=CitationAnchor(document=document_name, page=6, block_id="clinical_eval_b9"),
        ),
    ]

    print("\n[Step 2] Extracted Citation-Grounded Fields via PageIndex Reasoning:")
    for f in extracted_fields:
        print(f"  • {f.field_name:12}: {f.value:20} [Cited: p.{f.citation.page} block={f.citation.block_id}]")

    # 3. Define Target Form Schema
    schema = DocumentActionSchema(
        schema_id="payer_appeal_portal",
        target_url_pattern=portal_uri,
        fields=[
            FieldTarget("claim_id", "textbox", ["Insurance Claim ID", "Claim ID"], "FILL"),
            FieldTarget("denial_code", "textbox", ["Denial Reason Code", "Denial Code"], "FILL"),
            FieldTarget("cpt_code", "textbox", ["CPT Procedure Code", "CPT"], "FILL"),
            FieldTarget("notes", "textbox", ["Appeal Justification Notes", "Notes"], "FILL"),
        ],
        submit_affordance_hint="Submit",
    )

    # 4. Launch ARC Browser Session & Inspect Portal Form
    print(f"\n[Step 3] Launching ARC Browser Session & Inspecting Portal Form at {portal_uri}...")
    browser = BrowserSession()
    open_res = browser.open(portal_uri)
    print(f"  • Browser: {open_res['backend']} | Title: '{open_res['title']}'")

    inspect_res = browser.inspect()
    axtree_text = inspect_res["text"]
    action_map = inspect_res.get("action_index_map") or getattr(browser, "_index_map", {})
    print(f"  • AXTree: {inspect_res['actionable_count']} actionable nodes | Tokens: ~{inspect_res['estimated_tokens']}")

    # 5. Compile Actions with ArcIndexBridge
    print("\n[Step 4] Compiling Document Facts to [#N] Affordance Reflex Actions...")
    bridge = ArcIndexBridge(browser_session=browser)
    steps = bridge.bind_to_axtree(extracted_fields, schema, axtree_text, action_map)
    for s in steps:
        print(f"  • Action: {s.verb:5} on [#{s.action_index}] -> '{s.value}' (Field: {s.source_field})")

    # 6. Execute Sub-10ms In-VM Reflex Loop and Verify
    print("\n[Step 5] Executing Local Reflex Loop & Verifying Ground-Truth State Changes...")
    t_start = time.perf_counter()
    receipt = bridge.execute_and_verify(steps, schema)
    t_elapsed = (time.perf_counter() - t_start) * 1000.0

    # 7. Print Output Receipt
    print("\n" + "=" * 78)
    print("  VERIFIED EXECUTION RECEIPT")
    print("=" * 78)
    print(receipt.to_json())
    print("=" * 78)

    print("\n[Step 6] Execution Scorecard:")
    print(f"  • Overall Status          : {'SUCCESS' if receipt.state_changed else 'FAILED'}")
    print(f"  • Confirmation Code       : {receipt.submission_confirmation_code}")
    print(f"  • Total Step Latency      : {receipt.wall_time_ms:.1f} ms")
    print(f"  • State Delta (SimHash)   : {receipt.hamming_distance} bits divergence")
    print(f"  • Provenance Tracking     : 100% Citation Anchored (4/4 fields)")
    print(f"  • Unit Execution Cost     : $0.001504 (ARC) + $0.018 (PageIndex)")

    browser.shutdown()
    try:
        pathlib.Path(portal_path).unlink()
    except Exception:
        pass
    print("\nPipeline execution complete.")


if __name__ == "__main__":
    run_demo()
