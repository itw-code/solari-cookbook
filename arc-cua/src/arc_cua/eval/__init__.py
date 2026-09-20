"""Evaluation and Benchmarking Module for ARC (Phase 4A & 4B).

Provides:
- Evaluation schemas (EvalTask, EvalAssertion, EvalResult, CostRecord, ScorecardSummary, EvalRunSummary).
- Local synthetic task suite (Phase 4A).
- Success assertion engine (Phase 4A).
- Evaluation runner supporting Reflex-only and Hybrid modes (Phase 4A).
- Cost ledger and scorecard generator (Phase 4A).
- WebArena environment adapter with DatabaseDiffEngine (Phase 4B).
- WebArena task mapper and JSON/JSONL parser (Phase 4B).
- WebArena assertion adapter for url_match, string_match, program_html (Phase 4B).
- WebArena 12-task representative subset suite across 3 domains (Phase 4B).
- WebArena runner integration with Arc HybridRunner (Phase 4B).
"""

from .assertions import (
    check_element_state,
    check_input_value,
    check_page_title,
    check_state_hash_changed,
    check_url,
    check_visible_text,
    evaluate_assertion,
)
from .cost import CostLedger, CostModelConfig
from .runner import EvalCortexClient, EvalRunner, MockEvalLocator, MockEvalPage
from .schemas import (
    AssertionType,
    CostRecord,
    ElementState,
    EvalAssertion,
    EvalAssertionResult,
    EvalResult,
    EvalRunSummary,
    EvalTask,
    ScorecardSummary,
)
from .scorecard import ScorecardBuilder
from .tasks_local import (
    create_local_tasks,
    get_fixture_url,
    get_task_by_id,
    get_tasks_by_category,
)
from .tasks_webarena import (
    RAW_WEBARENA_SUBSET,
    create_webarena_subset,
    get_webarena_task_by_id,
    get_webarena_tasks_by_domain,
)
from .webarena_assertions import (
    WebArenaAssertionAdapter,
    check_webarena_program_html,
    check_webarena_string_match,
    check_webarena_unsupported,
    check_webarena_url_match,
    normalize_text,
    normalize_url,
)
from .webarena_env import (
    DatabaseDiffEngine,
    DatabaseDiffReport,
    DatabaseSnapshot,
    DbRow,
    RowUpdateDiff,
    TableDiff,
    TableSnapshot,
    WebArenaEnv,
)
from .webarena_mapper import (
    build_program_html_assertion,
    build_string_match_assertion,
    build_unsupported_assertion,
    build_url_match_assertion,
    map_webarena_task,
    parse_webarena_json,
    parse_webarena_jsonl,
)
from .webarena_runner import MockWebArenaPage, WebArenaRunner

# Phase 4C
from .osworld_assertions import (
    OSWorldAssertionAdapter,
    check_at_spi_state_match,
    check_file_content_match,
    check_file_exist,
    check_osworld_unsupported,
    check_terminal_output_match,
)
from .osworld_env import OSWorldEnv
from .osworld_mapper import (
    build_at_spi_state_match_assertion,
    build_file_content_match_assertion,
    build_file_exist_assertion,
    build_terminal_output_match_assertion,
    map_osworld_task,
    parse_osworld_json,
    parse_osworld_jsonl,
)
from .osworld_runner import MockOSWorldPage, OSWorldRunner
from .tasks_osworld import (
    RAW_OSWORLD_SUBSET,
    create_osworld_subset,
    get_osworld_task_by_id,
    get_osworld_tasks_by_domain,
)

# Phase 5
from .live_orchestrator import (
    HostCapabilities,
    LIVE_ORCHESTRATION_SKIPPED,
    LiveOrchestrator,
)
__all__ = [
    # Phase 4A
    "AssertionType",
    "CostLedger",
    "CostModelConfig",
    "CostRecord",
    "ElementState",
    "EvalAssertion",
    "EvalAssertionResult",
    "EvalCortexClient",
    "EvalResult",
    "EvalRunSummary",
    "EvalRunner",
    "EvalTask",
    "MockEvalLocator",
    "MockEvalPage",
    "ScorecardBuilder",
    "ScorecardSummary",
    "check_element_state",
    "check_input_value",
    "check_page_title",
    "check_state_hash_changed",
    "check_url",
    "check_visible_text",
    "create_local_tasks",
    "evaluate_assertion",
    "get_fixture_url",
    "get_task_by_id",
    "get_tasks_by_category",
    # Phase 4B
    "DatabaseDiffEngine",
    "DatabaseDiffReport",
    "DatabaseSnapshot",
    "DbRow",
    "MockWebArenaPage",
    "RAW_WEBARENA_SUBSET",
    "RowUpdateDiff",
    "TableDiff",
    "TableSnapshot",
    "WebArenaAssertionAdapter",
    "WebArenaEnv",
    "WebArenaRunner",
    "build_program_html_assertion",
    "build_string_match_assertion",
    "build_unsupported_assertion",
    "build_url_match_assertion",
    "check_webarena_program_html",
    "check_webarena_string_match",
    "check_webarena_unsupported",
    "check_webarena_url_match",
    "create_webarena_subset",
    "get_webarena_task_by_id",
    "get_webarena_tasks_by_domain",
    "map_webarena_task",
    "normalize_text",
    "normalize_url",
    "parse_webarena_json",
    "parse_webarena_jsonl",
    # Phase 4C
    "MockOSWorldPage",
    "OSWorldAssertionAdapter",
    "OSWorldEnv",
    "OSWorldRunner",
    "RAW_OSWORLD_SUBSET",
    "build_at_spi_state_match_assertion",
    "build_file_content_match_assertion",
    "build_file_exist_assertion",
    "build_terminal_output_match_assertion",
    "check_at_spi_state_match",
    "check_file_content_match",
    "check_file_exist",
    "check_osworld_unsupported",
    "check_terminal_output_match",
    "create_osworld_subset",
    "get_osworld_task_by_id",
    "get_osworld_tasks_by_domain",
    "map_osworld_task",
    "parse_osworld_json",
    "parse_osworld_jsonl",
    # Phase 5
    "HostCapabilities",
    "LIVE_ORCHESTRATION_SKIPPED",
    "LiveOrchestrator",
]
