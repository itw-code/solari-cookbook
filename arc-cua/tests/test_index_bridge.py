"""Unit tests for ARC Index bridge module (Document-to-Action)."""

import pytest

from arc_index.index_bridge import (
    ArcIndexBridge,
    CitationAnchor,
    CompiledActionStep,
    DocumentActionSchema,
    ExtractedField,
    FieldTarget,
    VerificationReceipt,
)


def test_citation_parsing_variants():
    text_modern = (
        'The patient claim number is 98214-A <cite doc="denial.pdf" page="2" block="b-14"/> '
        'and the primary diagnosis code was CPT-99214 <cite doc="denial.pdf" page="3"/>.'
    )
    cites = ArcIndexBridge.parse_citations(text_modern)
    assert len(cites) == 2
    assert cites[0].document == "denial.pdf"
    assert cites[0].page == 2
    assert cites[0].block_id == "b-14"
    assert cites[1].page == 3
    assert cites[1].block_id is None

    # Legacy syntax
    text_legacy = 'Payment was rejected under code CO-16 <doc=claim_eob.pdf;page=4;block=diag_table>.'
    legacy_cites = ArcIndexBridge.parse_citations(text_legacy)
    assert len(legacy_cites) == 1
    assert legacy_cites[0].document == "claim_eob.pdf"
    assert legacy_cites[0].page == 4
    assert legacy_cites[0].block_id == "diag_table"


def test_axtree_affordance_binding():
    bridge = ArcIndexBridge()
    schema = DocumentActionSchema(
        schema_id="healthcare_denial_appeal",
        target_url_pattern="https://payer-portal.example.com/appeal",
        fields=[
            FieldTarget(field_name="claim_id", target_role="textbox", label_hints=["Claim ID", "Claim #"], input_verb="FILL"),
            FieldTarget(field_name="denial_code", target_role="textbox", label_hints=["Denial Reason", "Denial Code"], input_verb="FILL"),
            FieldTarget(field_name="cpt_code", target_role="textbox", label_hints=["Procedure", "CPT"], input_verb="FILL"),
        ],
    )

    action_map = {
        1: {"index": 1, "role": "textbox", "name": "Patient Full Name", "css": "#name"},
        2: {"index": 2, "role": "textbox", "name": "Insurance Claim ID", "css": "#claim_num"},
        3: {"index": 3, "role": "textbox", "name": "Denial Code (e.g. CO-16)", "css": "#denial_ref"},
        4: {"index": 4, "role": "textbox", "name": "CPT Procedure Code", "css": "#cpt"},
        5: {"index": 5, "role": "button", "name": "Submit Appeal Request", "css": "#submit"},
    }

    extracted = [
        ExtractedField(
            field_name="claim_id",
            value="CLM-2026-9912",
            citation=CitationAnchor(document="denial.pdf", page=1, block_id="b1"),
        ),
        ExtractedField(
            field_name="denial_code",
            value="CO-16",
            citation=CitationAnchor(document="denial.pdf", page=2, block_id="b4"),
        ),
        ExtractedField(
            field_name="cpt_code",
            value="99214",
            citation=CitationAnchor(document="denial.pdf", page=2, block_id="b5"),
        ),
    ]

    steps = bridge.bind_to_axtree(extracted, schema, "", action_map)
    assert len(steps) == 3
    assert steps[0].action_index == 2
    assert steps[0].value == "CLM-2026-9912"
    assert steps[0].verb == "FILL"
    assert steps[1].action_index == 3
    assert steps[1].value == "CO-16"
    assert steps[2].action_index == 4
    assert steps[2].value == "99214"


