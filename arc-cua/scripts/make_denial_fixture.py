"""Render the synthetic denial-letter fixture (multi-page PDF with known ground truth).

The facts are spread across pages on purpose: the claim header is on page 1, the CPT line
item on page 2, the CARC denial on page 3 and the appeal ground on page 4, with decoy values
(a second claim number, a paid CPT line) so extraction has to pick the right block.
All names and numbers are fictitious.

Decoy variants (plan section 10) move the decoys around so that "the cited place contains the
value" is not enough to be right:
  swapped    - the denied line comes before the paid line
  two_denied - two denied lines with different CPT codes and amounts: there is no single right
               cpt_code or billed_amount, so truth is null and any accepted value is wrong
  decoy_first - the unaffected claim number is printed first, with its own "Claim number:" label

Run: python scripts/make_denial_fixture.py [--variant NAME ...]
Writes tests/fixtures/documents/synthetic_denial_letter[_<variant>].pdf and ground truth.
"""

from __future__ import annotations

import argparse
import json
import pathlib

from playwright.sync_api import sync_playwright

OUT_DIR = pathlib.Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "documents"

GROUND_TRUTH = {
    "claim_id": {"value": "CLM-2026-448817", "page": 1},
    "patient_name": {"value": "Dana Whitfield", "page": 1},
    "date_of_service": {"value": "2026-06-14", "page": 2},
    "billed_amount": {"value": "$412.00", "page": 2},
    "cpt_code": {"value": "99214", "page": 2},
    "denial_code": {"value": "CO-16", "page": 3},
}

PAID = ("<tr><td>{n}</td><td>2026-06-14</td><td>36415</td><td>Routine venipuncture</td>"
        "<td>$18.00</td><td>$11.40</td><td>Paid</td></tr>")
DENIED = ("<tr><td>{n}</td><td>2026-06-14</td><td>99214</td><td>Office visit, established patient, moderate MDM</td>"
          "<td>$412.00</td><td>$0.00</td><td>Denied</td></tr>")
DENIED_2 = ("<tr><td>{n}</td><td>2026-06-14</td><td>93000</td><td>Electrocardiogram, routine, with interpretation</td>"
            "<td>$96.00</td><td>$0.00</td><td>Denied</td></tr>")

HEADER_BASE = """<p>Claim number: CLM-2026-448817</p>
<p>Rendering provider: Lakeside Family Medicine, NPI 1487702233</p>
<p>This notice explains our decision on the claim listed above. A related claim for this member,
CLM-2026-448790, was processed separately and is not affected by this notice.</p>"""
HEADER_DECOY_FIRST = """<p>Related claim number: CLM-2026-448790 (processed separately, not affected by this notice)</p>
<p>Claim number: CLM-2026-448817</p>
<p>Rendering provider: Lakeside Family Medicine, NPI 1487702233</p>
<p>This notice explains our decision on the claim listed above.</p>"""

# variant -> (claim header, table rows, sentence under the table, truth overrides)
VARIANTS = {
    "base": (HEADER_BASE, [PAID, DENIED],
             "Line 1 was paid under your plan. Line 2 was denied; the reason is explained on the next page.", {}),
    "swapped": (HEADER_BASE, [DENIED, PAID],
                "Line 1 was denied; the reason is explained on the next page. Line 2 was paid under your plan.", {}),
    "two_denied": (HEADER_BASE, [PAID, DENIED, DENIED_2],
                   "Line 1 was paid under your plan. Lines 2 and 3 were denied; the reason is explained on the next page.",
                   {"cpt_code": {"value": None, "page": 2}, "billed_amount": {"value": None, "page": 2}}),
    "decoy_first": (HEADER_DECOY_FIRST, [PAID, DENIED],
                    "Line 1 was paid under your plan. Line 2 was denied; the reason is explained on the next page.", {}),
}

HTML = """<!DOCTYPE html><html><head><style>
body { font-family: Georgia, serif; font-size: 12pt; line-height: 1.45; margin: 0; }
.page { page-break-after: always; padding: 8px 0; }
h1 { font-size: 16pt; } h2 { font-size: 13pt; margin-top: 18px; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; }
td, th { border: 1px solid #555; padding: 4px 6px; font-size: 10.5pt; text-align: left; }
.small { font-size: 9pt; color: #333; }
</style></head><body>

<div class="page">
<h1>Northfield Mutual Health Plan</h1>
<p>Claims Adjudication Department<br>PO Box 7710, Harrow, OH 44102</p>
<p>Date of notice: July 2, 2026</p>
<h2>Notice of Adverse Benefit Determination</h2>
<p>Member: Dana Whitfield<br>Member ID: NMH-5530-2291<br>Group number: GRP-88120</p>
{header}
<p class="small">Keep this letter for your records. It is not a bill.</p>
</div>

<div class="page">
<h2>Explanation of Benefits: Line Items</h2>
<table>
<tr><th>Line</th><th>Date of service</th><th>CPT</th><th>Description</th><th>Billed</th><th>Allowed</th><th>Status</th></tr>
{rows}
</table>
<p>{sentence}</p>
</div>

<div class="page">
<h2>Reason for Denial</h2>
<p>Claim adjustment group and reason code: CO-16. Claim/service lacks information or has
submission/billing error(s) which is needed for adjudication.</p>
<p>Remark code: M127. Missing patient medical record for this service.</p>
<p class="small">Group code CO means the provider may not bill the member for this amount.</p>
</div>

<div class="page">
<h2>Your Right to Appeal</h2>
<p>You or your provider may request a redetermination within 180 days of the date of this notice.
Submit the appeal through the provider appeals portal and include the claim number above.</p>
<p>Basis for reconsideration noted by the provider: the visit note documents moderate medical
decision-making supporting CPT 99214, and the missing medical record will be attached to the appeal.</p>
</div>

</body></html>"""


def render(variant: str) -> tuple:
    header, rows, sentence, overrides = VARIANTS[variant]
    html = (HTML.replace("{header}", header)
            .replace("{rows}", "\n".join(r.format(n=i) for i, r in enumerate(rows, 1)))
            .replace("{sentence}", sentence))
    return html, {**GROUND_TRUTH, **overrides}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", action="append", choices=sorted(VARIANTS),
                    help="repeatable; default: every variant except base (the committed fixture)")
    variants = ap.parse_args().variant or [v for v in VARIANTS if v != "base"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        for variant in variants:
            html, truth = render(variant)
            stem = "synthetic_denial_letter" + ("" if variant == "base" else f"_{variant}")
            page.set_content(html)
            page.pdf(path=str(OUT_DIR / f"{stem}.pdf"), format="Letter",
                     margin={"top": "0.8in", "bottom": "0.8in", "left": "0.9in", "right": "0.9in"})
            (OUT_DIR / f"{stem}.truth.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")
            print(f"wrote {stem}.pdf")
        browser.close()


if __name__ == "__main__":
    main()
