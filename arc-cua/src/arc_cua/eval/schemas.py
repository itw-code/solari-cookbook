"""Evaluation Schemas for ARC (Phase 4A).

Implements Task 4A.1:
- Structured data schemas for tasks, assertions, evaluation results, cost ledgers, and scorecards.
- Serialization and deserialization utilities.
- Clean contract for both Reflex-only and Hybrid mode execution.
"""

from __future__ import annotations

import dataclasses
import enum
import time
from typing import Any, Dict, List, Optional, Union

from ..schemas import ActionStep


class AssertionType(str, enum.Enum):
    """Supported evaluation assertion types."""
    URL = "url"
    VISIBLE_TEXT = "visible_text"
    ELEMENT_STATE = "element_state"
    STATE_HASH_CHANGED = "state_hash_changed"
    PAGE_TITLE = "page_title"
    INPUT_VALUE = "input_value"


class ElementState(str, enum.Enum):
    """Element interactive / DOM states for element_state assertions."""
    VISIBLE = "visible"
    HIDDEN = "hidden"
    ATTACHED = "attached"
    DETACHED = "detached"
    ENABLED = "enabled"
    DISABLED = "disabled"
    CHECKED = "checked"


@dataclasses.dataclass
class EvalAssertion:
    """Assertion contract to verify task completion and intermediate states."""
    type: Union[AssertionType, str]
    selector: Optional[str] = None
    expected: Any = None
    description: Optional[str] = None
    timeout_ms: float = 2000.0
    min_width: float = 1.0
    min_height: float = 1.0

    def __post_init__(self):
        if isinstance(self.type, str):
            try:
                self.type = AssertionType(self.type)
            except ValueError:
                pass

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value if isinstance(self.type, AssertionType) else str(self.type),
            "selector": self.selector,
            "expected": self.expected,
            "description": self.description,
            "timeout_ms": self.timeout_ms,
            "min_width": self.min_width,
            "min_height": self.min_height,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EvalAssertion:
        return cls(
            type=data.get("type", "url"),
            selector=data.get("selector"),
            expected=data.get("expected"),
            description=data.get("description"),
            timeout_ms=float(data.get("timeout_ms", 2000.0)),
            min_width=float(data.get("min_width", 1.0)),
            min_height=float(data.get("min_height", 1.0)),
        )


@dataclasses.dataclass
class EvalAssertionResult:
    """Evaluation outcome for an individual assertion."""
    assertion: EvalAssertion
    passed: bool
    actual: Any = None
    error_message: Optional[str] = None
    latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "assertion": self.assertion.to_dict(),
            "passed": self.passed,
            "actual": self.actual,
            "error_message": self.error_message,
            "latency_ms": round(self.latency_ms, 2),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EvalAssertionResult:
        assertion_data = data.get("assertion", {})
        assertion = EvalAssertion.from_dict(assertion_data) if isinstance(assertion_data, dict) else assertion_data
        return cls(
            assertion=assertion,
            passed=bool(data.get("passed", False)),
            actual=data.get("actual"),
            error_message=data.get("error_message"),
            latency_ms=float(data.get("latency_ms", 0.0)),
        )


@dataclasses.dataclass
class CostRecord:
    """Task-level cost accounting record."""
    task_id: str
    mock_cortex_cost_usd: float = 0.0
    local_reflex_cost_usd: float = 0.0
    browser_runtime_ms: float = 0.0
    estimated_infra_cost_usd: float = 0.0
    total_cost_usd: float = 0.0
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "mock_cortex_cost_usd": self.mock_cortex_cost_usd,
            "local_reflex_cost_usd": self.local_reflex_cost_usd,
            "browser_runtime_ms": round(self.browser_runtime_ms, 2),
            "estimated_infra_cost_usd": self.estimated_infra_cost_usd,
            "total_cost_usd": self.total_cost_usd,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CostRecord:
        return cls(
            task_id=data.get("task_id", ""),
            mock_cortex_cost_usd=float(data.get("mock_cortex_cost_usd", 0.0)),
            local_reflex_cost_usd=float(data.get("local_reflex_cost_usd", 0.0)),
            browser_runtime_ms=float(data.get("browser_runtime_ms", 0.0)),
            estimated_infra_cost_usd=float(data.get("estimated_infra_cost_usd", 0.0)),
            total_cost_usd=float(data.get("total_cost_usd", 0.0)),
            metadata=data.get("metadata", {}),
        )


