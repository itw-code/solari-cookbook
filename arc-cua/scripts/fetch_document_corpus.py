"""Fetch the public test documents for the ARC Index live run and check they are real PDFs.

A failed download is an error, never a placeholder file: a fake PDF would let the live run
"pass" without reading anything. The synthetic letter is not fetched; it is rendered by
scripts/make_denial_fixture.py.

Run: python scripts/fetch_document_corpus.py
"""

from __future__ import annotations

import io
import pathlib
import sys
import urllib.request

import pypdf

DOCS = pathlib.Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "documents"

# Only documents whose ground truth has been read off the file itself (see *.truth.json).
CORPUS = {
    "MED-CMS-01": {
        "url": "https://www.cms.gov/Outreach-and-Education/Medicare-Learning-Network-MLN/MLNGenInfo/Downloads/FISS-SPR-Example.pdf",
        "filename": "cms_fiss_spr_example.pdf",
        "pages": 1,
    },
}


def fetch(doc_id: str, spec: dict) -> pathlib.Path:
    path = DOCS / spec["filename"]
    if not path.exists():
        req = urllib.request.Request(spec["url"], headers={"User-Agent": "Mozilla/5.0 ARC-CUA-corpus"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        pypdf.PdfReader(io.BytesIO(data))  # raises if this is not a PDF
        DOCS.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    pages = len(pypdf.PdfReader(str(path)).pages)
    if pages != spec["pages"]:
        raise RuntimeError(f"{doc_id}: expected {spec['pages']} page(s), file has {pages}")
    return path


def main() -> int:
    failed = 0
    for doc_id, spec in CORPUS.items():
        try:
            path = fetch(doc_id, spec)
            print(f"ok   {doc_id} {path.name} ({path.stat().st_size} bytes)")
        except Exception as e:
            failed += 1
            print(f"FAIL {doc_id}: {type(e).__name__}: {e}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