def test_verification_receipt_serialization():
    receipt = VerificationReceipt(
        receipt_id="rcpt_test_12345",
        document_name="appeal_form.pdf",
        schema_id="rcm_appeal",
        fields_submitted={"claim_id": "CLM-101", "denial_code": "CO-16"},
        citations=[{"document": "appeal_form.pdf", "page": 1, "block_id": "b1"}],
        submission_confirmation_code="CONF-88912-TX",
        state_changed=True,
        hamming_distance=8,
        wall_time_ms=18.4,
        solari_session_id="slr_sess_99812",
        timestamp="2026-09-29T06:00:00Z",
    )
    json_str = receipt.to_json()
    assert "CONF-88912-TX" in json_str
    assert "CLM-101" in json_str
    assert "rcpt_test_12345" in json_str


# ---- Phase 1-4 additions ---------------------------------------------------

import pathlib
import re

from arc_index.index_bridge import load_schema

PORTAL = """<html><body><form onsubmit="event.preventDefault();
document.getElementById('form').style.display='none';document.getElementById('ok').style.display='block'" id="form">
<label for="a">Insurance Claim ID</label><input id="a">
<label for="b">Denial Reason Code</label><input id="b">
<label for="c">CPT Procedure Code</label><input id="c">
<button type="submit">Submit Appeal Request</button></form>
<div id="ok" style="display:none">Appeal Accepted! Confirmation Reference: CONF-2026-99812-TX</div></body></html>"""

LLM_REPLY = """- claim_id: CLM-98214-A <cite doc="denial.pdf" page="2" block="b4"/>
- denial_code: CO-16 <cite doc="denial.pdf" page="4" block="remark_1"/>
- cpt_code: 99214 <cite doc="denial.pdf" page="2" block="row_2"/>
"""


class FakePageIndex:
    def submit_document(self, path, wait=True):
        return {"doc_id": "doc-1"}

    def get_document_structure(self, doc_id):
        return [{"title": "Denial", "pages": 6}]

    def chat(self, prompt, doc_id=None):
        return LLM_REPLY


def test_builtin_schemas_load():
    for sid in ("healthcare_denial_appeal", "invoice_entry"):
        schema = load_schema(sid)
        assert schema.schema_id == sid and schema.fields
    with pytest.raises(ValueError):
        load_schema("nope")


def test_parse_extracted_fields_rejects_uncited():
    schema = load_schema("healthcare_denial_appeal")
    fields = ArcIndexBridge._parse_extracted_fields(LLM_REPLY + "- notes: made up\n", schema, "denial.pdf")
    by = {f.field_name: f for f in fields}
    assert by["claim_id"].citation.block_id == "b4" and by["claim_id"].validation_status
    assert not by["notes"].validation_status

    # ungrounded fields are never bound to the browser
    steps = ArcIndexBridge().bind_to_axtree(
        [by["notes"]], schema, "", {1: {"role": "textbox", "name": "Appeal Notes"}})
    assert steps == []


def test_confirmation_scrape_ignores_plain_words():
    schema = load_schema("healthcare_denial_appeal")
    code = ArcIndexBridge._scrape_confirmation("Appeal Accepted! Confirmation Reference: CONF-2026-99812-TX", schema)
    assert code == "CONF-2026-99812-TX"
    assert ArcIndexBridge._scrape_confirmation("Submit Appeal Request", schema) is None


def test_mcp_tools_registered():
    import asyncio
    from arc_cua.mcp_server import build_server
    server, _ = build_server(pageindex_factory=lambda mode: FakePageIndex())
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert {"arc_index_document", "arc_index_query", "arc_doc_to_action"} <= names


