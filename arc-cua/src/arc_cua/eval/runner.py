"""Evaluation Runner for ARC (Phase 4A).

Implements Task 4A.5:
- Coordinates execution of EvalTask objects in either Reflex-only or Hybrid mode.
- Supports headless Chromium via public Playwright APIs and fallback MockEvalPage.
- Evaluates assertions using Success Assertion Engine (assertions.py).
- Integrates CostLedger (cost.py) and TrajectoryCollector.
- Captures duration, steps, escalations, recoveries, milestones, and telemetry.
- Strictly offline/mock: zero real Cortex or external LLM calls.
"""

from __future__ import annotations

import logging
import os
import pathlib
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from ..cdp_extractor import CDP_AXTree_Extractor, SanitizedAXTree
from ..cortex.mock_cortex import MockCortexClient
from ..datasets.trajectory_collector import TrajectoryCollector
from ..hybrid_runner import HybridRunner
from ..monitors.escalation_controller import EscalationController
from ..monitors.milestone_monitor import MilestoneMonitor
from ..monitors.stuck_monitor import StuckMonitor
from ..reflex_runner import ReflexExecutionResult, ReflexRunner, ReflexStatus
from ..schemas import (
    ActionStep,
    CortexResponse,
    DecisionType,
    EscalationPayload,
    EscalationReason,
    HybridRunResult,
    PlanSource,
    RecoveryPlan,
)
from ..telemetry import TelemetryCollector, compute_simhash64
from .assertions import evaluate_assertion
from .cost import CostLedger, CostModelConfig
from .schemas import (
    AssertionType,
    ElementState,
    EvalAssertion,
    EvalAssertionResult,
    EvalResult,
    EvalTask,
)

logger = logging.getLogger("arc_cua.eval.runner")


class EvalCortexClient(MockCortexClient):
    """Evaluation-specific Mock Cortex that recognizes task recovery actions."""

    def __init__(self, model_name: str = "eval-mock-cortex-v1"):
        super().__init__(model_name=model_name)
        self.active_task: Optional[EvalTask] = None

    def set_active_task(self, task: Optional[EvalTask]) -> None:
        self.active_task = task

    def recover(self, payload: EscalationPayload) -> CortexResponse:
        """Produce a targeted recovery plan if task metadata provides one, else default."""
        if self.active_task and self.active_task.metadata:
            custom_rec = self.active_task.metadata.get("recovery_action")
            if custom_rec and isinstance(custom_rec, dict):
                plan_id = f"eval-rec-{payload.reason.value.lower()}-{payload.escalation_id[:6]}"
                actions = [
                    custom_rec,
                    {"verb": "WAIT", "target": None, "value": "150"},
                ]
                return CortexResponse(
                    plan=RecoveryPlan(
                        plan_id=plan_id,
                        source=PlanSource.MOCK,
                        actions=actions,
                        expected_outcome="Execute task recovery action and stabilize",
                        stop_condition="recovery_action_executed",
                        confidence=0.98,
                    ),
                    model=self.model_name,
                    tokens_used=42,
                    latency_ms=25.0,
                )
        resp = super().recover(payload)
        if resp.plan and resp.plan.actions:
            concrete_target = None
            if self.active_task:
                for step in self.active_task.action_steps:
                    tgt = step.target_selector if hasattr(step, "target_selector") else (step.get("target_selector") if isinstance(step, dict) else None)
                    if tgt and tgt != "window":
                        concrete_target = tgt
                        break
            if not concrete_target:
                concrete_target = (
                    (payload.step_history[-1].target_selector if payload.step_history else None)
                    or (payload.failure_details or {}).get("target")
                )
            if concrete_target:
                for a in resp.plan.actions:
                    if a.get("target") in ("button", None):
                        a["target"] = concrete_target
        return resp


class MockKeyboard:
    def __init__(self):
        self.presses: List[str] = []

    def press(self, key: str) -> None:
        self.presses.append(key)


class MockMouse:
    def __init__(self):
        self.clicks: List[Tuple[float, float]] = []
        self.wheels: List[Tuple[int, int]] = []

    def click(self, x: float, y: float) -> None:
        self.clicks.append((x, y))

    def wheel(self, delta_x: int, delta_y: int) -> None:
        self.wheels.append((delta_x, delta_y))


