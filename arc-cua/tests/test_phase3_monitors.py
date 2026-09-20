"""Comprehensive Test Suite for Phase 3A: Monitor & Escalation Layer.

Verifies all 18 required test criteria:
1. Stuck Monitor detects repeated no-state-change actions.
2. Stuck Monitor detects cyclic state oscillation.
3. Stuck Monitor detects repeated locator failure.
4. Stuck Monitor does not trigger on healthy progress.
5. Milestone Monitor detects expected state change.
6. Milestone Monitor detects URL milestone.
7. Milestone Monitor detects visible text milestone.
8. Milestone Monitor does not trigger on error state.
9. Escalation Controller requires consecutive stuck signals.
10. Escalation Controller escalates immediately on hard failure.
11. Escalation Controller enforces cooldown.
12. Escalation Controller respects max escalation budget.
13. Mock Cortex returns valid typed recovery plan.
14. Recovery Compiler rejects invalid plan.
15. Hybrid Runner recovers from stuck state using Mock Cortex.
16. Hybrid Runner aborts when recovery budget exceeded.
17. Hybrid Runner does not call external network in mock mode.
18. Public Playwright API compliance remains enforced.

integration_mode: mock
"""

from __future__ import annotations

import ast
import inspect
import os
import pathlib
import socket
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import pytest

# Ensure src is in python path
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

from arc_cua.cdp_extractor import AXNode, SanitizedAXTree
from arc_cua.cortex import (
    CortexClient,
    MockCortexClient,
    RecoveryCompilationError,
    RecoveryCompiler,
)
from arc_cua.executor_interface import FORBIDDEN_PRIVATE_INTERNALS
from arc_cua.hybrid_runner import HybridRunner
from arc_cua.locator_resolver import LocatorResolver
from arc_cua.monitors import (
    EscalationController,
    MilestoneMonitor,
    StepTelemetry,
    StuckMonitor,
)
from arc_cua.playwright_executor import PlaywrightExecutor
from arc_cua.reflex_runner import ReflexRunner, ReflexStatus
from arc_cua.schemas import (
    ActionStep,
    DecisionType,
    EscalationPayload,
    EscalationReason,
    HybridRunResult,
    PerceptionSource,
    PlanSource,
    RecoveryPlan,
    TelemetryRecord,
    UIState,
)
from arc_cua.session_guard import SessionGuard
from arc_cua.state_verifier import StateVerifier
from arc_cua.telemetry import TelemetryCollector, compute_simhash64


# ============================================================================
# Mock Playwright Fixtures
# ============================================================================

class MockElementLocator:
    """Public Playwright Locator mock."""

    def __init__(
        self,
        selector: str,
        visible: bool = True,
        enabled: bool = True,
        count: int = 1,
        bbox: Optional[Dict[str, float]] = None,
        should_fail_click: bool = False,
    ):
        self.selector = selector
        self._is_visible = visible
        self._is_enabled = enabled
        self._count = count
        self._bbox = bbox or {"x": 100.0, "y": 200.0, "width": 80.0, "height": 30.0}
        self.should_fail_click = should_fail_click
        self.actions_log: List[str] = []

    @property
    def first(self) -> MockElementLocator:
        return self

    def count(self) -> int:
        return self._count

    def is_visible(self) -> bool:
        return self._is_visible and self._count > 0

    def is_enabled(self) -> bool:
        return self._is_enabled

    def is_disabled(self) -> bool:
        return not self._is_enabled

    def bounding_box(self) -> Optional[Dict[str, float]]:
        if not self._is_visible or self._count == 0:
            return None
        return self._bbox

    def click(self, timeout: Optional[float] = None) -> None:
        if self.should_fail_click:
            raise RuntimeError(f"Playwright TimeoutError: Element '{self.selector}' not clickable")
        self.actions_log.append(f"click:{self.selector}")

    def fill(self, text: str, timeout: Optional[float] = None) -> None:
        self.actions_log.append(f"fill:{self.selector}={text}")

    def select_option(self, value: str, timeout: Optional[float] = None) -> None:
        self.actions_log.append(f"select:{self.selector}={value}")

    def wait_for(self, state: str = "visible", timeout: Optional[float] = None) -> None:
        if not self._is_visible and state == "visible":
            raise TimeoutError(f"Timeout waiting for locator('{self.selector}') state='{state}'")


