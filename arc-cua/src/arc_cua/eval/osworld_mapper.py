"""OSWorld Task Schema Mapper for ARC (Phase 4C).

Ingests and translates OSWorld benchmark task definitions into the ARC
evaluation schema (`EvalTask`, `EvalAssertion`).

Supported OSWorld evaluation modalities:
- `file_exist`: Verifies presence/absence of workspace files.
- `file_content_match`: Verifies text or pattern matching within files.
- `terminal_output_match`: Verifies stdout/stderr output or executed commands.
- `at_spi_state_match`: Verifies AT-SPI accessible widget presence, role, and states.

Unsupported evaluation modalities are gracefully mapped to `skip` assertions
to maintain continuous evaluation flow.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Sequence, Union

from ..schemas import ActionStep
from .schemas import EvalAssertion, EvalTask

logger = logging.getLogger("arc_cua.eval.osworld_mapper")

SUPPORTED_EVAL_TYPES = {
    "file_exist",
    "file_content_match",
    "terminal_output_match",
    "at_spi_state_match",
}


def build_file_exist_assertion(
    file_path: str,
    expected: bool = True,
    description: Optional[str] = None,
) -> EvalAssertion:
    """Build an EvalAssertion for file existence check.

    Args:
        file_path: Normalized path to the target file.
        expected: True if file must exist, False if it must not exist.
        description: Optional human-readable description.
    """
    desc = description or f"Check file existence: {file_path} (expected={expected})"
    return EvalAssertion(
        type="file_exist",
        selector=file_path,
        expected=bool(expected),
        description=desc,
    )


def build_file_content_match_assertion(
    file_path: str,
    expected: Union[str, Dict[str, Any]],
    match_type: str = "substring",
    description: Optional[str] = None,
) -> EvalAssertion:
    """Build an EvalAssertion for file content matching.

    Args:
        file_path: Normalized path to the target file.
        expected: Expected string pattern or structured dict.
        match_type: 'substring', 'exact', 'regex', or 'lines_include'.
        description: Optional human-readable description.
    """
    if isinstance(expected, dict):
        pattern = expected.get("pattern", expected.get("content", ""))
        resolved_match_type = expected.get("match_type", match_type)
    else:
        pattern = str(expected)
        resolved_match_type = match_type

    desc = description or f"Check content in {file_path} matches '{pattern}' ({resolved_match_type})"
    return EvalAssertion(
        type="file_content_match",
        selector=file_path,
        expected={"pattern": pattern, "match_type": resolved_match_type},
        description=desc,
    )


def build_terminal_output_match_assertion(
    expected: Union[str, Dict[str, Any]],
    match_type: str = "substring",
    description: Optional[str] = None,
) -> EvalAssertion:
    """Build an EvalAssertion for terminal stdout/stderr or command matching.

    Args:
        expected: Expected text pattern or structured dictionary.
        match_type: 'substring', 'exact', 'regex', or 'command'.
        description: Optional human-readable description.
    """
    if isinstance(expected, dict):
        pattern = expected.get("pattern", expected.get("expected", ""))
        resolved_match_type = expected.get("match_type", match_type)
    else:
        pattern = str(expected)
        resolved_match_type = match_type

    desc = description or f"Check terminal output matches '{pattern}' ({resolved_match_type})"
    return EvalAssertion(
        type="terminal_output_match",
        selector=None,
        expected={"pattern": pattern, "match_type": resolved_match_type},
        description=desc,
    )


def build_at_spi_state_match_assertion(
    app_name: Optional[str] = None,
    role: Optional[str] = None,
    name: Optional[str] = None,
    state: Optional[str] = None,
    expected: bool = True,
    description: Optional[str] = None,
) -> EvalAssertion:
    """Build an EvalAssertion for AT-SPI accessibility widget matching.

    Args:
        app_name: Target desktop application (e.g. 'code', 'gnome-terminal').
        role: Target widget role (e.g. 'push_button', 'terminal', 'entry').
        name: Target widget accessible name/label.
        state: Accessibility state requirement (e.g. 'showing', 'focused', 'selected').
        expected: True if matching widget with state must exist, False otherwise.
        description: Optional human-readable description.
    """
    selector = f"{app_name or '*'}:{role or '*'}:{name or '*'}"
    desc = description or f"Check AT-SPI widget {selector} has state='{state}' (expected={expected})"
    return EvalAssertion(
        type="at_spi_state_match",
        selector=selector,
        expected={
            "app_name": app_name,
            "role": role,
            "name": name,
            "state": state,
            "expected": bool(expected),
        },
        description=desc,
    )


def build_unsupported_assertion(
    eval_type: str,
    raw_config: Optional[Dict[str, Any]] = None,
) -> EvalAssertion:
    """Create a placeholder assertion marking an unsupported OSWorld evaluation type."""
    return EvalAssertion(
        type="skip",
        selector=None,
        expected={"unsupported_type": eval_type, "raw": raw_config or {}},
        description=f"Unsupported OSWorld evaluation type: {eval_type} (gracefully skipped)",
    )


def _map_eval_rules(
    eval_spec: Dict[str, Any],
) -> List[EvalAssertion]:
    """Extract and build assertions from OSWorld eval specification."""
    assertions: List[EvalAssertion] = []
    eval_types = eval_spec.get("eval_types", [])
    if isinstance(eval_types, str):
        eval_types = [eval_types]

    # Check for explicit list of rules/assertions
    rules = eval_spec.get("rules") or eval_spec.get("assertions")
    if isinstance(rules, list):
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            r_type = rule.get("type", "").lower()
            if r_type == "file_exist":
                assertions.append(
                    build_file_exist_assertion(
                        file_path=rule.get("file_path", rule.get("path", "")),
                        expected=rule.get("expected", True),
                        description=rule.get("description"),
                    )
                )
            elif r_type == "file_content_match":
                assertions.append(
                    build_file_content_match_assertion(
                        file_path=rule.get("file_path", rule.get("path", "")),
                        expected=rule.get("expected", rule.get("pattern", "")),
                        match_type=rule.get("match_type", "substring"),
                        description=rule.get("description"),
                    )
                )
            elif r_type == "terminal_output_match":
                assertions.append(
                    build_terminal_output_match_assertion(
                        expected=rule.get("expected", rule.get("pattern", "")),
                        match_type=rule.get("match_type", "substring"),
                        description=rule.get("description"),
                    )
                )
            elif r_type == "at_spi_state_match":
                assertions.append(
                    build_at_spi_state_match_assertion(
                        app_name=rule.get("app_name"),
                        role=rule.get("role"),
                        name=rule.get("name"),
                        state=rule.get("state"),
                        expected=rule.get("expected", True),
                        description=rule.get("description"),
                    )
                )
            else:
                assertions.append(build_unsupported_assertion(r_type, rule))

    # If rules were not explicitly provided, map from domain shorthand keys
    if not assertions:
        for et in eval_types:
            et_lower = et.lower()
            if et_lower == "file_exist":
                file_info = eval_spec.get("file") or eval_spec.get("files") or {}
                if isinstance(file_info, dict):
                    path = file_info.get("path") or file_info.get("file_path") or ""
                    exp = file_info.get("exist", file_info.get("expected", True))
                    assertions.append(build_file_exist_assertion(path, expected=exp))
                elif isinstance(file_info, list):
                    for item in file_info:
                        if isinstance(item, dict):
                            path = item.get("path") or item.get("file_path") or ""
                            exp = item.get("exist", item.get("expected", True))
                            assertions.append(build_file_exist_assertion(path, expected=exp))
            elif et_lower == "file_content_match":
                file_info = eval_spec.get("file") or eval_spec.get("files") or {}
                if isinstance(file_info, dict):
                    path = file_info.get("path") or file_info.get("file_path") or ""
                    content = file_info.get("content") or file_info.get("expected") or ""
                    match_type = file_info.get("match_type", "substring")
                    assertions.append(build_file_content_match_assertion(path, content, match_type))
            elif et_lower == "terminal_output_match":
                term_info = eval_spec.get("terminal") or {}
                expected = term_info.get("expected") or term_info.get("output") or eval_spec.get("expected") or ""
                match_type = term_info.get("match_type", "substring")
                assertions.append(build_terminal_output_match_assertion(expected, match_type))
            elif et_lower == "at_spi_state_match":
                at_spi_info = eval_spec.get("at_spi") or {}
                assertions.append(
                    build_at_spi_state_match_assertion(
                        app_name=at_spi_info.get("app_name"),
                        role=at_spi_info.get("role"),
                        name=at_spi_info.get("name"),
                        state=at_spi_info.get("state"),
                        expected=at_spi_info.get("expected", True),
                    )
                )
            else:
                assertions.append(build_unsupported_assertion(et_lower, eval_spec))

    return assertions


def map_osworld_task(data: Dict[str, Any]) -> EvalTask:
    """Map a single OSWorld task definition dictionary to a ARC EvalTask.

    Args:
        data: Raw OSWorld task dictionary.

    Returns:
        Structured EvalTask object.
    """
    raw_id = data.get("id") or data.get("task_id") or "osworld_unknown"
    task_id = str(raw_id)

    instruction = data.get("instruction") or data.get("intent") or "OSWorld benchmark task"
    domain = data.get("domain") or data.get("category") or "desktop"

    # Start state extraction
    start_state = data.get("start_state") or data.get("init") or {}
    start_url = data.get("start_url") or f"desktop://{domain}"

    # Parse evaluation assertions
    eval_spec = data.get("eval") or data.get("evaluation") or {}
    assertions = _map_eval_rules(eval_spec)

    # Optional planned action steps from dataset if present
    raw_steps = data.get("action_steps") or data.get("steps") or []
    action_steps: List[Union[ActionStep, Dict[str, Any]]] = []
    for step in raw_steps:
        if isinstance(step, dict):
            action_steps.append(step)
        elif isinstance(step, ActionStep):
            action_steps.append(step)

    max_steps = int(data.get("max_steps", 20))
    timeout_ms = float(data.get("timeout_ms", 30000.0))

    tags = ["osworld", domain]
    if data.get("tags"):
        tags.extend([t for t in data["tags"] if t not in tags])

    metadata = {
        "osworld_raw_id": raw_id,
        "domain": domain,
        "start_state": start_state,
        "eval_spec": eval_spec,
    }
    if "metadata" in data and isinstance(data["metadata"], dict):
        metadata.update(data["metadata"])

    return EvalTask(
        task_id=task_id,
        name=f"OSWorld: {instruction[:60]}",
        category=domain,
        description=instruction,
        start_url=start_url,
        action_steps=action_steps,
        expected_assertions=assertions,
        max_steps=max_steps,
        timeout_ms=timeout_ms,
        tags=tags,
        metadata=metadata,
    )


def parse_osworld_json(json_str: str) -> List[EvalTask]:
    """Parse an OSWorld JSON string (object or array) into a list of EvalTasks.

    Args:
        json_str: Valid JSON string representing one task or list of tasks.

    Returns:
        List of parsed EvalTask instances.
    """
    data = json.loads(json_str)
    if isinstance(data, list):
        return [map_osworld_task(item) for item in data if isinstance(item, dict)]
    elif isinstance(data, dict):
        # Could be {"tasks": [...]} or a single task
        if "tasks" in data and isinstance(data["tasks"], list):
            return [map_osworld_task(item) for item in data["tasks"] if isinstance(item, dict)]
        return [map_osworld_task(data)]
    else:
        raise ValueError(f"Expected JSON object or array, got {type(data).__name__}")


def parse_osworld_jsonl(jsonl_str: str) -> List[EvalTask]:
    """Parse an OSWorld JSONL string into a list of EvalTasks.

    Args:
        jsonl_str: String containing one JSON object per line.

    Returns:
        List of parsed EvalTask instances.
    """
    tasks: List[EvalTask] = []
    for line in jsonl_str.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            item = json.loads(stripped)
            if isinstance(item, dict):
                tasks.append(map_osworld_task(item))
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse JSONL line in OSWorld mapper: %s", e)
    return tasks