class MockEvalLocator:
    """Mock Locator for deterministic evaluation without a real browser."""

    def __init__(self, selector: str, page: MockEvalPage):
        self.selector = selector
        self.page = page

    @property
    def first(self) -> MockEvalLocator:
        return self

    def nth(self, index: int) -> MockEvalLocator:
        return self

    def count(self) -> int:
        if any(term in self.selector for term in (".modal", "backdrop", "overlay", "dialog")):
            return 0
        if any(h in self.selector for h in ("non-existent", "missing")):
            return 0
        return 1

    def is_visible(self) -> bool:
        if any(term in self.selector for term in (".modal", "backdrop", "overlay", "dialog")):
            return False
        if any(h in self.selector for h in ("hidden", "invisible", "zero-pixel", "non-existent", "missing")):
            return False
        return True

    def is_hidden(self) -> bool:
        return not self.is_visible()

    def is_enabled(self) -> bool:
        if "disabled" in self.selector:
            return False
        return True

    def is_disabled(self) -> bool:
        return not self.is_enabled()

    def is_checked(self) -> bool:
        return False

    def bounding_box(self) -> Dict[str, float]:
        if "zero-pixel" in self.selector:
            return {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0}
        if not self.is_visible():
            return {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0}
        return {"x": 100.0, "y": 200.0, "width": 120.0, "height": 36.0}

    def inner_text(self) -> str:
        return self.page.get_element_text(self.selector)

    def text_content(self) -> str:
        return self.inner_text()

    def input_value(self, timeout: Optional[float] = None) -> str:
        return self.page.get_input_value(self.selector)

    def click(self, timeout: Optional[float] = None) -> None:
        self.page.handle_click(self.selector)

    def fill(self, value: str, timeout: Optional[float] = None) -> None:
        self.page.handle_fill(self.selector, value)

    def select_option(self, value: Any, timeout: Optional[float] = None) -> List[str]:
        self.page.handle_select(self.selector, value)
        return [str(value)]

    def scroll_into_view_if_needed(self, timeout: Optional[float] = None) -> None:
        pass

    def wait_for(self, state: str = "visible", timeout: Optional[float] = None) -> None:
        pass

    def evaluate(self, script: str, arg: Any = None) -> Any:
        if "getComputedStyle" in script:
            if not self.is_visible():
                return {"display": "none", "visibility": "hidden", "opacity": "0"}
            return {"display": "block", "visibility": "visible", "opacity": "1"}
        if "value" in script:
            return self.input_value()
        return None


class MockTreeExtractor:
    """Mock extractor generating a real SanitizedAXTree reflecting MockEvalPage state."""

    def __init__(self, mock_page: MockEvalPage):
        self.mock_page = mock_page

    def extract(self) -> SanitizedAXTree:
        yaml_lines = [f"- page url='{self.mock_page.url}'"]
        for k, v in sorted(self.mock_page._texts.items()):
            yaml_lines.append(f"  - {k}: '{v}'")
        for k, v in sorted(self.mock_page._inputs.items()):
            yaml_lines.append(f"  - {k}: '{v}'")
        yaml_str = "\n".join(yaml_lines)
        return SanitizedAXTree(
            raw_node_count=len(self.mock_page._texts),
            pruned_node_count=0,
            actionable_count=len(self.mock_page._texts),
            sanitization_latency_ms=0.5,
            estimated_tokens=len(yaml_str) // 4,
            yaml_linearized=yaml_str,
            json_structured=[],
            action_index_map={},
            truncated=False,
        )

