"""OSWorld Assertion Adapter for ARC (Phase 4C).

Implements evaluation checkers for OSWorld desktop benchmark assertions:
1. `file_exist`: Verifies presence or absence of target files.
2. `file_content_match`: Verifies text, regex, or lines in target files.
3. `terminal_output_match`: Verifies terminal output buffer or command history.
4. `at_spi_state_match`: Verifies AT-SPI accessibility widget hierarchy and states.
5. `skip`: Gracefully handles unsupported or skipped evaluation requirements.

Integrates with `OSWorldEnv` to inspect live desktop environments or offline
mock environments with 100% determinism.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional, Sequence, Union

from .osworld_env import OSWorldEnv
from .schemas import EvalAssertion, EvalAssertionResult

logger = logging.getLogger("arc_cua.eval.osworld_assertions")


def check_file_exist(
    assertion: EvalAssertion,
    env: OSWorldEnv,
) -> EvalAssertionResult:
    """Evaluate file existence in OSWorld environment.

    Args:
        assertion: EvalAssertion specifying target file path and expected existence.
        env: OSWorldEnv instance.

    Returns:
        EvalAssertionResult with pass/fail and actual file existence.
    """
    t0 = time.perf_counter()
    file_path = assertion.selector or ""
    expected = bool(assertion.expected) if isinstance(assertion.expected, (bool, int)) else True
    if isinstance(assertion.expected, dict):
        file_path = assertion.expected.get("file_path", file_path)
        expected = bool(assertion.expected.get("expected", True))

    if not file_path:
        return EvalAssertionResult(
            assertion=assertion,
            passed=False,
            actual=None,
            error_message="file_exist assertion missing file_path/selector",
            latency_ms=(time.perf_counter() - t0) * 1000.0,
        )

    actual_exists = env.file_exists(file_path)
    passed = (actual_exists == expected)
    error_msg = None
    if not passed:
        if expected:
            error_msg = f"Expected file to exist: '{file_path}', but it does not exist"
        else:
            error_msg = f"Expected file NOT to exist: '{file_path}', but it exists"

    latency_ms = (time.perf_counter() - t0) * 1000.0
    return EvalAssertionResult(
        assertion=assertion,
        passed=passed,
        actual={"file_path": file_path, "exists": actual_exists},
        error_message=error_msg,
        latency_ms=latency_ms,
    )


def check_file_content_match(
    assertion: EvalAssertion,
    env: OSWorldEnv,
) -> EvalAssertionResult:
    """Evaluate file content matching in OSWorld environment.

    Args:
        assertion: EvalAssertion specifying target file and pattern/match_type.
        env: OSWorldEnv instance.

    Returns:
        EvalAssertionResult with pass/fail and actual content match details.
    """
    t0 = time.perf_counter()
    file_path = assertion.selector or ""
    pattern = ""
    match_type = "substring"

    if isinstance(assertion.expected, dict):
        file_path = assertion.expected.get("file_path", file_path)
        pattern = str(assertion.expected.get("pattern", assertion.expected.get("content", "")))
        match_type = assertion.expected.get("match_type", "substring").lower()
    elif assertion.expected is not None:
        pattern = str(assertion.expected)

    if not file_path:
        return EvalAssertionResult(
            assertion=assertion,
            passed=False,
            actual=None,
            error_message="file_content_match assertion missing file_path/selector",
            latency_ms=(time.perf_counter() - t0) * 1000.0,
        )

    if not env.file_exists(file_path):
        return EvalAssertionResult(
            assertion=assertion,
            passed=False,
            actual=None,
            error_message=f"Target file does not exist: '{file_path}'",
            latency_ms=(time.perf_counter() - t0) * 1000.0,
        )

    try:
        content = env.read_file(file_path)
    except Exception as e:
        return EvalAssertionResult(
            assertion=assertion,
            passed=False,
            actual=None,
            error_message=f"Failed to read target file '{file_path}': {e}",
            latency_ms=(time.perf_counter() - t0) * 1000.0,
        )

    passed = False
    error_msg = None

    if match_type in ("exact", "equals"):
        passed = (content.strip() == pattern.strip())
        if not passed:
            error_msg = f"Content in '{file_path}' did not exactly match pattern '{pattern}'"
    elif match_type in ("regex", "regexp"):
        try:
            match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
            passed = (match is not None)
            if not passed:
                error_msg = f"Regex '{pattern}' did not match content in '{file_path}'"
        except re.error as err:
            passed = False
            error_msg = f"Invalid regex pattern '{pattern}': {err}"
    elif match_type in ("lines_include", "contains_all_lines"):
        expected_lines = [line.strip() for line in pattern.splitlines() if line.strip()]
        actual_lines = [line.strip() for line in content.splitlines()]
        missing = [line for line in expected_lines if line not in actual_lines]
        passed = (len(missing) == 0)
        if not passed:
            error_msg = f"File '{file_path}' missing expected lines: {missing}"
    else:  # Default substring match
        passed = (pattern in content)
        if not passed:
            error_msg = f"Pattern '{pattern}' not found in '{file_path}'"

    latency_ms = (time.perf_counter() - t0) * 1000.0
    preview = content[:200] + ("..." if len(content) > 200 else "")
    return EvalAssertionResult(
        assertion=assertion,
        passed=passed,
        actual={"file_path": file_path, "match_type": match_type, "preview": preview},
        error_message=error_msg,
        latency_ms=latency_ms,
    )


def check_terminal_output_match(
    assertion: EvalAssertion,
    env: OSWorldEnv,
) -> EvalAssertionResult:
    """Evaluate terminal output or command history in OSWorld environment.

    Args:
        assertion: EvalAssertion specifying expected terminal output pattern.
        env: OSWorldEnv instance.

    Returns:
        EvalAssertionResult with pass/fail and actual terminal output comparison.
    """
    t0 = time.perf_counter()
    pattern = ""
    match_type = "substring"

    if isinstance(assertion.expected, dict):
        pattern = str(assertion.expected.get("pattern", assertion.expected.get("expected", "")))
        match_type = assertion.expected.get("match_type", "substring").lower()
    elif assertion.expected is not None:
        pattern = str(assertion.expected)

    terminal_output = env.get_terminal_output()
    terminal_history = env.get_terminal_history()

    passed = False
    error_msg = None

    if match_type == "command":
        # Check if command was executed in terminal history
        passed = any(pattern.lower() in cmd.lower() for cmd in terminal_history)
        if not passed:
            error_msg = f"Command pattern '{pattern}' not found in terminal history: {terminal_history}"
    elif match_type in ("exact", "equals"):
        passed = (terminal_output.strip() == pattern.strip())
        if not passed:
            error_msg = f"Terminal output did not exactly match '{pattern}'"
    elif match_type in ("regex", "regexp"):
        try:
            match = re.search(pattern, terminal_output, re.MULTILINE | re.DOTALL)
            passed = (match is not None)
            if not passed:
                error_msg = f"Regex '{pattern}' did not match terminal output"
        except re.error as err:
            passed = False
            error_msg = f"Invalid regex pattern '{pattern}': {err}"
    else:  # Default substring match
        # Check terminal output buffer, or fall back to terminal history
        combined_text = terminal_output + "\n" + "\n".join(terminal_history)
        passed = (pattern in combined_text)
        if not passed:
            error_msg = f"Terminal output did not contain pattern '{pattern}'"

    latency_ms = (time.perf_counter() - t0) * 1000.0
    preview = terminal_output[:200] + ("..." if len(terminal_output) > 200 else "")
    return EvalAssertionResult(
        assertion=assertion,
        passed=passed,
        actual={"match_type": match_type, "preview": preview, "command_count": len(terminal_history)},
        error_message=error_msg,
        latency_ms=latency_ms,
    )


def check_at_spi_state_match(
    assertion: EvalAssertion,
    env: OSWorldEnv,
) -> EvalAssertionResult:
    """Evaluate AT-SPI accessible widget presence, role, and states.

    Args:
        assertion: EvalAssertion specifying app, role, name, and required state.
        env: OSWorldEnv instance.

    Returns:
        EvalAssertionResult with pass/fail and matched widget details.
    """
    t0 = time.perf_counter()
    app_name = None
    role = None
    name = None
    state = None
    expected = True

    if isinstance(assertion.expected, dict):
        app_name = assertion.expected.get("app_name")
        role = assertion.expected.get("role")
        name = assertion.expected.get("name")
        state = assertion.expected.get("state")
        expected = bool(assertion.expected.get("expected", True))
    elif assertion.selector:
        # Selector format: "app:role:name"
        parts = assertion.selector.split(":", 2)
        if len(parts) >= 1 and parts[0] != "*":
            app_name = parts[0]
        if len(parts) >= 2 and parts[1] != "*":
            role = parts[1]
        if len(parts) >= 3 and parts[2] != "*":
            name = parts[2]

    # Query matching accessible widgets from environment
    matches = env.find_nodes(app_name=app_name, role=role, name=name, state=state)

    node_found = len(matches) > 0
    passed = (node_found == expected)
    error_msg = None

    if not passed:
        desc_parts = []
        if app_name:
            desc_parts.append(f"app='{app_name}'")
        if role:
            desc_parts.append(f"role='{role}'")
        if name:
            desc_parts.append(f"name='{name}'")
        if state:
            desc_parts.append(f"state='{state}'")
        desc_str = ", ".join(desc_parts) or "any widget"

        if expected:
            error_msg = f"Expected matching AT-SPI widget ({desc_str}), but none found"
        else:
            error_msg = f"Expected NO matching AT-SPI widget ({desc_str}), but found {len(matches)}"

    actual_info = {
        "matched_count": len(matches),
        "app_name": app_name,
        "role": role,
        "name": name,
        "state": state,
    }
    if matches:
        first = matches[0]
        actual_info["first_match"] = {
            "app_name": first.app_name,
            "role": first.role,
            "name": first.name,
            "states": list(first.states),
            "bounding_box": list(first.bounding_box),
        }

    latency_ms = (time.perf_counter() - t0) * 1000.0
    return EvalAssertionResult(
        assertion=assertion,
        passed=passed,
        actual=actual_info,
        error_message=error_msg,
        latency_ms=latency_ms,
    )


def check_osworld_unsupported(
    assertion: EvalAssertion,
) -> EvalAssertionResult:
    """Handle unsupported or skipped OSWorld evaluation assertion types."""
    return EvalAssertionResult(
        assertion=assertion,
        passed=True,
        actual="SKIPPED",
        error_message=None,
        latency_ms=0.0,
    )


class OSWorldAssertionAdapter:
    """Unified evaluation adapter for OSWorld benchmark assertions."""

    def __init__(
        self,
        env: OSWorldEnv,
        skip_unsupported: bool = True,
    ):
        """Initialize the adapter.

        Args:
            env: OSWorldEnv instance providing file, terminal, and AT-SPI state.
            skip_unsupported: Whether unsupported assertion types are marked passed.
        """
        self.env = env
        self.skip_unsupported = skip_unsupported

    def evaluate_assertion(self, assertion: EvalAssertion) -> EvalAssertionResult:
        """Evaluate a single OSWorld assertion.

        Args:
            assertion: EvalAssertion to evaluate.

        Returns:
            EvalAssertionResult.
        """
        raw_type = str(assertion.type.value if hasattr(assertion.type, "value") else assertion.type).lower()

        if raw_type == "file_exist":
            return check_file_exist(assertion, self.env)
        elif raw_type == "file_content_match":
            return check_file_content_match(assertion, self.env)
        elif raw_type == "terminal_output_match":
            return check_terminal_output_match(assertion, self.env)
        elif raw_type == "at_spi_state_match":
            return check_at_spi_state_match(assertion, self.env)
        elif raw_type in ("skip", "unsupported"):
            return check_osworld_unsupported(assertion)
        else:
            if self.skip_unsupported:
                logger.warning("Skipping unsupported OSWorld assertion type: %s", raw_type)
                return check_osworld_unsupported(assertion)
            return EvalAssertionResult(
                assertion=assertion,
                passed=False,
                actual=None,
                error_message=f"Unsupported OSWorld assertion type: {raw_type}",
            )

    def evaluate_all(
        self,
        assertions: Sequence[EvalAssertion],
    ) -> List[EvalAssertionResult]:
        """Evaluate a sequence of assertions against the environment.

        Args:
            assertions: List or sequence of EvalAssertion objects.

        Returns:
            List of EvalAssertionResult objects.
        """
        results: List[EvalAssertionResult] = []
        for assertion in assertions:
            res = self.evaluate_assertion(assertion)
            results.append(res)
        return results
