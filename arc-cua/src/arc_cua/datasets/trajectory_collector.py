"""Trajectory Dataset Collector for ARC (Phase 3B Task 1).

Collects structured trajectory windows for training and evaluating learned monitors:
- Records full per-step telemetry and environmental state transitions.
- Maintains a deterministic sliding window (default 5 steps).
- Enforces strict redaction of credentials and secrets.
- Exports structured JSONL datasets to artifacts/phase3b/trajectory_logs/.
"""

from __future__ import annotations

import collections
import dataclasses
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from ..schemas import TrajectoryRecord, TrajectoryWindow

logger = logging.getLogger("arc_cua.datasets.trajectory_collector")

SENSITIVE_KEY_PATTERNS = [
    re.compile(r"pass(word)?", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"api[_-]?key", re.IGNORECASE),
    re.compile(r"auth(orization)?", re.IGNORECASE),
    re.compile(r"cred(ential)?", re.IGNORECASE),
    re.compile(r"bearer", re.IGNORECASE),
]

SENSITIVE_VALUE_PATTERNS = [
    re.compile(r"^Bearer\s+[A-Za-z0-9\-_.]+", re.IGNORECASE),
    re.compile(r"^[A-Za-z0-9+/]{32,}={0,2}$"),  # Base64 tokens
    re.compile(r"^sk-[A-Za-z0-9]{20,}"),  # OpenAI/API style keys
]


def redact_sensitive_data(obj: Any) -> Any:
    """Recursively redact sensitive data (passwords, tokens, credentials, API keys)."""
    if isinstance(obj, dict):
        cleaned: Dict[str, Any] = {}
        for k, v in obj.items():
            k_str = str(k)
            if any(pattern.search(k_str) for pattern in SENSITIVE_KEY_PATTERNS):
                cleaned[k_str] = "[REDACTED]"
            else:
                cleaned[k_str] = redact_sensitive_data(v)
        return cleaned
    elif isinstance(obj, list):
        return [redact_sensitive_data(item) for item in obj]
    elif isinstance(obj, str):
        for val_pat in SENSITIVE_VALUE_PATTERNS:
            if val_pat.search(obj):
                return "[REDACTED]"
        return obj
    return obj