class MockEvalPage:
    """Deterministic in-memory mock page simulating eval_site.html interactions."""

    def __init__(self, initial_url: str = "file:///eval_site.html"):
        self.url = initial_url
        self._title = "ARC Evaluation Suite"
        self.keyboard = MockKeyboard()
        self.mouse = MockMouse()
        self._inputs: Dict[str, str] = {
            "input#user-name": "",
            "input#user-email": "",
            "input#validated-input": "",
        }
        self._texts: Dict[str, str] = {
            "#suite-title": "ARC Evaluation Suite",
            "#suite-description": "Deterministic local test bench for Phase 4A evaluation harness.",
            "div#form-result": "Form ready",
            "div#current-view-title": "View: Overview",
            "div#view-content": "Active section content for Overview",
            "div#dropdown-selected-value": "Selected: none",
            "div#priority-status": "Status: Pending",
            "div#scroll-status": "Scroll status: Unclicked",
            "div#validation-result": "Awaiting validation",
            "div#noop-status": "No-op State Unchanged",
            "div#recovery-status": "Recovery Status: Idle",
            "div#milestone-indicator": "Milestone Progress: Step 0",
            "div#readiness-log": "Guards active",
        }
        self._selected_priority = "none"

    def goto(self, url: str, timeout: Optional[float] = None) -> None:
        self.url = url

    def title(self) -> str:
        return self._title

    def locator(self, selector: str) -> MockEvalLocator:
        return MockEvalLocator(selector, self)

    def get_element_text(self, selector: str) -> str:
        # Match normalized key
        for k, v in self._texts.items():
            if k in selector or selector in k:
                return v
        return "mock_content"

    def get_input_value(self, selector: str) -> str:
        for k, v in self._inputs.items():
            if k in selector or selector in k:
                return v
        return ""

    def handle_fill(self, selector: str, value: str) -> None:
        for k in self._inputs:
            if k in selector or selector in k:
                self._inputs[k] = value
                return
        self._inputs[selector] = value

    def handle_select(self, selector: str, value: Any) -> None:
        self._selected_priority = str(value)
        self._texts["div#dropdown-selected-value"] = f"Selected: {value}"

    def handle_click(self, selector: str) -> None:
        sel = selector.lower()
        if "submit-form-btn" in sel:
            u = self._inputs.get("input#user-name", "")
            e = self._inputs.get("input#user-email", "")
            self._texts["div#form-result"] = f"Form submitted: {u} ({e})"
        elif "nav-to-settings" in sel:
            self.url = f"{self.url.split('#')[0]}#settings"
            self._texts["div#current-view-title"] = "View: Settings"
            self._texts["div#view-content"] = "Active section content for Settings"
        elif "nav-to-overview" in sel:
            self.url = f"{self.url.split('#')[0]}#overview"
            self._texts["div#current-view-title"] = "View: Overview"
        elif "apply-priority-btn" in sel:
            self._texts["div#priority-status"] = f"Priority set to {self._selected_priority}"
        elif "revealed-target-btn" in sel:
            self._texts["div#scroll-status"] = "Revealed button clicked successfully"
        elif "validate-btn" in sel:
            val = self._inputs.get("input#validated-input", "")
            if len(val) >= 6:
                self._texts["div#validation-result"] = f"Validation Passed: {val}"
            else:
                self._texts["div#validation-result"] = "Validation Failed: Input must be at least 6 characters"
        elif "noop-action-btn" in sel:
            pass  # State remains intentionally unchanged
        elif "stuck-trigger-btn" in sel:
            pass  # State remains unchanged
        elif "recovery-action-btn" in sel:
            self._texts["div#recovery-status"] = "Recovery Succeeded: State Resumed"
        elif "milestone-step-1" in sel:
            self._texts["div#milestone-indicator"] = "Milestone 1 Completed"
        elif "milestone-step-2" in sel:
            self._texts["div#milestone-indicator"] = "Milestone 2 Completed"
        elif "milestone-step-3" in sel:
            self._texts["div#milestone-indicator"] = "Milestone 3 Completed - Workflow Done"

    def evaluate(self, script: str, arg: Any = None) -> Any:
        if "readyState" in script:
            return "complete"
        if "modal" in script:
            return False
        return None

    def wait_for_timeout(self, timeout_ms: float) -> None:
        pass


