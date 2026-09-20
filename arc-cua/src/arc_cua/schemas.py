"""Unified Perception, Action, and Telemetry Schemas for ARC.

Remediates Task 1 & Checklist Requirements:
- Structured data schemas for AXTree/AT-SPI perceptions, actions, and trajectory telemetry.
- Provides standard contract between Perception (Phase 1), Reflex (Phase 2), and Cortex (Phase 3).
- Implements 64-bit SimHash state fingerprinting and escalation recovery formats.
"""

from __future__ import annotations

import dataclasses
import enum
import time
from typing import Any, Dict, List, Optional, Tuple


class PerceptionSource(str, enum.Enum):
    """Source subsystem providing UI accessibility state."""
    CDP_AXTREE = "cdp_axtree"
    AT_SPI_DESKTOP = "at_spi_desktop"
    VISUAL_OMNIPARSER = "visual_omniparser"


class EscalationReason(str, enum.Enum):
    """Failure signatures triggering escalation from Reflex to Cortex."""
    CYCLIC_LOOP = "CYCLIC_LOOP"
    CANVAS_OCCLUSION = "CANVAS_OCCLUSION"
    LOCATOR_NOT_FOUND = "LOCATOR_NOT_FOUND"
    SEMANTIC_DRIFT = "SEMANTIC_DRIFT"
    ACTION_TIMEOUT = "ACTION_TIMEOUT"
    PROCESS_CRASH = "PROCESS_CRASH"
    MANUAL_TRIGGER = "MANUAL_TRIGGER"
    STATE_NOT_CHANGED = "STATE_NOT_CHANGED"
    READINESS_TIMEOUT = "READINESS_TIMEOUT"
    ESCALATION_REQUIRED = "ESCALATION_REQUIRED"


class DecisionType(str, enum.Enum):
    """Escalation controller decision outcomes."""
    CONTINUE = "continue"
    RECOVER_LOCALLY = "recover_locally"
    ESCALATE = "escalate"
    ABORT = "abort"


class PlanSource(str, enum.Enum):
    """Source engine that produced the recovery plan."""
    MOCK = "mock"
    REAL_CORTEX = "real_cortex"
    LOCAL_RECOVERY = "local_recovery"

@dataclasses.dataclass
class UIState:
    """Snapshot of localized accessibility state."""
    state_id: str
    timestamp: float
    source: PerceptionSource
    simhash: int  # 64-bit state fingerprint
    raw_node_count: int
    pruned_node_count: int
    actionable_count: int
    estimated_tokens: int
    yaml_representation: str
    structured_tree: Dict[str, Any]
    action_index_map: Dict[int, Dict[str, Any]]
    active_window_title: Optional[str] = None
    focused_element: Optional[str] = None


@dataclasses.dataclass
class ActionStep:
    """Historical telemetry record of a single executed step."""
    step_number: int
    verb: str
    target_selector: Optional[str]
    value: Optional[str]
    action_index: Optional[int]
    latency_ms: float
    success: bool
    resulting_url: Optional[str] = None
    error_message: Optional[str] = None
    timestamp: float = dataclasses.field(default_factory=time.time)

@dataclasses.dataclass
class ActionResult:
    """Structured result of executing an individual action via Playwright or Reflex engine."""
    success: bool
    verb: str
    target_selector: Optional[str] = None
    value: Optional[str] = None
    latency_ms: float = 0.0
    resulting_url: Optional[str] = None
    error_message: Optional[str] = None
    retries_count: int = 0
    action: Optional[Any] = None
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)
    timestamp: float = dataclasses.field(default_factory=time.time)

    @property
    def execution_latency_ms(self) -> float:
        """Compatibility alias matching ExecutionOutcome."""
        return self.latency_ms

    def to_action_step(self, step_number: int, action_index: Optional[int] = None) -> ActionStep:
        return ActionStep(
            step_number=step_number,
            verb=self.verb,
            target_selector=self.target_selector,
            value=self.value,
            action_index=action_index,
            latency_ms=self.latency_ms,
            success=self.success,
            resulting_url=self.resulting_url,
            error_message=self.error_message,
            timestamp=self.timestamp,
        )


@dataclasses.dataclass
class EscalationPayload:
    """Complete diagnostic payload routed to Cortex (Frontier Model) on anomaly."""
    escalation_id: str
    task_goal: str
    reason: EscalationReason
    step_history: List[ActionStep]
    current_state: UIState
    failure_details: Dict[str, Any]
    timestamp: float = dataclasses.field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "escalation_id": self.escalation_id,
            "task_goal": self.task_goal,
            "reason": self.reason.value,
            "failure_details": self.failure_details,
            "timestamp": self.timestamp,
            "current_state": {
                "state_id": self.current_state.state_id,
                "source": self.current_state.source.value,
                "simhash": hex(self.current_state.simhash),
                "tokens": self.current_state.estimated_tokens,
                "yaml": self.current_state.yaml_representation,
            },
            "step_history": [dataclasses.asdict(s) for s in self.step_history],
        }