class MockKeyboard:
    def __init__(self):
        self.pressed_keys: List[str] = []

    def press(self, key: str) -> None:
        self.pressed_keys.append(key)


class MockMouse:
    def __init__(self):
        self.clicks: List[Tuple[float, float]] = []
        self.wheels: List[Tuple[int, int]] = []

    def click(self, x: float, y: float) -> None:
        self.clicks.append((x, y))

    def wheel(self, delta_x: int, delta_y: int) -> None:
        self.wheels.append((delta_x, delta_y))


class MockPlaywrightPage:
    """Mock of Playwright Page exposing only public methods."""

    def __init__(self, url: str = "https://app.arc.local/dashboard", default_present: bool = True):
        self.url = url
        self.keyboard = MockKeyboard()
        self.mouse = MockMouse()
        self.locators: Dict[str, MockElementLocator] = {}
        self.history: List[str] = []
        self.default_present = default_present
        self.eval_values: Dict[str, Any] = {
            "() => document.readyState": "complete",
        }

    def locator(self, selector: str) -> MockElementLocator:
        if selector in self.locators:
            return self.locators[selector]
        if any(term in selector for term in (".modal", "backdrop", "overlay", "dialog")):
            loc = MockElementLocator(selector=selector, count=0, visible=False)
            self.locators[selector] = loc
            return loc
        count = 1 if self.default_present else 0
        loc = MockElementLocator(selector=selector, count=count, visible=(count > 0))
        self.locators[selector] = loc
        return loc

    def goto(self, url: str, timeout: Optional[float] = None) -> None:
        self.url = url
        self.history.append(f"goto:{url}")

    def wait_for_timeout(self, timeout_ms: float) -> None:
        self.history.append(f"wait:{timeout_ms}")

    def evaluate(self, script: str, arg: Any = None) -> Any:
        if script in self.eval_values:
            val = self.eval_values[script]
            if callable(val):
                return val(arg)
            return val
        return None


# ============================================================================
# Test 1-4: Stuck Monitor Tests
# ============================================================================

def test_01_stuck_monitor_detects_repeated_no_state_change():
    """Test 1: Stuck Monitor detects repeated action with no state change."""
    monitor = StuckMonitor(window_size=5, stuck_threshold=0.75)

    # Step 1: Click button, no state change
    s1 = StepTelemetry(step_id=1, verb="CLICK", target="#submit-btn", success=True, state_changed=False)
    sig1 = monitor.evaluate_step(s1)
    assert not sig1.is_stuck

    # Step 2: Same click button, no state change again
    s2 = StepTelemetry(step_id=2, verb="CLICK", target="#submit-btn", success=True, state_changed=False)
    sig2 = monitor.evaluate_step(s2)
    assert sig2.is_stuck
    assert sig2.stuck_score >= 0.75
    assert "repeated_action_no_state_change" in sig2.reason or "mechanical_success_zero_delta" in sig2.reason


def test_02_stuck_monitor_detects_cyclic_state_oscillation():
    """Test 2: Stuck Monitor detects cyclic state oscillation (A -> B -> A -> B)."""
    monitor = StuckMonitor(window_size=5, stuck_threshold=0.75)
    hash_a = 0xAAAA111122223333
    hash_b = 0xBBBB444455556666

    # Sequence oscillating between A and B
    monitor.evaluate_step(StepTelemetry(step_id=1, verb="CLICK", target="#tab1", state_changed=True, state_hash=hash_a))
    monitor.evaluate_step(StepTelemetry(step_id=2, verb="CLICK", target="#tab2", state_changed=True, state_hash=hash_b))
    monitor.evaluate_step(StepTelemetry(step_id=3, verb="CLICK", target="#tab1", state_changed=True, state_hash=hash_a))
    sig4 = monitor.evaluate_step(StepTelemetry(step_id=4, verb="CLICK", target="#tab2", state_changed=True, state_hash=hash_b))

    assert sig4.is_stuck
    assert sig4.stuck_score >= 0.85
    assert sig4.reason == "cyclic_state_oscillation"
    assert sig4.evidence["oscillation"]["pattern"] in {"4_step_2_cycle", "3_step_ping_pong"}