class EvalRunner:
    """Execution engine for evaluation tasks across Reflex-only and Hybrid modes."""

    def __init__(
        self,
        mode: str = "hybrid",
        headless: bool = True,
        mock_mode: bool = False,
        cost_ledger: Optional[CostLedger] = None,
        trajectory_collector: Optional[TrajectoryCollector] = None,
        cortex_client: Optional[EvalCortexClient] = None,
    ):
        self.mode = mode.lower()
        self.headless = headless
        self.mock_mode = mock_mode
        self.cost_ledger = cost_ledger or CostLedger()
        self.trajectory_collector = trajectory_collector
        self.cortex_client = cortex_client or EvalCortexClient()

    def _acquire_page(self, start_url: str, provided_page: Optional[Any] = None) -> Tuple[Any, Optional[Any], Optional[Any]]:
        """Resolve or launch an appropriate page object (live Playwright Page or MockEvalPage)."""
        if provided_page is not None:
            if hasattr(provided_page, "goto"):
                try:
                    provided_page.goto(start_url)
                except Exception as e:
                    logger.debug(f"provided_page goto exception: {e}")
            return provided_page, None, None

        if not self.mock_mode:
            try:
                from playwright.sync_api import sync_playwright
                pw = sync_playwright().start()
                browser = pw.chromium.launch(headless=self.headless)
                page = browser.new_page(viewport={"width": 1400, "height": 3000})
                page.goto(start_url)
                return page, browser, pw
            except Exception as e:
                logger.warning(f"Could not launch Playwright Chromium ({e}); falling back to MockEvalPage")

        mock_page = MockEvalPage(initial_url=start_url)
        return mock_page, None, None

    def _release_page(self, page: Any, browser: Optional[Any], pw: Optional[Any]) -> None:
        """Safely close page and browser if launched dynamically."""
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if pw is not None:
            try:
                pw.stop()
            except Exception:
                pass
            import asyncio
            try:
                asyncio.set_event_loop(None)
            except Exception:
                pass

    def run_task(self, task: EvalTask, page: Optional[Any] = None) -> EvalResult:
        """Run an individual EvalTask and produce an EvalResult."""
        t0 = time.perf_counter()
        active_page, browser, pw = self._acquire_page(task.start_url, page)

        # Notify eval cortex of active task for targeted recovery
        self.cortex_client.set_active_task(task)

        # Initialize telemetry and monitors
        telemetry = TelemetryCollector(session_id=f"eval-{task.task_id}")
        reflex_runner = ReflexRunner(telemetry=telemetry, session_id=f"eval-{task.task_id}")

        stuck_monitor = StuckMonitor(window_size=4, stuck_threshold=0.70)
        milestone_monitor = MilestoneMonitor()
        escalation_controller = EscalationController(
            max_escalations_per_task=3,
            max_recovery_attempts=2,
            cooldown_steps=1,
            local_recovery_enabled=False,
        )

        mock_extractor = MockTreeExtractor(active_page) if isinstance(active_page, MockEvalPage) else None
        initial_tree = mock_extractor.extract() if mock_extractor else None
        initial_state_hash = compute_simhash64(initial_tree.yaml_linearized) if initial_tree else 1000
        final_state_hash = initial_state_hash

        total_steps = 0
        reflex_steps = 0
        escalations = 0
        recoveries_attempted = 0
        recoveries_succeeded = 0
        milestones_detected = 0
        aborted = False
        abort_reason: Optional[str] = None
        completed_steps: List[ActionStep] = []

        try:
            if self.mode == "hybrid":
                hybrid_runner = HybridRunner(
                    reflex_runner=reflex_runner,
                    stuck_monitor=stuck_monitor,
                    milestone_monitor=milestone_monitor,
                    escalation_controller=escalation_controller,
                    cortex_client=self.cortex_client,
                    telemetry=telemetry,
                    cortex_mode="mock",
                    session_id=f"eval-hybrid-{task.task_id}",
                )
                h_res: HybridRunResult = hybrid_runner.run(
                    page=active_page,
                    steps=task.action_steps,
                    task_goal=task.description,
                    initial_tree=initial_tree,
                    extractor=mock_extractor,
                )
                total_steps = h_res.total_steps
                reflex_steps = h_res.reflex_steps
                escalations = h_res.escalations
                recoveries_attempted = h_res.recoveries_attempted
                recoveries_succeeded = h_res.recoveries_succeeded
                milestones_detected = h_res.milestones_detected
                aborted = h_res.aborted
                abort_reason = h_res.abort_reason
                completed_steps = h_res.completed_steps
                final_state_hash = compute_simhash64(mock_extractor.extract().yaml_linearized) if mock_extractor else (h_res.final_state_hash or (initial_state_hash + total_steps * 10))
            else:
                # Reflex-only execution
                r_res: ReflexExecutionResult = reflex_runner.run_steps(
                    page=active_page,
                    steps=task.action_steps,
                    task_goal=task.description,
                    initial_tree=initial_tree,
                    extractor=mock_extractor,
                )
                completed_steps = r_res.completed_steps
                total_steps = len(completed_steps)
                reflex_steps = total_steps
                if r_res.status == ReflexStatus.ESCALATE:
                    escalations = 1
                    aborted = True
                    abort_reason = r_res.escalation_payload.reason.value if r_res.escalation_payload else "REFLEX_ESCALATION"
                final_state_hash = compute_simhash64(mock_extractor.extract().yaml_linearized) if mock_extractor else (initial_state_hash + total_steps * 10)

        except Exception as e:
            logger.error(f"Task {task.task_id} execution error: {e}", exc_info=True)
            aborted = True
            abort_reason = str(e)

        # 2. Evaluate Assertions
        assertion_results: List[EvalAssertionResult] = []
        for assertion in task.expected_assertions:
            res = evaluate_assertion(
                page=active_page,
                assertion=assertion,
                initial_state_hash=initial_state_hash,
                current_state_hash=final_state_hash,
            )
            assertion_results.append(res)

        # Determine task success: all assertions passed AND not aborted
        all_assertions_passed = all(a.passed for a in assertion_results) if assertion_results else True
        task_success = all_assertions_passed and not aborted

        duration_ms = (time.perf_counter() - t0) * 1000.0

        # Calculate costs
        cost_record = self.cost_ledger.calculate_task_cost(
            task_id=task.task_id,
            reflex_steps=reflex_steps,
            cortex_calls=escalations,
            browser_runtime_ms=duration_ms,
            is_mock_cortex=True,
        )

        telemetry_summary = telemetry.get_summary()

        # If trajectory collector is available, record task telemetry
        if self.trajectory_collector:
            try:
                for step in completed_steps:
                    self.trajectory_collector.record_step(
                        run_id=f"eval-{self.mode}",
                        task_id=task.task_id,
                        step_id=step.step_number,
                        action_type=step.verb,
                        target_locator=step.target_selector,
                        execution_success=step.success,
                        state_hash_before=initial_state_hash,
                        state_hash_after=final_state_hash,
                    )
            except Exception as e:
                logger.debug(f"Trajectory collection note: {e}")

        # Clean up page if dynamically launched
        if page is None:
            self._release_page(active_page, browser, pw)

        return EvalResult(
            task_id=task.task_id,
            success=task_success,
            total_steps=total_steps,
            reflex_steps=reflex_steps,
            escalations=escalations,
            recoveries_attempted=recoveries_attempted,
            recoveries_succeeded=recoveries_succeeded,
            milestones_detected=milestones_detected,
            aborted=aborted,
            abort_reason=abort_reason,
            duration_ms=duration_ms,
            cost_usd=cost_record.total_cost_usd,
            telemetry_summary=telemetry_summary,
            assertion_results=assertion_results,
            mode=self.mode,
            completed_steps=completed_steps,
            final_state_hash=final_state_hash,
            metadata={
                "category": task.category,
                "cost_record": cost_record.to_dict(),
                "all_assertions_passed": all_assertions_passed,
            },
        )

    def run_suite(self, tasks: List[EvalTask], page: Optional[Any] = None) -> List[EvalResult]:
        """Run all tasks in a suite sequentially."""
        results: List[EvalResult] = []
        for task in tasks:
            logger.info(f"Running Eval Task: {task.task_id} [{self.mode}]")
            res = self.run_task(task, page=page)
            results.append(res)
        return results