def test_end_to_end_local_chromium(tmp_path):
    from arc_cua.browser_session import BrowserSession
    html = tmp_path / "portal.html"
    html.write_text(PORTAL, encoding="utf-8")
    try:
        browser = BrowserSession()
        browser.open(html.resolve().as_uri())
    except Exception as e:  # no Chromium in this environment
        pytest.skip(f"browser unavailable: {e}")
    try:
        bridge = ArcIndexBridge(FakePageIndex(), browser)
        schema = load_schema("healthcare_denial_appeal")
        doc_id = bridge.ingest_document("denial.pdf")
        fields = bridge.extract_action_fields(doc_id, schema, "denial.pdf")
        inspect = browser.inspect()
        steps = bridge.bind_to_axtree(fields, schema, inspect["text"], inspect["action_index_map"])
        assert {s.source_field for s in steps} == {"claim_id", "denial_code", "cpt_code"}
        receipt = bridge.execute_and_verify(steps, schema, document_name="denial.pdf")
        assert receipt.state_changed
        assert receipt.submission_confirmation_code == "CONF-2026-99812-TX"
        pages = {(c["page"], c["block_id"]) for c in receipt.citations}
        assert pages == {(2, "b4"), (4, "remark_1"), (2, "row_2")}
    finally:
        browser.shutdown()


# ---- grounding check (local doc index) ------------------------------------

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "documents"


def _cms_index():
    pytest.importorskip("pypdf")
    from arc_index.local_doc_index import LocalDocIndexClient

    class Canned:
        def complete(self, system, user):
            return {"text": self.reply, "input_tokens": 0, "output_tokens": 0}

    chat = Canned()
    client = LocalDocIndexClient(chat=chat)
    doc_id = client.submit_document(str(FIXTURES / "cms_fiss_spr_example.pdf"))["doc_id"]
    return client, chat, doc_id


def test_block_lookup_accepts_dropped_b_prefix():
    client, _, doc_id = _cms_index()
    assert client.value_in_block(doc_id, "p1_b22", "1EG4TE5MK72")
    assert client.value_in_block(doc_id, "p1_22", "1EG4TE5MK72")
    assert not client.value_in_block(doc_id, "p1_b21", "1EG4TE5MK72")


def test_grounding_needs_an_evidence_quote_on_the_cited_page():
    client, chat, doc_id = _cms_index()
    mbi_line = client.block_text(doc_id, "p1_b22")
    chat.reply = (
        f'- mbi: 1EG4TE5MK72 | evidence: {mbi_line} <cite doc="x" page="1" block="p1_b22"/>\n'
        '- patient_name: SMITH J <cite doc="x" page="1" block="p1_b22"/>\n'             # no quote
        '- from_date: 10/01/2018 | evidence: FROM DT 10/01/2018 <cite doc="x" page="2"/>\n'  # no page 2
        f'- thru_date: 10/31/2018 | evidence: {mbi_line} <cite doc="x" page="1"/>\n'   # not in quote
        '- reason_code: NOT_FOUND\n'
        '- remark_code: AMBIGUOUS\n'
    )
    fields = {f.field_name: f for f in
              ArcIndexBridge(client).extract_action_fields(doc_id, load_schema("medicare_redetermination"))}
    assert fields["mbi"].validation_status and fields["mbi"].citation.text_snippet == mbi_line
    assert fields["mbi"].citation.block_id == "p1_b22"
    assert fields["patient_name"].error_message == "no evidence quote"
    assert fields["from_date"].error_message == "evidence quote not on cited page 2"
    assert fields["thru_date"].error_message == "value not in its evidence quote"
    assert fields["reason_code"].error_message == "not found in document"
    assert fields["remark_code"].error_message == "more than one value fits"


def test_parse_evidence_with_citation_before_or_after():
    schema = load_schema("healthcare_denial_appeal")
    reply = ('cpt_code: **99214** | evidence: "2 2026-06-14 99214 Office visit" <cite doc="d" page="2"/>\n'
             'claim_id: CLM-1 <cite doc="d" page="1"/> | Evidence: Claim number: CLM-1\n')
    by = {f.field_name: f for f in ArcIndexBridge._parse_extracted_fields(reply, schema, "d")}
    assert (by["cpt_code"].value, by["cpt_code"].evidence) == ("99214", "2 2026-06-14 99214 Office visit")
    assert (by["claim_id"].value, by["claim_id"].evidence) == ("CLM-1", "Claim number: CLM-1")


# ---- evidence rules on the synthetic letter (paid line + decoy claim) ---------