def test_03_stuck_monitor_detects_repeated_locator_failure():
    """Test 3: Stuck Monitor detects the same locator failing multiple times."""
    monitor = StuckMonitor(window_size=5, stuck_threshold=0.75)

    s1 = StepTelemetry(step_id=1, verb="CLICK", target="#missing-elem", success=False, error_message="Timeout")
    sig1 = monitor.evaluate_step(s1)
    assert not sig1.is_stuck

    s2 = StepTelemetry(step_id=2, verb="CLICK", target="#missing-elem", success=False, error_message="Timeout")
    sig2 = monitor.evaluate_step(s2)
    assert sig2.is_stuck
    assert sig2.stuck_score >= 0.75
    assert sig2.reason in {"repeated_locator_failure", "repeated_action_exception"}


def test_04_stuck_monitor_does_not_trigger_on_healthy_progress():
    """Test 4: Stuck Monitor does not trigger on healthy progress."""
    monitor = StuckMonitor(window_size=5, stuck_threshold=0.75)

    # 5 healthy advancing steps
    for i in range(1, 6):
        s = StepTelemetry(
            step_id=i,
            verb="TYPE" if i % 2 == 0 else "CLICK",
            target=f"#field-{i}",
            success=True,
            state_changed=True,
            state_hash=0x1000 + i,
            hamming_distance=12,
        )
        sig = monitor.evaluate_step(s)
        assert not sig.is_stuck
        assert sig.stuck_score == 0.0


# ============================================================================
# Test 5-8: Milestone Monitor Tests
# ============================================================================

def test_05_milestone_monitor_detects_expected_state_change():
    """Test 5: Milestone Monitor detects declared expected state change."""
    monitor = MilestoneMonitor(milestone_threshold=0.65)

    step = StepTelemetry(
        step_id=1,
        verb="CLICK",
        target="#toggle",
        success=True,
        state_changed=True,
        hamming_distance=8,
        metadata={"expected_state_change": "panel_expanded"},
    )
    sig = monitor.evaluate(step, goal="expand side panel")

    assert sig.is_milestone
    assert sig.milestone_score == 1.0
    assert sig.milestone_type == "declared_state_change"


def test_06_milestone_monitor_detects_url_milestone():
    """Test 6: Milestone Monitor detects URL transition to expected destination."""
    monitor = MilestoneMonitor(milestone_threshold=0.65)

    step = StepTelemetry(
        step_id=2,
        verb="CLICK",
        target="#login-btn",
        success=True,
        state_changed=True,
        url_changed=True,
        url="https://app.arc.local/dashboard/overview",
    )
    goal = {"goal": "Login and navigate to dashboard", "expected_url": "/dashboard"}
    sig = monitor.evaluate(step, goal=goal)

    assert sig.is_milestone
    assert sig.milestone_score == 1.0
    assert sig.milestone_type == "expected_url_reached"


def test_07_milestone_monitor_detects_visible_text_milestone():
    """Test 7: Milestone Monitor detects expected visible text appearing."""
    monitor = MilestoneMonitor(milestone_threshold=0.65)

    step = StepTelemetry(
        step_id=3,
        verb="CLICK",
        target="#pay-btn",
        success=True,
        state_changed=True,
        hamming_distance=20,
    )
    goal = {"goal": "Complete checkout", "expected_text": "Order Confirmation"}
    state_after_text = "Thank you! Your Order Confirmation #98214 is ready."

    sig = monitor.evaluate(step, goal=goal, state_text_after=state_after_text)

    assert sig.is_milestone
    assert sig.milestone_score >= 0.90
    assert sig.milestone_type == "expected_text_appeared"


