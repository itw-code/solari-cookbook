"""Feature Builder for ARC (Phase 3B Task 4).

Extracts deterministic, JSON-serializable feature vectors from telemetry windows:
- Quantifies action patterns, locator repetitions, and execution outcomes.
- Calculates state hash cycles, consecutive stalls, and distance sequences.
- Extracts role and name sequences without requiring screenshot dependencies.
- Sub-10ms p95 execution latency.
"""

from __future__ import annotations

import collections
import dataclasses
import json
import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from ..schemas import TrajectoryRecord, TrajectoryWindow
from .model_interface import MonitorWindow, to_step_telemetry
from .stuck_monitor import StepTelemetry

logger = logging.getLogger("arc_cua.monitors.feature_builder")

# Regex helpers to extract role and name from locator strings
ROLE_NAME_REGEX = re.compile(
    r"(?:role:)?([a-zA-Z0-9_\-]+)(?:\[name=['\"]([^'\"]+)['\"]\])?", re.IGNORECASE
)
CSS_ID_CLASS_REGEX = re.compile(r"([a-zA-Z0-9_\-]+)?(?:#([a-zA-Z0-9_\-]+))?", re.IGNORECASE)


def parse_role_and_name(locator: Optional[str]) -> Tuple[str, str]:
    """Extract (role, name) from a locator string deterministically."""
    if not locator:
        return "none", "none"

    loc = str(locator).strip()

    # 1. Check role:xxx[name='yyy']
    m = ROLE_NAME_REGEX.match(loc)
    if m:
        role = m.group(1) or "unknown"
        name = m.group(2) or "unknown"
        if role != "unknown" or name != "unknown":
            return role.lower(), name

    # 2. Check css tag#id
    m2 = CSS_ID_CLASS_REGEX.match(loc)
    if m2 and (m2.group(1) or m2.group(2)):
        role = m2.group(1) or "element"
        name = m2.group(2) or loc
        return role.lower(), name

    return "element", loc


@dataclasses.dataclass
class WindowFeatures:
    """Structured feature container extracted from a trajectory window."""
    window_size: int
    action_repeat_count: int
    locator_repeat_count: int
    locator_failure_count: int
    readiness_timeout_count: int
    action_exception_count: int
    consecutive_no_state_change: int
    hamming_distance_sequence: List[int]
    state_hash_cycle_detected: bool
    url_changed: bool
    error_detected: bool
    expected_state_change_verified: bool
    visible_text_delta: int
    action_type_sequence: List[str]
    target_role_sequence: List[str]
    target_name_sequence: List[str]
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


class FeatureBuilder:
    """Deterministic feature extractor converting trajectory windows to feature representations."""

    def __init__(self):
        pass

    def build_features(
        self, window: Union[MonitorWindow, TrajectoryWindow, Sequence[Any]]
    ) -> WindowFeatures:
        """Extract structured WindowFeatures from a window or step sequence."""
        if isinstance(window, (MonitorWindow, TrajectoryWindow)):
            raw_steps = window.steps
            current_raw = window.current_step
        elif isinstance(window, Sequence) and len(window) > 0:
            raw_steps = list(window)
            current_raw = raw_steps[-1]
        else:
            raise ValueError("Invalid window: must be non-empty sequence or window object")

        steps: List[StepTelemetry] = [to_step_telemetry(s) for s in raw_steps]
        curr = steps[-1]

        window_size = len(steps)

        # 1. Action repeat count (consecutive same verb ending at curr)
        action_repeat = 0
        target_verb = curr.verb.upper() if curr.verb else ""
        for s in reversed(steps):
            if (s.verb.upper() if s.verb else "") == target_verb:
                action_repeat += 1
            else:
                break

        # 2. Locator repeat count (consecutive same target ending at curr)
        locator_repeat = 0
        target_loc = curr.target or ""
        for s in reversed(steps):
            if (s.target or "") == target_loc:
                locator_repeat += 1
            else:
                break

        # 3. Locator failure count (failures on target_loc in window)
        locator_failure_count = sum(
            1 for s in steps if (s.target or "") == target_loc and (not s.success or s.action_exception)
        )

        # 4. Readiness timeout count
        readiness_timeout_count = sum(
            1 for s in steps if not s.readiness_ok or (s.readiness_reason and "timeout" in s.readiness_reason.lower())
        )

        # 5. Action exception count
        action_exception_count = sum(
            1 for s in steps if not s.success or s.action_exception
        )

        # 6. Consecutive no state change ending at curr
        consecutive_no_change = 0
        for s in reversed(steps):
            if not s.state_changed:
                consecutive_no_change += 1
            else:
                break

        # 7. Hamming distance sequence
        hamming_sequence = [int(s.hamming_distance) for s in steps]

        # 8. State hash cycle detected
        hashes = [s.state_hash for s in steps if s.state_hash]
        cycle_detected = False
        if len(hashes) >= 3:
            for i in range(len(hashes) - 2):
                if hashes[i] == hashes[i + 2] and hashes[i] != hashes[i + 1]:
                    cycle_detected = True
                    break

        # 9. Current step specific signals
        url_changed = bool(curr.url_changed)
        error_detected = bool(not curr.success or curr.action_exception or curr.error_message)

        # 10. Expected state change verified
        meta = curr.metadata or {}
        expected_verified = bool(
            meta.get("expected_state_change_verified", False)
            or (curr.state_changed and curr.success and not error_detected)
        )

        # 11. Visible text delta
        text_delta = int(meta.get("visible_text_delta", meta.get("text_delta", curr.hamming_distance)))

        # 12. Sequences
        action_seq = [s.verb.upper() if s.verb else "UNKNOWN" for s in steps]
        role_seq: List[str] = []
        name_seq: List[str] = []
        for s in steps:
            r, n = parse_role_and_name(s.target)
            role_seq.append(r)
            name_seq.append(n)

        return WindowFeatures(
            window_size=window_size,
            action_repeat_count=action_repeat,
            locator_repeat_count=locator_repeat,
            locator_failure_count=locator_failure_count,
            readiness_timeout_count=readiness_timeout_count,
            action_exception_count=action_exception_count,
            consecutive_no_state_change=consecutive_no_change,
            hamming_distance_sequence=hamming_sequence,
            state_hash_cycle_detected=cycle_detected,
            url_changed=url_changed,
            error_detected=error_detected,
            expected_state_change_verified=expected_verified,
            visible_text_delta=text_delta,
            action_type_sequence=action_seq,
            target_role_sequence=role_seq,
            target_name_sequence=name_seq,
            metadata={"step_id": curr.step_id, "current_verb": curr.verb},
        )
