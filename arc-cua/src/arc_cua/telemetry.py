"""Perception and Trajectory Telemetry Collector with Statistical Percentiles.

Remediates Task 6:
- Records execution telemetry (perception latency, serialization latency, action latency).
- Implements 64-bit SimHash state fingerprinting per ARCHITECTURE.md §4.1.
- Computes empirical p50, p95, and p99 percentile distributions.
- Exports structured telemetry to JSONL and Parquet-compatible tabular formats.
"""

from __future__ import annotations

import collections
import dataclasses
import hashlib
import json
import logging
import math
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from .schemas import TelemetryRecord, TrajectoryRecord, TrajectoryWindow

logger = logging.getLogger("arc_cua.telemetry")


def compute_simhash64(text: str) -> int:
    """Compute a deterministic 64-bit SimHash fingerprint for an accessibility tree.

    Used by the Stuck Monitor to detect:
    - Zero-pixel traps: H(s_t) == H(s_{t-1})
    - Cyclic oscillations: H(s_t) == H(s_{t-2}) and a_t == a_{t-2}

    Args:
        text: Normalized YAML or serialized UI state string.

    Returns:
        64-bit unsigned integer hash.
    """
    if not text:
        return 0

    tokens = text.split()
    if not tokens:
        tokens = [text]

    token_counts = collections.Counter(tokens)
    v = [0] * 64
    for token, count in token_counts.items():
        digest = hashlib.md5(token.encode("utf-8")).digest()
        h = int.from_bytes(digest[:8], byteorder="big", signed=False)
        for i in range(64):
            bit = (h >> i) & 1
            v[i] += count if bit else -count

    fingerprint = 0
    for i in range(64):
        if v[i] > 0:
            fingerprint |= 1 << i

    return fingerprint


@dataclasses.dataclass(frozen=True)
class MetricDistribution:
    """Statistical summary of latency or resource distribution."""
    metric_name: str
    count: int
    mean: float
    min: float
    max: float
    p50: float
    p95: float
    p99: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "count": self.count,
            "mean": round(self.mean, 4),
            "min": round(self.min, 4),
            "max": round(self.max, 4),
            "p50": round(self.p50, 4),
            "p95": round(self.p95, 4),
            "p99": round(self.p99, 4),
        }