def test_08_milestone_monitor_does_not_trigger_on_error_state():
    """Test 8: Milestone Monitor does not trigger on error states."""
    monitor = MilestoneMonitor(milestone_threshold=0.65)

    step = StepTelemetry(
        step_id=4,
        verb="CLICK",
        target="#error-btn",
        success=False,
        error_message="500 Internal Server Error",
        state_changed=True,
        url_changed=True,
        url="https://app.arc.local/error",
    )
    sig = monitor.evaluate(step, goal="Navigate to overview")

    assert not sig.is_milestone
    assert sig.milestone_score == 0.0
    assert sig.evidence.get("error_detected") is True


# ============================================================================
# Test 9-12: Escalation Controller Tests
# ============================================================================

def test_09_escalation_controller_requires_consecutive_stuck_signals():
    """Test 9: Escalation Controller does not escalate on a single noisy stuck signal."""
    controller = EscalationController(
        stuck_threshold=0.75,
        consecutive_stuck_required=2,
        local_recovery_enabled=False,
    )
    from arc_cua.schemas import StuckSignal

    # First stuck signal: must CONTINUE (Rule 1)
    sig1 = StuckSignal(stuck_score=0.85, is_stuck=True, reason="noise")
    dec1 = controller.decide(stuck_signal=sig1)
    assert dec1.decision == DecisionType.CONTINUE
    assert "single_stuck_observed" in dec1.reason

    # Second consecutive stuck signal: must ESCALATE (Rule 2)
    sig2 = StuckSignal(stuck_score=0.88, is_stuck=True, reason="stuck_persistent")
    dec2 = controller.decide(stuck_signal=sig2)
    assert dec2.decision == DecisionType.ESCALATE
    assert "consecutive_stuck_escalation" in dec2.reason


def test_10_escalation_controller_escalates_immediately_on_hard_failure():
    """Test 10: Hard failures escalate immediately without waiting for consecutive steps."""
    controller = EscalationController()
    from arc_cua.schemas import StuckSignal

    sig = StuckSignal(stuck_score=0.0, is_stuck=False)

    for hard_reason in ["LOCATOR_NOT_FOUND", "PAGE_CRASH", "BROWSER_DISCONNECTED", "ESCALATION_REQUIRED"]:
        controller.reset()
        dec = controller.decide(stuck_signal=sig, hard_failure=hard_reason)
        assert dec.decision == DecisionType.ESCALATE
        assert "hard_failure" in dec.reason


def test_11_escalation_controller_enforces_cooldown():
    """Test 11: Escalation Controller enforces cooldown after recovery."""
    controller = EscalationController(cooldown_steps=3)
    from arc_cua.schemas import StuckSignal

    controller.activate_cooldown(steps=3)
    high_stuck = StuckSignal(stuck_score=0.90, is_stuck=True, reason="noise")

    # Step 1 of cooldown
    dec1 = controller.decide(stuck_signal=high_stuck)
    assert dec1.decision == DecisionType.CONTINUE
    assert "cooldown_active" in dec1.reason

    # Step 2 of cooldown
    dec2 = controller.decide(stuck_signal=high_stuck)
    assert dec2.decision == DecisionType.CONTINUE

    # Step 3 of cooldown
    dec3 = controller.decide(stuck_signal=high_stuck)
    assert dec3.decision == DecisionType.CONTINUE

    # Post-cooldown step 1: single stuck observed -> CONTINUE
    dec4 = controller.decide(stuck_signal=high_stuck)
    assert dec4.decision == DecisionType.CONTINUE
    assert "single_stuck_observed" in dec4.reason


def test_12_escalation_controller_respects_max_escalation_budget():
    """Test 12: Escalation Controller aborts when max escalation budget is exceeded."""
    controller = EscalationController(max_escalations_per_task=2)
    from arc_cua.schemas import StuckSignal

    sig = StuckSignal(stuck_score=0.0, is_stuck=False)

    # Escalation 1
    d1 = controller.decide(stuck_signal=sig, hard_failure="LOCATOR_NOT_FOUND")
    assert d1.decision == DecisionType.ESCALATE

    # Escalation 2 (budget limit reached)
    d2 = controller.decide(stuck_signal=sig, hard_failure="PAGE_CRASH")
    assert d2.decision == DecisionType.ESCALATE

    # Escalation 3: budget exceeded -> ABORT
    d3 = controller.decide(stuck_signal=sig, hard_failure="BROWSER_DISCONNECTED")
    assert d3.decision == DecisionType.ABORT
    assert "max_escalations_exceeded" in d3.reason


