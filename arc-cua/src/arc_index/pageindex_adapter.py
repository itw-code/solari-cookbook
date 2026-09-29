"""ArcIndexBridge adapter for the real PageIndex SDK (`pip install pageindex`).

Local mode needs no PageIndex account: Flash builds the document tree from the PDF layout,
and summaries plus the answering agent run on your own model through LiteLLM (for example
`gemini/gemini-3.8-flash` with GEMINI_API_KEY). Local page content has no layout blocks, so
citations are page-level: `page_lines` gives the bridge the cited page's lines for its evidence
check, and `verify_citation` (the older presence check) looks for the value on that page.
Cloud documents (api_key / PAGEINDEX_API_KEY) have blocks, but block-level checking is not
wired up here: the same page-level check is used, since it is the one path that has been run.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from arc_index.index_bridge import CitationAnchor

DEFAULT_MODEL = "gemini/gemini-3.8-flash"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


class PageIndexAdapter:
    """Wraps `pageindex.PageIndexClient` in the calls ArcIndexBridge makes."""

    cites_blocks = False  # local PageIndex cites pages only

    def __init__(self, client: Any = None, model: str = DEFAULT_MODEL, storage_path: Optional[str] = None):
        if client is None:
            try:
                from pageindex import PageIndexClient
            except ImportError as e:
                raise RuntimeError("PageIndex is not installed: pip install pageindex") from e
            kwargs: Dict[str, Any] = {"model": model}
            if storage_path:
                kwargs["storage_path"] = storage_path
            client = PageIndexClient(**kwargs)
        self.client = client
        self._pages: Dict[tuple, str] = {}

    def submit_document(self, file_path: str, wait: bool = True) -> Dict[str, Any]:
        return self.client.submit_document(file_path, wait=wait)

    def get_document_structure(self, doc_id: str) -> List[Dict[str, Any]]:
        return self.client.get_document_structure(doc_id)

    def chat(self, prompt: str, doc_id: Optional[str] = None) -> str:
        return self.client.chat(prompt, doc_id=doc_id, citations=True)

    def page_text(self, doc_id: str, page: int) -> str:
        key = (doc_id, page)
        if key not in self._pages:
            content = self.client.get_page_content(doc_id, str(page))
            self._pages[key] = "\n".join(p.get("markdown") or p.get("content") or "" for p in content)
        return self._pages[key]

    def page_lines(self, doc_id: str, page: int) -> List[Tuple[Optional[str], str]]:
        """(None, text) for each line of a page: page-level, so lines carry no block id."""
        return [(None, ln) for ln in self.page_text(doc_id, page).splitlines() if ln.strip()]

    def verify_citation(self, doc_id: str, citation: CitationAnchor, value: str) -> Optional[str]:
        """The line of the cited page that contains the value, or None if the page lacks it."""
        want = _norm(value)
        if not want or citation.page < 1:
            return None
        text = self.page_text(doc_id, citation.page)
        for line in text.splitlines():
            if want in _norm(line):
                return line.strip()
        # A value that wraps across lines (a sentence): match with whitespace collapsed.
        flat = re.sub(r"\s+", " ", text)
        i = flat.lower().find(re.sub(r"\s+", " ", value.strip()).lower())
        if i >= 0:
            return flat[max(0, i - 40): i + len(value) + 40].strip()
        return None
