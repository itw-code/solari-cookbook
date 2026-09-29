"""ARC Index: documents in, verified actions out.

Built on ARC CUA (`arc_cua`): a document is indexed (PageIndex, or pypdf blocks locally), its
fields are extracted with an evidence quote and a citation, the grounding checks reject any value
not proven at the cited place (evidence quote, row rules, uniqueness), and what is left is bound
to a form's `[#N]` affordances and filled in one batched call through `arc_cua.BrowserSession`.

Depends on `arc_cua`; `arc_cua` does not depend on it (its MCP server loads `arc_index.mcp_tools`
as an optional plugin). Plan and measurements: docs/ARC_INDEX_PLAN.md.
"""

from arc_index.index_bridge import (
    ArcIndexBridge,
    CitationAnchor,
    CompiledActionStep,
    DocumentActionSchema,
    ExtractedField,
    FieldTarget,
    VerificationReceipt,
    load_schema,
)

__all__ = [
    "ArcIndexBridge",
    "CitationAnchor",
    "CompiledActionStep",
    "DocumentActionSchema",
    "ExtractedField",
    "FieldTarget",
    "VerificationReceipt",
    "load_schema",
]