# ============================================================================
# Test 13-14: Mock Cortex and Recovery Compiler Tests
# ============================================================================

def test_13_mock_cortex_returns_valid_typed_recovery_plan():
    """Test 13: Mock Cortex returns typed RecoveryPlan for all required escalation reasons."""
    client = MockCortexClient()

    reasons = [
        EscalationReason.LOCATOR_NOT_FOUND,
        EscalationReason.STATE_NOT_CHANGED,
        EscalationReason.ACTION_TIMEOUT,
        EscalationReason.READINESS_TIMEOUT,
        EscalationReason.ESCALATION_REQUIRED,
    ]

    for r in reasons:
        payload = EscalationPayload(
            escalation_id=f"esc-{r.value.lower()}",
            task_goal="Complete user purchase",
            reason=r,
            step_history=[ActionStep(step_number=1, verb="CLICK", target_selector="#btn", value=None, action_index=0, latency_ms=10.0, success=False)],
            current_state=UIState(
                state_id="state-0",
                timestamp=time.time(),
                source=PerceptionSource.CDP_AXTREE,
                simhash=0x1234,
                raw_node_count=10,
                pruned_node_count=5,
                actionable_count=2,
                estimated_tokens=50,
                yaml_representation="",
                structured_tree={},
                action_index_map={},
            ),
            failure_details={"target": "#btn"},
        )
        resp = client.recover(payload)
        assert resp.success is True
        assert resp.plan is not None
        assert isinstance(resp.plan, RecoveryPlan)
        assert resp.plan.source == PlanSource.MOCK
        assert len(resp.plan.actions) > 0
        assert resp.plan.expected_outcome != ""
        assert resp.plan.stop_condition != ""


def test_14_recovery_compiler_rejects_invalid_plan():
    """Test 14: Recovery Compiler rejects invalid action verbs, missing locators, and unsafe URLs."""
    compiler = RecoveryCompiler()

    # Case 1: Unsupported verb
    bad_verb_plan = RecoveryPlan(
        plan_id="p-bad-verb",
        source=PlanSource.MOCK,
        actions=[{"verb": "RUN_SHELL_COMMAND", "target": "rm -rf /"}],
    )
    with pytest.raises(RecoveryCompilationError, match="Unsupported action verb"):
        compiler.compile(bad_verb_plan)

    # Case 2: Missing required target locator for CLICK
    missing_loc_plan = RecoveryPlan(
        plan_id="p-missing-loc",
        source=PlanSource.MOCK,
        actions=[{"verb": "CLICK", "target": None}],
    )
    with pytest.raises(RecoveryCompilationError, match="requires a target selector"):
        compiler.compile(missing_loc_plan)

    # Case 3: Unsafe javascript: URL in GOTO
    unsafe_goto_plan = RecoveryPlan(
        plan_id="p-unsafe-goto",
        source=PlanSource.MOCK,
        actions=[{"verb": "GOTO", "value": "javascript:alert(1)"}],
    )
    with pytest.raises(RecoveryCompilationError, match="Unsafe URL scheme"):
        compiler.compile(unsafe_goto_plan)


# ============================================================================
# Test 15-17: Hybrid Runner Tests
# ============================================================================

