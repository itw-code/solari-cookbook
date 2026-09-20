"""WebArena Task Schema Mapper for ARC (Phase 4B).

Converts WebArena benchmark task definitions (JSON / JSONL format) into
ARC internal EvalTask and EvalAssertion schemas.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Sequence, Union

from .schemas import EvalAssertion, EvalTask
from .webarena_env import WebArenaEnv

logger = logging.getLogger("arc_cua.eval.webarena_mapper")

SUPPORTED_EVAL_TYPES = {"url_match", "string_match", "program_html"}


def build_url_match_assertion(
    reference_url: str,
    url_note: Optional[str] = None,
    timeout_ms: float = 2000.0,
) -> EvalAssertion:
    """Create an EvalAssertion for WebArena url_match."""
    return EvalAssertion(
        type="url_match",
        expected={"reference_url": reference_url, "url_note": url_note or "exact"},
        description=f"WebArena URL match: expected '{reference_url}' (note: {url_note or 'exact'})",
        timeout_ms=timeout_ms,
    )


def build_string_match_assertion(
    reference_answers: Any,
    string_note: Optional[str] = None,
    timeout_ms: float = 2000.0,
) -> EvalAssertion:
    """Create an EvalAssertion for WebArena string_match."""
    return EvalAssertion(
        type="string_match",
        expected={
            "reference_answers": reference_answers,
            "string_note": string_note or "fuzzy_match",
        },
        description="WebArena string match against reference answers in final state",
        timeout_ms=timeout_ms,
    )


def build_program_html_assertion(
    program_html_item: Dict[str, Any],
    timeout_ms: float = 2000.0,
) -> EvalAssertion:
    """Create an EvalAssertion for WebArena program_html (database or DOM state check)."""
    point = program_html_item.get("point", "db")
    locator = program_html_item.get("locator") or program_html_item.get("selector", "")
    return EvalAssertion(
        type="program_html",
        selector=locator if point == "dom" else None,
        expected=program_html_item,
        description=f"WebArena program_html assertion (point: {point}, locator: {locator})",
        timeout_ms=timeout_ms,
    )


def build_unsupported_assertion(
    eval_type: str,
    reason: Optional[str] = None,
) -> EvalAssertion:
    """Create a placeholder assertion marking an unsupported WebArena evaluation type."""
    return EvalAssertion(
        type="unsupported",
        expected="SKIP",
        description=f"Unsupported WebArena eval type '{eval_type}': {reason or 'no compatible evaluator'}",
    )


def map_webarena_task(
    raw_task: Dict[str, Any],
    env: Optional[WebArenaEnv] = None,
    default_max_steps: int = 15,
    default_timeout_ms: float = 30000.0,
    action_steps: Optional[Sequence[Any]] = None,
) -> EvalTask:
    """Map a single WebArena task dictionary to ARC EvalTask.

    Args:
        raw_task: Raw WebArena task dictionary from JSON/JSONL.
        env: Optional WebArenaEnv instance used to resolve domain placeholders.
        default_max_steps: Maximum step budget for task execution.
        default_timeout_ms: Timeout limit in milliseconds.
        action_steps: Optional pre-defined action steps for replay/testing.

    Returns:
        Fully initialized EvalTask instance with mapped assertions.
    """
    task_id_raw = raw_task.get("task_id", 0)
    task_id = f"webarena_{task_id_raw}"
    intent = raw_task.get("intent", "").strip()

    start_url_raw = raw_task.get("start_url", "")
    if env is not None:
        start_url = env.resolve_url(start_url_raw)
    else:
        start_url = start_url_raw

    sites = raw_task.get("sites", [])
    category = sites[0] if sites else "webarena"

    eval_block = raw_task.get("eval", {})
    eval_types: List[str] = eval_block.get("eval_types", [])
    reference_answers = eval_block.get("reference_answers")
    reference_url = eval_block.get("reference_url")
    if env is not None and reference_url:
        reference_url = env.resolve_url(reference_url)

    url_note = eval_block.get("url_note")
    string_note = eval_block.get("string_note")
    program_html = eval_block.get("program_html", [])

    assertions: List[EvalAssertion] = []
    unsupported_types: List[str] = []

    for eval_type in eval_types:
        if eval_type == "url_match":
            if reference_url:
                assertions.append(build_url_match_assertion(reference_url, url_note))
            else:
                assertions.append(
                    build_unsupported_assertion("url_match", "Missing reference_url in task eval config")
                )
        elif eval_type == "string_match":
            if reference_answers is not None:
                assertions.append(build_string_match_assertion(reference_answers, string_note))
            else:
                assertions.append(
                    build_unsupported_assertion("string_match", "Missing reference_answers in task eval config")
                )
        elif eval_type == "program_html":
            if isinstance(program_html, list) and len(program_html) > 0:
                for item in program_html:
                    assertions.append(build_program_html_assertion(item))
            elif isinstance(program_html, dict):
                assertions.append(build_program_html_assertion(program_html))
            else:
                assertions.append(
                    build_unsupported_assertion("program_html", "Empty or invalid program_html definition")
                )
        else:
            unsupported_types.append(eval_type)
            assertions.append(
                build_unsupported_assertion(eval_type, f"Evaluation type '{eval_type}' is not supported")
            )

    is_supported = len(unsupported_types) == 0 and len(assertions) > 0

    metadata: Dict[str, Any] = {
        "raw_task_id": task_id_raw,
        "sites": sites,
        "require_login": raw_task.get("require_login", False),
        "supported": is_supported,
        "unsupported_eval_types": unsupported_types,
        "original_eval_types": eval_types,
        "raw_task": raw_task,
    }

    # Concise readable name
    name = f"WebArena-{task_id_raw}: {intent[:45]}..." if len(intent) > 45 else f"WebArena-{task_id_raw}: {intent}"

    return EvalTask(
        task_id=task_id,
        name=name,
        category=category,
        description=intent,
        start_url=start_url,
        action_steps=list(action_steps) if action_steps else [],
        expected_assertions=assertions,
        max_steps=default_max_steps,
        timeout_ms=default_timeout_ms,
        tags=["webarena", category],
        metadata=metadata,
    )


def parse_webarena_json(
    json_content: str,
    env: Optional[WebArenaEnv] = None,
) -> List[EvalTask]:
    """Parse a WebArena JSON string (object or array) into a list of EvalTasks."""
    data = json.loads(json_content)
    if isinstance(data, dict):
        return [map_webarena_task(data, env=env)]
    elif isinstance(data, list):
        return [map_webarena_task(item, env=env) for item in data]
    else:
        raise ValueError(f"Expected JSON object or array, got {type(data).__name__}")


def parse_webarena_jsonl(
    jsonl_content: str,
    env: Optional[WebArenaEnv] = None,
) -> List[EvalTask]:
    """Parse WebArena JSONL string into a list of EvalTasks."""
    tasks: List[EvalTask] = []
    for line_idx, line in enumerate(jsonl_content.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
            tasks.append(map_webarena_task(item, env=env))
        except json.JSONDecodeError as err:
            logger.warning("Failed to decode JSONL on line %d: %s", line_idx, err)
    return tasks