PAID_ROW = "1 2026-06-14 36415Routine venipuncture $18.00 $11.40 Paid"
DENIED_ROW = "2 2026-06-14 99214Office visit, established patient, moderate MDM $412.00$0.00 Denied"


def _letter(reply, schema=None, pdf="synthetic_denial_letter.pdf"):
    pytest.importorskip("pypdf")
    from arc_index.local_doc_index import LocalDocIndexClient

    class Canned:
        def complete(self, system, user):
            return {"text": reply, "input_tokens": 0, "output_tokens": 0}

    client = LocalDocIndexClient(chat=Canned())
    doc_id = client.submit_document(str(FIXTURES / pdf))["doc_id"]
    schema = schema or load_schema("healthcare_denial_appeal")
    return {f.field_name: f for f in ArcIndexBridge(client).extract_action_fields(doc_id, schema)}


def test_evidence_must_match_rejects_the_paid_line_even_with_a_trimmed_quote():
    f = _letter(f'cpt_code: 36415 | evidence: {PAID_ROW} <cite doc="d" page="2" block="p2_b4"/>\n'
                'billed_amount: $18.00 | evidence: $18.00 <cite doc="d" page="2" block="p2_b4"/>\n')
    assert f["cpt_code"].error_message == r"source row does not match /(?i)\bdenied\b/"
    # The quote omits "Paid", but the rule is checked on the whole source line, not the quote.
    assert not f["billed_amount"].validation_status


def test_evidence_must_not_match_rejects_the_unaffected_claim():
    f = _letter('claim_id: CLM-2026-448790 | evidence: CLM-2026-448790 <cite doc="d" page="1" block="p1_b12"/>\n')
    assert "source row matches" in f["claim_id"].error_message


def test_same_row_as_rejects_fields_from_different_rows():
    # Without the Denied/Paid and row rules, only the cross-field check stands between 36415 and the portal.
    schema = load_schema("healthcare_denial_appeal")
    for spec in schema.fields:
        spec.evidence_must_match = spec.evidence_must_not_match = spec.row_start = None
    f = _letter(f'cpt_code: 36415 | evidence: {PAID_ROW} <cite doc="d" page="2"/>\n'
                f'billed_amount: $412.00 | evidence: {DENIED_ROW} <cite doc="d" page="2"/>\n', schema)
    assert f["cpt_code"].error_message == "source row does not contain billed_amount ($412.00)"
    assert f["billed_amount"].error_message == "source row does not contain cpt_code (36415)"


def test_receipt_snippet_is_the_row_the_value_came_from():
    # 2026-06-14 is on both rows; the old check cited the first line containing it (the paid row).
    f = _letter(f'date_of_service: 2026-06-14 | evidence: {DENIED_ROW} <cite doc="d" page="2" block="p2_b4"/>\n'
                f'cpt_code: 99214 | evidence: {DENIED_ROW} <cite doc="d" page="2" block="p2_b5"/>\n'
                f'billed_amount: $412.00 | evidence: {DENIED_ROW} <cite doc="d" page="2" block="p2_b6"/>\n')
    for name in ("date_of_service", "cpt_code", "billed_amount"):
        c = f[name].citation
        assert f[name].validation_status, f[name].error_message
        assert c.text_snippet == "2 2026-06-14 99214Office visit, established patient, moderate MDM $412.00$0.00 Denied"
        assert c.block_id == "p2_b5..p2_b6"            # the verified lines, not the id the model wrote


TWO_DENIED = "synthetic_denial_letter_two_denied.pdf"
ECG_ROW = "3 2026-06-14 93000Electrocardiogram, routine, with interpretation $96.00 $0.00 Denied"


@pytest.mark.parametrize("cpt,billed,row", [("99214", "$412.00", DENIED_ROW.replace("99214", "99214 ")),
                                            ("93000", "$96.00", ECG_ROW)])
