"""Arc-Native Hybrid Computer Use Agent (CUA) - Phase 1: Infrastructure & Perception.

Provides:
- ArcVMManager: MicroVM lifecycle orchestrator with UDS isolation and UFFD snapshot hooks.
- ArcImageProvider, VMImageSpec: Dynamic kernel/rootfs resolution.
- CDP_AXTree_Extractor, AXNode, SanitizedAXTree: Chromium accessibility tree extractor & sanitizer.
- CDPDiscovery, CDPEndpointSpec: Dynamic CDP endpoint discovery.
- AT_SPI_Bridge, DesktopNode, ATSPIEvent: Linux desktop AT-SPI2 D-Bus bridge.
- PlaywrightActionExecutorInterface, ActionVerb, ActionPayload, ExecutionOutcome: Phase 2 contract.
- UIState, ActionStep, EscalationPayload, EscalationReason, TelemetryRecord: Unified schemas.
- TelemetryCollector, MetricDistribution, compute_simhash64: Telemetry & percentiles.
"""

from .vm_manager import ArcVMManager, VMMetadata, SnapshotMetadata
from .image_provider import ArcImageProvider, VMImageSpec
from .cdp_extractor import CDP_AXTree_Extractor, AXNode, SanitizedAXTree
from .cdp_discovery import CDPDiscovery, CDPEndpointSpec
from .at_spi_bridge import AT_SPI_Bridge, DesktopNode, ATSPIEvent
from .executor_interface import (
    ActionExecutor,
    PlaywrightActionExecutorInterface,
    BasePlaywrightExecutor,
    ActionVerb,
    ActionPayload,
    ExecutionOutcome,
    audit_public_api_compliance,
)
from .playwright_executor import PlaywrightExecutor
from .locator_resolver import (
    LocatorResolver,
    ResolvedLocator,
    LocatorResolutionError,
    SelectorLRUCache,
)
from .session_guard import SessionGuard, ReadinessResult
from .state_verifier import (
    StateVerifier,
    StateVerificationResult,
    compute_hamming_distance,
)
from .reflex_runner import ReflexRunner, ReflexStatus, ReflexExecutionResult
from .schemas import (
    PerceptionSource,
    EscalationReason,
    UIState,
    ActionStep,
    EscalationPayload,
    TelemetryRecord,
    ActionResult,
    DecisionType,
    PlanSource,
    StuckSignal,
    MilestoneSignal,
    MonitorSignals,
    EscalationDecision,
    RecoveryPlan,
    CortexResponse,
    HybridRunResult,
)
from .telemetry import (
    TelemetryCollector,
    MetricDistribution,
    compute_percentiles,
    compute_simhash64,
)
from .monitors import (
    StuckMonitor,
    StepTelemetry,
    MilestoneMonitor,
    EscalationController,
)
from .cortex import (
    CortexClient,
    MockCortexClient,
    RecoveryCompiler,
    RecoveryCompilationError,
)
from .hybrid_runner import HybridRunner

__all__ = [
    "ArcVMManager",
    "VMMetadata",
    "SnapshotMetadata",
    "ArcImageProvider",
    "VMImageSpec",
    "CDP_AXTree_Extractor",
    "AXNode",
    "SanitizedAXTree",
    "CDPDiscovery",
    "CDPEndpointSpec",
    "AT_SPI_Bridge",
    "DesktopNode",
    "ATSPIEvent",
    "ActionExecutor",
    "PlaywrightExecutor",
    "LocatorResolver",
    "ResolvedLocator",
    "LocatorResolutionError",
    "SelectorLRUCache",
    "SessionGuard",
    "ReadinessResult",
    "StateVerifier",
    "StateVerificationResult",
    "compute_hamming_distance",
    "ReflexRunner",
    "ReflexStatus",
    "ReflexExecutionResult",
    "BasePlaywrightExecutor",
    "ActionVerb",
    "ActionPayload",
    "ExecutionOutcome",
    "audit_public_api_compliance",
    "PerceptionSource",
    "EscalationReason",
    "UIState",
    "ActionStep",
    "EscalationPayload",
    "TelemetryRecord",
    "ActionResult",
    "compute_simhash64",
    "DecisionType",
    "PlanSource",
    "StuckSignal",
    "MilestoneSignal",
    "MonitorSignals",
    "EscalationDecision",
    "RecoveryPlan",
    "CortexResponse",
    "HybridRunResult",
    "StuckMonitor",
    "StepTelemetry",
    "MilestoneMonitor",
    "EscalationController",
    "CortexClient",
    "MockCortexClient",
    "RecoveryCompiler",
    "RecoveryCompilationError",
    "HybridRunner",
]
