"""ARC Index's MCP tools: index a document, query it with citations, and turn it into a verified form fill.

A plugin for ARC CUA's MCP server (`arc_cua.mcp_server.build_server`), which loads it when
`arc_index` is importable. The tools share the server's browser worker, so `arc_doc_to_action`
fills the page `arc_open` opened.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
from typing import Any, Callable, Literal, Optional

from mcp.server.mcpserver.exceptions import ToolError

from arc_cua.browser_session import BrowserSession
from arc_cua.mcp_server import _json
from arc_index.index_bridge import ArcIndexBridge, load_schema


def default_pageindex_client(mode: str = "local") -> Any:
    """Build a PageIndex client lazily; `pageindex` is an optional dependency.

    local: documents indexed on this machine, models via LiteLLM (ARC_INDEX_MODEL, default
    gemini/gemini-3.8-flash with GEMINI_API_KEY). cloud: PAGEINDEX_API_KEY.
    """
    from arc_index.pageindex_adapter import DEFAULT_MODEL, PageIndexAdapter
    try:
        from pageindex import PageIndexClient  # type: ignore
    except ImportError as e:
        raise ToolError("PageIndex is not installed: pip install pageindex") from e
    model = os.environ.get("ARC_INDEX_MODEL", DEFAULT_MODEL)
    client = PageIndexClient(index="cloud", chat_model=model) if mode == "cloud" else PageIndexClient(model=model)
    return PageIndexAdapter(client)


def register(server: Any, worker: Any, pageindex_factory: Optional[Callable[[str], Any]] = None) -> None:
    """Add arc_index_document, arc_index_query and arc_doc_to_action to `server`."""
    factory = pageindex_factory or default_pageindex_client
    _pi: dict = {}

    def pageindex(mode: str = "local") -> Any:
        if mode not in _pi:
            _pi[mode] = factory(mode)
        return _pi[mode]

    @server.tool()
    async def arc_index_document(file_path: str, mode: Literal["local", "cloud"] = "local") -> str:
        """Ingest a PDF/document into PageIndex (vectorless tree index). Returns doc_id and the tree structure."""
        def go() -> dict:
            bridge = ArcIndexBridge(pageindex(mode))
            doc_id = bridge.ingest_document(file_path)
            return {"doc_id": doc_id, "structure": bridge.pageindex.get_document_structure(doc_id)}
        try:
            return _json(await asyncio.to_thread(go))
        except ToolError:
            raise
        except Exception as e:
            raise ToolError(f"{type(e).__name__}: {e}") from e

    @server.tool()
    async def arc_index_query(doc_id: str, query: str, target_fields: Optional[list[str]] = None) -> str:
        """Reasoning search over a document tree; answers carry <cite doc page block/> citations.

        target_fields: optional field names to extract, one `name: value <cite/>` line each.
        """
        prompt = query
        if target_fields:
            prompt += ("\nReturn one line per field as `field_name: value <cite doc=\"..\" page=\"..\" block=\"..\"/>`: "
                       + ", ".join(target_fields))
        try:
            text = await asyncio.to_thread(lambda: pageindex().chat(prompt, doc_id=doc_id))
        except Exception as e:
            raise ToolError(f"{type(e).__name__}: {e}") from e
        cites = [c.to_dict() for c in ArcIndexBridge.parse_citations(text, doc_id)]
        return _json({"answer": text, "citations": cites})

    @server.tool()
    async def arc_doc_to_action(
        doc_id: str,
        schema_id: str = "healthcare_denial_appeal",
        auto_submit: bool = False,
    ) -> str:
        """Extract fields from an indexed document, bind them to the open page's form, fill it, and
        return an audit receipt. schema_id: healthcare_denial_appeal, invoice_entry, or a JSON path.
        Open the target form with arc_open first. Nothing is submitted unless auto_submit=true."""
        try:
            schema = load_schema(schema_id)
            fields = await asyncio.to_thread(
                lambda: ArcIndexBridge(pageindex()).extract_action_fields(doc_id, schema))
        except ToolError:
            raise
        except Exception as e:
            raise ToolError(f"{type(e).__name__}: {e}") from e
        ungrounded = [f.field_name for f in fields if not f.validation_status]

        def go(session: BrowserSession) -> dict:
            bridge = ArcIndexBridge(pageindex(), session)
            inspect = session.inspect()
            steps = bridge.bind_to_axtree(fields, schema, inspect["text"], inspect["action_index_map"])
            receipt = bridge.execute_and_verify(steps, schema, submit=auto_submit)
            return {"receipt": dataclasses.asdict(receipt), "ungrounded_fields": ungrounded,
                    "unbound_fields": sorted({f.field_name for f in fields if f.validation_status}
                                             - {s.source_field for s in steps})}
        return _json(await worker.run(go))