def test_two_denied_rows_reject_a_confident_pick(cpt, billed, row):
    # The model picks one denied row instead of answering AMBIGUOUS. That row passes Denied /
    # not Paid and holds the other field, so only the uniqueness rule keeps the pick out.
    f = _letter(f'cpt_code: {cpt} | evidence: {row} <cite doc="d" page="2"/>\n'
                f'billed_amount: {billed} | evidence: {row} <cite doc="d" page="2"/>\n'
                f'date_of_service: 2026-06-14 | evidence: {row} <cite doc="d" page="2"/>\n', pdf=TWO_DENIED)
    assert f["cpt_code"].error_message == "2 rows fit: 93000 / 99214"
    assert f["billed_amount"].error_message == "2 rows fit: $0.00, $412.00 / $0.00, $96.00"
    assert f["date_of_service"].validation_status     # both denied rows have the same date: not ambiguous


def test_two_denied_rows_are_accepted_without_the_row_rule():
    schema = load_schema("healthcare_denial_appeal")
    for spec in schema.fields:
        spec.row_start = None
    f = _letter(f'cpt_code: 93000 | evidence: {ECG_ROW} <cite doc="d" page="2"/>\n', schema, pdf=TWO_DENIED)
    assert f["cpt_code"].validation_status             # what the uniqueness rule is there to stop


def test_evidence_outside_a_table_row_is_rejected():
    f = _letter('cpt_code: 99214 | evidence: 99214Office visit, established patient, moderate MDM $412.00$0.00 '
                'Denied Line 1 was paid <cite doc="d" page="2"/>\n')
    assert f["cpt_code"].error_message == "evidence quote is not within one table row on page 2"


def test_a_partial_quote_is_checked_against_its_whole_row():
    f = _letter('cpt_code: 99214 | evidence: 99214Office visit <cite doc="d" page="2"/>\n')
    assert f["cpt_code"].validation_status, f["cpt_code"].error_message
    assert f["cpt_code"].citation.text_snippet == DENIED_ROW


# ---- batched fills ----------------------------------------------------------

FORM = """<form>
<label for=a>Claim ID</label><input id=a name=a>
<label>Notes<textarea name=n></textarea></label>
<label>Code<select name=s><option value="">-</option><option value="co16">CO-16</option></select></label>
<label>Locked<input name=l disabled></label>
<label>Upper<input name=u oninput="this.value=this.value.toUpperCase()"></label>
<label>Date<input type=date name=d></label>
<button>Submit</button></form>
<script>window.events=[];document.addEventListener('input',e=>events.push(e.target.name),true)</script>"""


@pytest.fixture
def form_browser():
    from arc_cua.browser_session import BrowserSession
    browser = BrowserSession()
    try:
        browser.open("about:blank")
    except Exception as e:
        pytest.skip(f"browser unavailable: {e}")
    browser.page.set_content(FORM)
    yield browser
    browser.shutdown()


def _idx(browser, name):
    m = browser.inspect(settle_ms=300)["action_index_map"]
    return next(i for i, v in m.items() if v["name"] == name)


def test_fill_many_fills_and_reports_each_field(form_browser):
    b = form_browser
    m = b.inspect(settle_ms=300)["action_index_map"]
    by = {v["name"]: i for i, v in m.items()}
    out = b.fill_many([(by["Claim ID"], "CLM-1"), (by["Notes"], "two\nlines"), (by["Code"], "CO-16"),
                       (by["Locked"], "x"), (by["Upper"], "abc"), (by["Day Day"], "14")])
    r = {}
    for x in out["results"]:
        r.setdefault(x["index"], []).append(x)
    assert not out["stale"] and out["state_changed"]
    assert r[by["Claim ID"]][0]["ok"] and r[by["Notes"]][0]["ok"]
    assert r[by["Code"]][0]["ok"] and b.page.eval_on_selector("select", "e => e.value") == "co16"
    assert "disabled" in r[by["Locked"]][0]["error"]
    assert not r[by["Upper"]][0]["ok"] and "did not stick" in r[by["Upper"]][0]["error"]  # read back
    assert "no DOM path" in r[by["Day Day"]][0]["error"]             # shadow DOM: not batched
    assert {"a", "n", "u"} <= set(b.page.evaluate("window.events"))  # frameworks see input events