def compute_percentiles(values: Sequence[float], metric_name: str = "metric") -> MetricDistribution:
    """Calculate count, mean, min, max, p50, p95, p99 from a sequence of floats."""
    if not values:
        return MetricDistribution(metric_name, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mean_val = sum(sorted_vals) / n

    def _get_pct(p: float) -> float:
        idx = int(math.ceil((p / 100.0) * n)) - 1
        idx = max(0, min(n - 1, idx))
        return sorted_vals[idx]

    return MetricDistribution(
        metric_name=metric_name,
        count=n,
        mean=mean_val,
        min=sorted_vals[0],
        max=sorted_vals[-1],
        p50=_get_pct(50.0),
        p95=_get_pct(95.0),
        p99=_get_pct(99.0),
    )


class TelemetryCollector:
    """In-memory and persistent telemetry engine tracking microVM and perception metrics."""

    def __init__(self, session_id: str = "default_session"):
        self.session_id = session_id
        self._metric_buffers: Dict[str, List[float]] = collections.defaultdict(list)
        self._records: List[TelemetryRecord] = []
        self.trajectory_collector = TrajectoryCollector(
            output_dir="artifacts/phase3b/trajectory_logs"
        )
    def record_metric(self, name: str, value: float) -> None:
        """Record a numeric observation (e.g. latency, token count, memory)."""
        self._metric_buffers[name].append(float(value))

    def log_record(self, record: TelemetryRecord) -> None:
        """Append a complete structured TelemetryRecord."""
        self._records.append(record)
        self.record_metric("step_latency_ms", record.total_step_latency_ms)
        self.record_metric("perception_latency_ms", record.perception_latency_ms)
        self.record_metric("tokens_consumed", float(record.tokens_consumed))
        self.record_metric("memory_overhead_mb", record.memory_overhead_mb)
        # Phase 3 metrics
        self.record_metric("monitor_stuck_score", float(record.monitor_stuck_score))
        self.record_metric("monitor_milestone_score", float(record.monitor_milestone_score))
        if record.estimated_cost_usd > 0.0:
            self.record_metric("estimated_cost_usd", float(record.estimated_cost_usd))

    # Alias for compatibility with callers
    record = log_record

    def get_distribution(self, name: str) -> MetricDistribution:
        """Retrieve statistical distribution (p50, p95, p99) for a recorded metric."""
        return compute_percentiles(self._metric_buffers.get(name, []), metric_name=name)

    def get_summary(self) -> Dict[str, Dict[str, Any]]:
        """Return full summary of all tracked metrics."""
        summary = {}
        for k in sorted(self._metric_buffers.keys()):
            summary[k] = self.get_distribution(k).to_dict()
        return summary

    def get_monitor_summary(self) -> Dict[str, Any]:
        """Return aggregated summary of monitor decisions, scores, and costs."""
        decisions = collections.Counter(r.escalation_decision for r in self._records if r.escalation_decision)
        reasons = collections.Counter(r.escalation_reason for r in self._records if r.escalation_reason)
        total_cost = sum(r.estimated_cost_usd for r in self._records)
        recoveries_used = max((r.recoveries_used for r in self._records), default=0)
        escalations_used = max((r.escalations_used for r in self._records), default=0)

        return {
            "total_records": len(self._records),
            "decisions_count": dict(decisions),
            "reasons_count": dict(reasons),
            "recoveries_used": recoveries_used,
            "escalations_used": escalations_used,
            "total_estimated_cost_usd": round(total_cost, 6),
            "stuck_score_distribution": self.get_distribution("monitor_stuck_score").to_dict(),
            "milestone_score_distribution": self.get_distribution("monitor_milestone_score").to_dict(),
        }

    @staticmethod
    def _sanitize_for_export(obj: Any) -> Any:
        """Redact sensitive fields (passwords, tokens, api keys) before export."""
        sensitive_keywords = {"password", "secret", "token", "api_key", "auth", "credential"}
        if isinstance(obj, dict):
            sanitized = {}
            for k, v in obj.items():
                if any(sec in str(k).lower() for sec in sensitive_keywords):
                    sanitized[k] = "[REDACTED]"
                else:
                    sanitized[k] = TelemetryCollector._sanitize_for_export(v)
            return sanitized
        elif isinstance(obj, list):
            return [TelemetryCollector._sanitize_for_export(elem) for elem in obj]
        return obj

    def export_jsonl(self, filepath: Union[str, Path]) -> Path:
        """Export all recorded telemetry rows to JSONL format with credential redaction."""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for r in self._records:
                raw_dict = dataclasses.asdict(r)
                sanitized_dict = self._sanitize_for_export(raw_dict)
                line = json.dumps(sanitized_dict)
                f.write(line + "\n")
        return path

    def export_summary_json(self, filepath: Union[str, Path]) -> Path:
        """Export summary distributions and monitor summary to JSON."""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "distributions": self.get_summary(),
            "monitors": self.get_monitor_summary(),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return path

    def record_trajectory_step(
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
        timestamp: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TrajectoryWindow:
        """Record a structured step into the integrated TrajectoryCollector."""
        return self.trajectory_collector.record_step(
            run_id=run_id,
            task_id=task_id,
            step_id=step_id,
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
            timestamp=timestamp,
            metadata=metadata,
        )

    def export_trajectories(self, output_dir: Optional[Union[str, Path]] = None) -> Dict[str, Path]:
        """Export trajectory records and windows to JSONL in the specified or default directory."""
        out = Path(output_dir) if output_dir else self.trajectory_collector.output_dir
        records_path = self.trajectory_collector.export_records_jsonl(out / "trajectory_records.jsonl")
        windows_path = self.trajectory_collector.export_windows_jsonl(out / "trajectory_windows.jsonl")
        return {
            "records": records_path,
            "windows": windows_path,
        }


# Lazy import or re-export of TrajectoryCollector to avoid circular dependency
from .datasets.trajectory_collector import TrajectoryCollector  # noqa: E402