@dataclasses.dataclass
class EvalTask:
    """Specification of an evaluation task."""
    task_id: str
    name: str
    category: str
    description: str
    start_url: str
    action_steps: List[Union[ActionStep, Dict[str, Any]]] = dataclasses.field(default_factory=list)
    expected_assertions: List[EvalAssertion] = dataclasses.field(default_factory=list)
    max_steps: int = 20
    timeout_ms: float = 30000.0
    tags: List[str] = dataclasses.field(default_factory=list)
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        steps_dicts = []
        for s in self.action_steps:
            if isinstance(s, ActionStep):
                steps_dicts.append(dataclasses.asdict(s))
            elif isinstance(s, dict):
                steps_dicts.append(s)
            else:
                steps_dicts.append(str(s))

        return {
            "task_id": self.task_id,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "start_url": self.start_url,
            "action_steps": steps_dicts,
            "expected_assertions": [a.to_dict() for a in self.expected_assertions],
            "max_steps": self.max_steps,
            "timeout_ms": self.timeout_ms,
            "tags": self.tags,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EvalTask:
        raw_steps = data.get("action_steps", [])
        steps: List[Union[ActionStep, Dict[str, Any]]] = []
        for s in raw_steps:
            if isinstance(s, dict) and "verb" in s:
                steps.append(s)
            else:
                steps.append(s)

        raw_assertions = data.get("expected_assertions", [])
        assertions = [EvalAssertion.from_dict(a) if isinstance(a, dict) else a for a in raw_assertions]

        return cls(
            task_id=data.get("task_id", ""),
            name=data.get("name", ""),
            category=data.get("category", "general"),
            description=data.get("description", ""),
            start_url=data.get("start_url", ""),
            action_steps=steps,
            expected_assertions=assertions,
            max_steps=int(data.get("max_steps", 20)),
            timeout_ms=float(data.get("timeout_ms", 30000.0)),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
        )


@dataclasses.dataclass
class EvalResult:
    """Outcome of running an EvalTask."""
    task_id: str
    success: bool
    total_steps: int = 0
    reflex_steps: int = 0
    escalations: int = 0
    recoveries_attempted: int = 0
    recoveries_succeeded: int = 0
    milestones_detected: int = 0
    aborted: bool = False
    abort_reason: Optional[str] = None
    duration_ms: float = 0.0
    cost_usd: float = 0.0
    telemetry_summary: Dict[str, Any] = dataclasses.field(default_factory=dict)
    assertion_results: List[EvalAssertionResult] = dataclasses.field(default_factory=list)
    mode: str = "hybrid"
    completed_steps: List[ActionStep] = dataclasses.field(default_factory=list)
    final_state_hash: Optional[int] = None
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "success": self.success,
            "total_steps": self.total_steps,
            "reflex_steps": self.reflex_steps,
            "escalations": self.escalations,
            "recoveries_attempted": self.recoveries_attempted,
            "recoveries_succeeded": self.recoveries_succeeded,
            "milestones_detected": self.milestones_detected,
            "aborted": self.aborted,
            "abort_reason": self.abort_reason,
            "duration_ms": round(self.duration_ms, 2),
            "cost_usd": self.cost_usd,
            "telemetry_summary": self.telemetry_summary,
            "assertion_results": [a.to_dict() for a in self.assertion_results],
            "mode": self.mode,
            "completed_steps": [dataclasses.asdict(s) for s in self.completed_steps],
            "final_state_hash": hex(self.final_state_hash) if self.final_state_hash is not None else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EvalResult:
        raw_assertions = data.get("assertion_results", [])
        assertion_results = [
            EvalAssertionResult.from_dict(a) if isinstance(a, dict) else a
            for a in raw_assertions
        ]
        raw_steps = data.get("completed_steps", [])
        completed_steps = [
            ActionStep(**s) if isinstance(s, dict) else s
            for s in raw_steps
        ]
        state_hash = data.get("final_state_hash")
        if isinstance(state_hash, str) and state_hash.startswith("0x"):
            parsed_hash = int(state_hash, 16)
        elif isinstance(state_hash, int):
            parsed_hash = state_hash
        else:
            parsed_hash = None

        return cls(
            task_id=data.get("task_id", ""),
            success=bool(data.get("success", False)),
            total_steps=int(data.get("total_steps", 0)),
            reflex_steps=int(data.get("reflex_steps", 0)),
            escalations=int(data.get("escalations", 0)),
            recoveries_attempted=int(data.get("recoveries_attempted", 0)),
            recoveries_succeeded=int(data.get("recoveries_succeeded", 0)),
            milestones_detected=int(data.get("milestones_detected", 0)),
            aborted=bool(data.get("aborted", False)),
            abort_reason=data.get("abort_reason"),
            duration_ms=float(data.get("duration_ms", 0.0)),
            cost_usd=float(data.get("cost_usd", 0.0)),
            telemetry_summary=data.get("telemetry_summary", {}),
            assertion_results=assertion_results,
            mode=data.get("mode", "hybrid"),
            completed_steps=completed_steps,
            final_state_hash=parsed_hash,
            metadata=data.get("metadata", {}),
        )


@dataclasses.dataclass
class ScorecardSummary:
    """Aggregated scorecard metrics across an evaluation run."""
    total_tasks: int = 0
    successful_tasks: int = 0
    success_rate: float = 0.0
    avg_duration_ms: float = 0.0
    p50_duration_ms: float = 0.0
    p95_duration_ms: float = 0.0
    p99_duration_ms: float = 0.0
    total_steps: int = 0
    avg_steps_per_task: float = 0.0
    reflex_step_share: float = 0.0
    escalation_rate: float = 0.0
    recovery_attempt_rate: float = 0.0
    recovery_success_rate: float = 0.0
    milestone_detection_count: int = 0
    abort_rate: float = 0.0
    total_cost_usd: float = 0.0
    avg_cost_per_task_usd: float = 0.0
    assertion_failure_count: int = 0
    mode: str = "hybrid"
    details: Dict[str, Any] = dataclasses.field(default_factory=dict)
    comparison: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_tasks": self.total_tasks,
            "successful_tasks": self.successful_tasks,
            "success_rate": round(self.success_rate, 4),
            "avg_duration_ms": round(self.avg_duration_ms, 2),
            "p50_duration_ms": round(self.p50_duration_ms, 2),
            "p95_duration_ms": round(self.p95_duration_ms, 2),
            "p99_duration_ms": round(self.p99_duration_ms, 2),
            "total_steps": self.total_steps,
            "avg_steps_per_task": round(self.avg_steps_per_task, 2),
            "reflex_step_share": round(self.reflex_step_share, 4),
            "escalation_rate": round(self.escalation_rate, 4),
            "recovery_attempt_rate": round(self.recovery_attempt_rate, 4),
            "recovery_success_rate": round(self.recovery_success_rate, 4),
            "milestone_detection_count": self.milestone_detection_count,
            "abort_rate": round(self.abort_rate, 4),
            "total_cost_usd": round(self.total_cost_usd, 6),
            "avg_cost_per_task_usd": round(self.avg_cost_per_task_usd, 6),
            "assertion_failure_count": self.assertion_failure_count,
            "mode": self.mode,
            "details": self.details,
            "comparison": self.comparison,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ScorecardSummary:
        return cls(
            total_tasks=int(data.get("total_tasks", 0)),
            successful_tasks=int(data.get("successful_tasks", 0)),
            success_rate=float(data.get("success_rate", 0.0)),
            avg_duration_ms=float(data.get("avg_duration_ms", 0.0)),
            p50_duration_ms=float(data.get("p50_duration_ms", 0.0)),
            p95_duration_ms=float(data.get("p95_duration_ms", 0.0)),
            p99_duration_ms=float(data.get("p99_duration_ms", 0.0)),
            total_steps=int(data.get("total_steps", 0)),
            avg_steps_per_task=float(data.get("avg_steps_per_task", 0.0)),
            reflex_step_share=float(data.get("reflex_step_share", 0.0)),
            escalation_rate=float(data.get("escalation_rate", 0.0)),
            recovery_attempt_rate=float(data.get("recovery_attempt_rate", 0.0)),
            recovery_success_rate=float(data.get("recovery_success_rate", 0.0)),
            milestone_detection_count=int(data.get("milestone_detection_count", 0)),
            abort_rate=float(data.get("abort_rate", 0.0)),
            total_cost_usd=float(data.get("total_cost_usd", 0.0)),
            avg_cost_per_task_usd=float(data.get("avg_cost_per_task_usd", 0.0)),
            assertion_failure_count=int(data.get("assertion_failure_count", 0)),
            mode=data.get("mode", "hybrid"),
            details=data.get("details", {}),
            comparison=data.get("comparison"),
        )


@dataclasses.dataclass
class EvalRunSummary:
    """Full evaluation run encapsulation."""
    run_id: str
    timestamp: float = dataclasses.field(default_factory=time.time)
    mode: str = "hybrid"
    environment: Dict[str, Any] = dataclasses.field(default_factory=dict)
    scorecard: ScorecardSummary = dataclasses.field(default_factory=ScorecardSummary)
    results: List[EvalResult] = dataclasses.field(default_factory=list)
    total_duration_ms: float = 0.0
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "mode": self.mode,
            "environment": self.environment,
            "scorecard": self.scorecard.to_dict(),
            "results": [r.to_dict() for r in self.results],
            "total_duration_ms": round(self.total_duration_ms, 2),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EvalRunSummary:
        raw_results = data.get("results", [])
        results = [EvalResult.from_dict(r) if isinstance(r, dict) else r for r in raw_results]
        raw_sc = data.get("scorecard", {})
        scorecard = ScorecardSummary.from_dict(raw_sc) if isinstance(raw_sc, dict) else raw_sc

        return cls(
            run_id=data.get("run_id", ""),
            timestamp=float(data.get("timestamp", time.time())),
            mode=data.get("mode", "hybrid"),
            environment=data.get("environment", {}),
            scorecard=scorecard,
            results=results,
            total_duration_ms=float(data.get("total_duration_ms", 0.0)),
            metadata=data.get("metadata", {}),
        )
