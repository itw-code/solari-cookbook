"""Local stand-in for the PageIndex client, for runs without a PageIndex key.

Same three calls ArcIndexBridge uses (`submit_document`, `get_document_structure`, `chat`),
but the "tree" is just pages -> text lines from pypdf, and `chat` sends the whole block-tagged
text to an OpenAI-compatible model (Gemini by default). This is not PageIndex's tree search:
it only works for documents that fit in one prompt. What it does give is a real citation
check, because every block id the model cites can be looked up and compared with the value.
"""

from __future__ import annotations

import os
import pathlib
import re
from typing import Any, Dict, List, Optional, Tuple

from arc_cua.reflex_policy import ChatClient

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"

SYSTEM = """\
You extract fields from a document. The document is given as blocks, one per line, in the form
[p<page>_b<block>] <text>. Answer only from the document. For each requested field output exactly
one line: field_name: value | evidence: QUOTE <cite doc="DOC" page="P" block="pP_bB"/>
Cite the block that contains the value. Copy the value as written in that block. QUOTE is the
whole table row or sentence the value is in, copied verbatim without the [block] tags, from its
first cell to its last. A table row is often split over two or more consecutive blocks: quote
all of them, not just the block holding the value.
If a field is not in the document, output: field_name: NOT_FOUND
If more than one different value fits a field, output: field_name: AMBIGUOUS
"""


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


class LocalDocIndexClient:
    """PageIndex-shaped client over pypdf text blocks and a chat model."""

    def __init__(self, chat: Optional[ChatClient] = None, model: str = "gemini-3.8-flash"):
        if chat is None:
            key = os.environ.get("GEMINI_API_KEY")
            if not key:
                raise RuntimeError("GEMINI_API_KEY is not set (or pass chat=ChatClient(...)).")
            chat = ChatClient(GEMINI_BASE_URL, key, model, timeout=90.0, max_tokens=16384,
                              extra={"reasoning_effort": "low"})
        self.chat_client = chat
        self._docs: Dict[str, Dict[str, Any]] = {}
        self.usage = {"input_tokens": 0, "output_tokens": 0}

    def submit_document(self, file_path: str, wait: bool = True) -> Dict[str, Any]:
        import pypdf

        path = pathlib.Path(file_path)
        reader = pypdf.PdfReader(str(path))
        pages: List[Dict[str, Any]] = []
        for n, page in enumerate(reader.pages, 1):
            lines = [ln.strip() for ln in (page.extract_text() or "").splitlines() if ln.strip()]
            pages.append({"page": n, "blocks": {f"p{n}_b{k}": ln for k, ln in enumerate(lines, 1)}})
        doc_id = path.name
        self._docs[doc_id] = {"name": path.name, "pages": pages}
        return {"doc_id": doc_id}

    def get_document_structure(self, doc_id: str) -> List[Dict[str, Any]]:
        return [{"page": p["page"], "blocks": len(p["blocks"]),
                 "first_line": next(iter(p["blocks"].values()), "")} for p in self._docs[doc_id]["pages"]]

    def block_text(self, doc_id: str, block_id: str) -> Optional[str]:
        # Models sometimes drop the "b" ("p1_18" for "p1_b18"); the id still names one block.
        block_id = re.sub(r"^p(\d+)_(\d+)$", r"p\1_b\2", block_id.strip())
        for p in self._docs.get(doc_id, {}).get("pages", []):
            if block_id in p["blocks"]:
                return p["blocks"][block_id]
        return None

    def page_lines(self, doc_id: str, page: int) -> List[Tuple[Optional[str], str]]:
        """(block id, text) for each line of a page, for the bridge's evidence check."""
        for p in self._docs.get(doc_id, {}).get("pages", []):
            if p["page"] == page:
                return list(p["blocks"].items())
        return []

    def chat(self, prompt: str, doc_id: Optional[str] = None) -> str:
        doc = self._docs[doc_id]
        body = "\n".join(f"[{bid}] {text}" for p in doc["pages"] for bid, text in p["blocks"].items())
        user = f"Document: {doc['name']}\n\n{body}\n\nTask:\n{prompt}"
        out = self.chat_client.complete(SYSTEM.replace("DOC", doc["name"]), user)
        self.usage["input_tokens"] += out["input_tokens"]
        self.usage["output_tokens"] += out["output_tokens"]
        return out["text"]

    def verify_citation(self, doc_id: str, citation: Any, value: str) -> Optional[str]:
        """The cited block's text when it contains the value, else None."""
        if self.value_in_block(doc_id, citation.block_id, value):
            return self.block_text(doc_id, citation.block_id)
        return None

    def value_in_block(self, doc_id: str, block_id: Optional[str], value: str) -> bool:
        """True when the cited block's text contains the value (ignoring case and punctuation)."""
        text = self.block_text(doc_id, block_id) if block_id else None
        return bool(text) and bool(_norm(value)) and _norm(value) in _norm(text)