@dataclasses.dataclass
class TelemetryRecord:
    """Point-in-time telemetry snapshot logged to telemetry log."""
    session_id: str
    vm_id: str
    step_index: int
    route: str  # "reflex" or "cortex"
    total_step_latency_ms: float
    perception_latency_ms: float
    action_latency_ms: float
    tokens_consumed: int
    memory_overhead_mb: float
    sockets_active_count: int
    success: bool
    timestamp: float = dataclasses.field(default_factory=time.time)
    monitor_stuck_score: float = 0.0
    monitor_milestone_score: float = 0.0
    escalation_decision: Optional[str] = None
    escalation_reason: Optional[str] = None
    cooldown_active: bool = False
    recovery_plan_source: Optional[str] = None
    recovery_success: Optional[bool] = None
    recoveries_used: int = 0
    escalations_used: int = 0
    estimated_cost_usd: float = 0.0
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class StuckSignal:
    """Signal output by the Stuck Monitor indicating potential loop/traps."""
    stuck_score: float
    is_stuck: bool
    reason: str = ""
    evidence: Dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class MilestoneSignal:
    """Signal output by the Milestone Monitor indicating meaningful progress."""
    milestone_score: float
    is_milestone: bool
    milestone_type: str = ""
    evidence: Dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class MonitorSignals:
    """Combined per-step monitor evaluation signals."""
    step_id: int
    stuck_score: float = 0.0
    milestone_score: float = 0.0
    state_changed: bool = False
    consecutive_no_change: int = 0
    repeated_locator_count: int = 0
    readiness_timeout_count: int = 0
    action_exception_count: int = 0
    state_hash: int = 0
    previous_state_hash: int = 0
    url_changed: bool = False
    error_detected: bool = False
    cooldown_active: bool = False
    escalations_used: int = 0
    details: Dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class EscalationDecision:
    """Outcome of the Escalation Controller deciding whether to continue, recover, escalate, or abort."""
    decision: Union[DecisionType, str]
    reason: str = ""
    confidence: float = 1.0
    required_action: Optional[str] = None
    cooldown_steps: int = 0
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class RecoveryPlan:
    """Structured, executable recovery sequence generated by Mock or Real Cortex."""
    plan_id: str
    source: Union[PlanSource, str]
    actions: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    expected_outcome: str = ""
    stop_condition: str = ""
    confidence: float = 1.0
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class CortexResponse:
    """Container response from Cortex Client invocation."""
    plan: Optional[RecoveryPlan] = None
    raw_response: Optional[str] = None
    model: Optional[str] = None
    latency_ms: float = 0.0
    tokens_used: int = 0
    cost_usd: float = 0.0
    success: bool = True
    error: Optional[str] = None
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class HybridRunResult:
    """Final summary outcome of a Hybrid Runner execution combining Reflex and Cortex."""
    success: bool
    total_steps: int
    reflex_steps: int
    escalations: int
    recoveries_attempted: int
    recoveries_succeeded: int
    milestones_detected: int
    aborted: bool
    abort_reason: Optional[str] = None
    final_state_hash: int = 0
    telemetry_summary: Dict[str, Any] = dataclasses.field(default_factory=dict)
    completed_steps: List[ActionStep] = dataclasses.field(default_factory=list)
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class TrajectoryRecord:
    """Individual trajectory step record for dataset collection and learned monitor training."""
    run_id: str
    task_id: str
    step_id: int
    timestamp: float = dataclasses.field(default_factory=time.time)
    action_type: str = ""
    target_locator: Optional[str] = None
    locator_strategy: Optional[str] = None
    readiness_passed: bool = True
    execution_success: bool = True
    state_hash_before: Union[int, str] = 0
    state_hash_after: Union[int, str] = 0
    state_changed: bool = False
    hamming_distance: int = 0
    url_before: Optional[str] = None
    url_after: Optional[str] = None
    url_changed: bool = False
    error_detected: bool = False
    error_type: Optional[str] = None
    monitor_stuck_score: float = 0.0
    monitor_milestone_score: float = 0.0
    escalation_decision: Optional[str] = None
    recovery_attempted: bool = False
    recovery_success: Optional[bool] = None
    integration_mode: str = "mock"
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class TrajectoryWindow:
    """Sliding window of trajectory records (e.g. current step + up to 4 previous steps)."""
    window_id: str
    current_step: TrajectoryRecord
    history: List[TrajectoryRecord] = dataclasses.field(default_factory=list)
    window_size: int = 5
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

    @property
    def steps(self) -> List[TrajectoryRecord]:
        return self.history + [self.current_step]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "window_id": self.window_id,
            "window_size": len(self.steps),
            "current_step": self.current_step.to_dict(),
            "history": [s.to_dict() for s in self.history],
            "metadata": self.metadata,
        }