class TrajectoryCollector:
    """Collects and windows trajectory execution records."""

    def __init__(
        self,
        default_window_size: int = 5,
        output_dir: Optional[Union[str, Path]] = None,
        auto_redact: bool = True,
    ):
        """Initialize TrajectoryCollector.

        Args:
            default_window_size: Number of steps in the sliding history window (default: 5).
            output_dir: Optional directory for saving logs (default: artifacts/phase3b/trajectory_logs/).
            auto_redact: Whether to sanitize credentials and sensitive information automatically.
        """
        self.default_window_size = default_window_size
        self.output_dir = Path(output_dir or "artifacts/phase3b/trajectory_logs")
        self.auto_redact = auto_redact

        self._records: List[TrajectoryRecord] = []
        self._windows: List[TrajectoryWindow] = []
        self._recent_steps_by_run: Dict[str, collections.deque[TrajectoryRecord]] = collections.defaultdict(
            lambda: collections.deque(maxlen=max(1, self.default_window_size - 1))
        )

    @property
    def total_records(self) -> int:
        return len(self._records)

    @property
    def total_windows(self) -> int:
        return len(self._windows)

    def record_step(
        self,
        run_id: str,
        task_id: str,
        step_id: int,
        action_type: str = "",
        target_locator: Optional[str] = None,
        locator_strategy: Optional[str] = None,
        readiness_passed: bool = True,
        execution_success: bool = True,
        state_hash_before: Union[int, str] = 0,
        state_hash_after: Union[int, str] = 0,
        state_changed: bool = False,
        hamming_distance: int = 0,
        url_before: Optional[str] = None,
        url_after: Optional[str] = None,
        url_changed: bool = False,
        error_detected: bool = False,
        error_type: Optional[str] = None,
        monitor_stuck_score: float = 0.0,
        monitor_milestone_score: float = 0.0,
        escalation_decision: Optional[str] = None,
        recovery_attempted: bool = False,
        recovery_success: Optional[bool] = None,
        integration_mode: str = "mock",
        value: Optional[str] = None,
        timestamp: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TrajectoryWindow:
        """Create, store, and window a new TrajectoryRecord.

        Returns:
            The newly created TrajectoryWindow enclosing this step.
        """
        meta = dict(metadata or {})
        if value is not None:
            meta["value"] = value

        record = TrajectoryRecord(
            run_id=run_id,
            task_id=task_id,
            step_id=step_id,
            timestamp=timestamp if timestamp is not None else time.time(),
            action_type=action_type,
            target_locator=target_locator,
            locator_strategy=locator_strategy,
            readiness_passed=readiness_passed,
            execution_success=execution_success,
            state_hash_before=state_hash_before,
            state_hash_after=state_hash_after,
            state_changed=state_changed,
            hamming_distance=hamming_distance,
            url_before=url_before,
            url_after=url_after,
            url_changed=url_changed,
            error_detected=error_detected,
            error_type=error_type,
            monitor_stuck_score=monitor_stuck_score,
            monitor_milestone_score=monitor_milestone_score,
            escalation_decision=escalation_decision,
            recovery_attempted=recovery_attempted,
            recovery_success=recovery_success,
            integration_mode=integration_mode,
            metadata=meta,
        )
        return self.add_record(record)

    def add_record(self, record: TrajectoryRecord) -> TrajectoryWindow:
        """Add an existing TrajectoryRecord and return its sliding window."""
        run_id = record.run_id
        recent_queue = self._recent_steps_by_run[run_id]

        # Prior history excludes the current step
        history = list(recent_queue)

        # Build window
        window_id = f"{run_id}_step{record.step_id}_w{len(history) + 1}"
        window = TrajectoryWindow(
            window_id=window_id,
            current_step=record,
            history=history,
            window_size=len(history) + 1,
            metadata={
                "run_id": run_id,
                "task_id": record.task_id,
                "timestamp": record.timestamp,
            },
        )

        # Update buffers
        recent_queue.append(record)
        self._records.append(record)
        self._windows.append(window)

        return window

    def get_records(self, run_id: Optional[str] = None) -> List[TrajectoryRecord]:
        """Get all stored records, optionally filtered by run_id."""
        if run_id:
            return [r for r in self._records if r.run_id == run_id]
        return list(self._records)

    def get_windows(self, run_id: Optional[str] = None) -> List[TrajectoryWindow]:
        """Get all stored windows, optionally filtered by run_id."""
        if run_id:
            return [w for w in self._windows if w.metadata.get("run_id") == run_id]
        return list(self._windows)

    def clear(self) -> None:
        """Clear all stored records and windows."""
        self._records.clear()
        self._windows.clear()
        self._recent_steps_by_run.clear()

    def export_records_jsonl(self, filepath: Optional[Union[str, Path]] = None) -> Path:
        """Export individual records to JSONL.

        Args:
            filepath: Optional destination path (default: {output_dir}/trajectory_records.jsonl).
        """
        dest = Path(filepath) if filepath else self.output_dir / "trajectory_records.jsonl"
        dest.parent.mkdir(parents=True, exist_ok=True)

        with open(dest, "w", encoding="utf-8") as f:
            for record in self._records:
                data = record.to_dict()
                if self.auto_redact:
                    data = redact_sensitive_data(data)
                f.write(json.dumps(data) + "\n")

        logger.info(f"Exported {len(self._records)} trajectory records to {dest}")
        return dest

    def export_windows_jsonl(self, filepath: Optional[Union[str, Path]] = None) -> Path:
        """Export sliding windows to JSONL.

        Args:
            filepath: Optional destination path (default: {output_dir}/trajectory_windows.jsonl).
        """
        dest = Path(filepath) if filepath else self.output_dir / "trajectory_windows.jsonl"
        dest.parent.mkdir(parents=True, exist_ok=True)

        with open(dest, "w", encoding="utf-8") as f:
            for window in self._windows:
                data = window.to_dict()
                if self.auto_redact:
                    data = redact_sensitive_data(data)
                f.write(json.dumps(data) + "\n")

        logger.info(f"Exported {len(self._windows)} trajectory windows to {dest}")
        return dest