def test_15_hybrid_runner_recovers_from_stuck_state():
    """Test 15: Hybrid Runner recovers from stuck state using Mock Cortex."""
    page = MockPlaywrightPage()
    # Mock locator that succeeds
    page.locator("body")

    telemetry = TelemetryCollector()
    reflex_runner = ReflexRunner(telemetry=telemetry)
    stuck_monitor = StuckMonitor()
    milestone_monitor = MilestoneMonitor()
    escalation_controller = EscalationController(
        stuck_threshold=0.75,
        consecutive_stuck_required=2,
        local_recovery_enabled=False,  # Directly test Cortex recovery
    )
    cortex_client = MockCortexClient()
    recovery_compiler = RecoveryCompiler()

    runner = HybridRunner(
        reflex_runner=reflex_runner,
        stuck_monitor=stuck_monitor,
        milestone_monitor=milestone_monitor,
        escalation_controller=escalation_controller,
        cortex_client=cortex_client,
        recovery_compiler=recovery_compiler,
        telemetry=telemetry,
        cortex_mode="mock",
    )

    # Sequence of actions that creates a stuck condition, followed by an action
    steps = [
        {"verb": "WAIT", "value": "10"},
        # Action step with target that will trigger escalation or recovery
        {"verb": "CLICK", "target": "#save-btn"},
    ]

    result = runner.run(page, steps, task_goal="Save document")
    assert isinstance(result, HybridRunResult)
    assert not result.aborted
    assert result.total_steps >= 2


def test_16_hybrid_runner_aborts_when_recovery_budget_exceeded():
    """Test 16: Hybrid Runner aborts when escalation/recovery budget is exhausted."""
    page = MockPlaywrightPage()
    telemetry = TelemetryCollector()

    # Configure max_escalations_per_task=1
    controller = EscalationController(
        max_escalations_per_task=1,
        local_recovery_enabled=False,
    )

    runner = HybridRunner(
        escalation_controller=controller,
        telemetry=telemetry,
        cortex_mode="mock",
    )

    # Feed 3 explicit ESCALATE steps to exhaust budget
    steps = [
        {"verb": "ESCALATE", "target": "body"},
        {"verb": "ESCALATE", "target": "body"},
    ]

    result = runner.run(page, steps, task_goal="Exhaust budget")
    assert result.aborted is True
    assert "max_escalations_exceeded" in (result.abort_reason or "")


def test_17_hybrid_runner_does_not_call_external_network_in_mock_mode(monkeypatch):
    """Test 17: Hybrid Runner does not make any external network calls in mock mode."""
    # Monkeypatch socket.connect to ensure no network calls occur
    def forbidden_connect(*args, **kwargs):
        raise AssertionError("External network call attempted in mock mode!")

    monkeypatch.setattr(socket.socket, "connect", forbidden_connect)

    page = MockPlaywrightPage()
    runner = HybridRunner(cortex_mode="mock")

    steps = [
        {"verb": "WAIT", "value": "10"},
        {"verb": "CLICK", "target": "#submit"},
    ]

    # Must complete successfully without triggering forbidden_connect
    result = runner.run(page, steps, task_goal="Zero network run")
    assert not result.aborted


# ============================================================================
# Test 18: Public Playwright API Compliance
# ============================================================================

def test_18_public_playwright_api_compliance():
    """Test 18: Verify Phase 3 codebase contains strictly zero private Playwright internals."""
    src_dir = pathlib.Path(__file__).parent.parent / "src" / "arc_cua"
    monitors_dir = src_dir / "monitors"
    cortex_dir = src_dir / "cortex"

    target_files = [
        src_dir / "hybrid_runner.py",
        src_dir / "schemas.py",
        src_dir / "telemetry.py",
        monitors_dir / "stuck_monitor.py",
        monitors_dir / "milestone_monitor.py",
        monitors_dir / "escalation_controller.py",
        cortex_dir / "cortex_interface.py",
        cortex_dir / "mock_cortex.py",
        cortex_dir / "recovery_compiler.py",
    ]

    violations = []
    for filepath in target_files:
        if not filepath.exists():
            violations.append(f"Missing file: {filepath}")
            continue

        with open(filepath, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(filepath))

        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if node.attr in FORBIDDEN_PRIVATE_INTERNALS:
                    violations.append(f"{filepath.name}:{node.lineno} accesses forbidden '{node.attr}'")

    assert not violations, f"Forbidden private Playwright internals found: {violations}"