def test_fill_many_refuses_stale_page(form_browser):
    b = form_browser
    idx = _idx(b, "Claim ID")
    b.page.evaluate("document.body.insertAdjacentHTML('afterbegin', '<button>New</button>')")
    out = b.fill_many([(idx, "CLM-1")])
    assert out["stale"] and out["results"] == []
    assert b.page.input_value("#a") == ""


def test_bridge_batches_and_falls_back(form_browser):
    b = form_browser
    m = b.inspect(settle_ms=300)["action_index_map"]
    by = {v["name"]: i for i, v in m.items()}
    cite = CitationAnchor("d.pdf", 1, "p1_b1")
    steps = [CompiledActionStep(by["Claim ID"], "FILL", "CLM-9", "claim_id", cite),
             CompiledActionStep(by["Notes"], "FILL", "why", "notes", cite),
             CompiledActionStep(by["Day Day"], "FILL", "14", "day", cite)]
    schema = DocumentActionSchema("t", "*", [], submit_affordance_hint="Nope")
    receipt = ArcIndexBridge(browser_session=b).execute_and_verify(steps, schema)
    log = {s["field"]: s for s in receipt.step_log}
    assert log["claim_id"]["batched"] and log["notes"]["batched"]
    assert not log["day"].get("batched")               # no DOM path: retried with act
    assert b.page.input_value("#a") == "CLM-9"


# ---- PageIndex adapter (page-level grounding) -------------------------------


class FakePageIndexSDK:
    """Shape of pageindex.PageIndexClient for the calls the adapter makes."""

    def __init__(self, reply):
        self.reply, self.chat_kwargs = reply, None

    def chat(self, prompt, doc_id=None, citations=False):
        self.chat_kwargs = {"doc_id": doc_id, "citations": citations, "prompt": prompt}
        return self.reply

    def get_page_content(self, doc_id, pages):
        text = {"1": "Claim number: CLM-7\nMember: Ana Ruiz", "3": "Reason: CO-16 lacks\ninformation for review"}
        return [{"page_index": int(pages), "markdown": text.get(pages, "")}]


def test_pageindex_adapter_grounds_on_cited_page():
    from arc_index.pageindex_adapter import PageIndexAdapter
    sdk = FakePageIndexSDK(
        '- claim_id: CLM-7 | evidence: Claim number: CLM-7 <cite doc="d.pdf" page="1" block="made_up"/>\n'
        '- patient_name: Ana Ruiz | evidence: Member: Ana Ruiz <cite doc="d.pdf" page="3"/>\n'   # wrong page
        '- notes: CO-16 lacks information | evidence: Reason: CO-16 lacks information for review'
        ' <cite doc="d.pdf" page="3"/>\n'                                                          # wraps a line
    )
    schema = DocumentActionSchema("s", "*", [
        FieldTarget("claim_id", "textbox", ["Claim"]),
        FieldTarget("patient_name", "textbox", ["Patient"]),
        FieldTarget("notes", "textbox", ["Notes"]),
    ])
    fields = {f.field_name: f for f in
              ArcIndexBridge(PageIndexAdapter(sdk)).extract_action_fields("doc-1", schema, "d.pdf")}
    assert sdk.chat_kwargs["citations"] is True and "block=" not in sdk.chat_kwargs["prompt"]
    assert fields["claim_id"].validation_status
    assert fields["claim_id"].citation.block_id is None           # page-level index: no block ids
    assert fields["claim_id"].citation.text_snippet == "Claim number: CLM-7"
    assert not fields["patient_name"].validation_status
    assert fields["patient_name"].error_message == "evidence quote not on cited page 3"
    assert fields["notes"].validation_status
    assert fields["notes"].citation.text_snippet == "Reason: CO-16 lacks information for review"
