"""Live Browser Hybrid Smoke Test for ARC (Phase 3B Task 8).

Validates HybridRunner end-to-end against a real headless Chromium browser:
1. Open a local test page in Chromium.
2. Extract state.
3. Execute one healthy typed action (e.g. TYPE into an input).
4. Force a stuck condition using repeated no-op actions that do not change state.
5. Verify Stuck Monitor detects the stuck state.
6. Verify Escalation Controller triggers escalation/recovery.
7. Use Mock Cortex to generate recovery plan.
8. Verify recovery action executes successfully.
9. Log and export telemetry and trajectory data.
"""

from __future__ import annotations

import pathlib
import sys
import pytest

# Ensure src is on sys.path
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

from arc_cua.cdp_extractor import CDP_AXTree_Extractor
from arc_cua.cortex.mock_cortex import MockCortexClient
from arc_cua.hybrid_runner import HybridRunner
from arc_cua.monitors.escalation_controller import EscalationController
from arc_cua.monitors.milestone_monitor import MilestoneMonitor
from arc_cua.monitors.stuck_monitor import StuckMonitor
from arc_cua.schemas import ActionStep, DecisionType, EscalationReason, PlanSource, RecoveryPlan
from arc_cua.telemetry import TelemetryCollector

LIVE_BROWSER_SMOKE_SKIPPED = "LIVE_BROWSER_SMOKE_SKIPPED"


class SmokeRecoveryCortexClient(MockCortexClient):
    """Custom mock cortex specifically tuned to recover our live smoke test."""

    def recover(self, payload):
        resp = super().recover(payload)
        # Supply action targeting button#recover-btn to confirm recovery execution in DOM
        resp.plan = RecoveryPlan(
            plan_id=f"smoke-rec-{payload.escalation_id[:6]}",
            source=PlanSource.MOCK,
            actions=[
                {"verb": "CLICK", "target": "button#recover-btn", "value": None},
                {"verb": "WAIT", "target": None, "value": "200"},
            ],
            expected_outcome="Click recover button and stabilize",
            stop_condition="button_clicked",
            confidence=0.95,
        )
        return resp


def run_live_hybrid_smoke(headless: bool = True) -> dict:
    """Execute complete live browser hybrid smoke test.

    Returns:
        Dictionary summarizing the execution and telemetry.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip(f"{LIVE_BROWSER_SMOKE_SKIPPED}: Playwright not installed")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            page = browser.new_page()

            # 1. Open test page
            page.set_content("""
                <!DOCTYPE html>
                <html>
                <head><title>Hybrid Live Smoke Page</title></head>
                <body>
                    <h1 id="title">Live Smoke Test</h1>
                    <div id="status">initial</div>
                    <input id="test-input" type="text" placeholder="Type here..." />
                    <button id="update-btn" onclick="document.getElementById('status').innerText='updated'">Update Status</button>
                    <button id="noop-btn" onclick="/* no state change */">No-Op Button</button>
                    <button id="recover-btn" onclick="document.getElementById('status').innerText='recovered'">Recovery Target</button>
                </body>
                </html>
            """)

            telemetry = TelemetryCollector(session_id="smoke-live-p3b")
            milestone_monitor = MilestoneMonitor()
            # Setup HybridRunner with deterministic monitors & custom mock cortex
            stuck_monitor = StuckMonitor(window_size=5, stuck_threshold=0.75)
            escalation_controller = EscalationController(
                max_escalations_per_task=3,
                max_recovery_attempts=2,
                cooldown_steps=1,
                local_recovery_enabled=False,  # Direct Cortex escalation for smoke test
            )

            mock_cortex = SmokeRecoveryCortexClient(model_name="live-smoke-cortex")

            runner = HybridRunner(
                telemetry=telemetry,
                stuck_monitor=stuck_monitor,
                milestone_monitor=milestone_monitor,
                escalation_controller=escalation_controller,
                cortex_client=mock_cortex,
                cortex_mode="mock",
                session_id="smoke-live-p3b",
            )

            # 3. Healthy action + 4. Repeated no-op actions to trigger stuck condition
            steps = [
                # Step 1: Healthy action (changes state by typing)
                ActionStep(
                    step_number=1,
                    verb="TYPE",
                    target_selector="input#test-input",
                    value="Hello Arc",
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
                # Steps 2 & 3: Repeated no-op clicks (do not change state)
                ActionStep(
                    step_number=2,
                    verb="CLICK",
                    target_selector="button#noop-btn",
                    value=None,
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
                ActionStep(
                    step_number=3,
                    verb="CLICK",
                    target_selector="button#noop-btn",
                    value=None,
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
                # Step 4: Normal action to finish after recovery
                ActionStep(
                    step_number=4,
                    verb="CLICK",
                    target_selector="button#update-btn",
                    value=None,
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
            ]

            # Execute Hybrid Runner
            result = runner.run(
                page=page,
                steps=steps,
                task_goal="Smoke test typing and button clicks with recovery",
            )

            # Read final page DOM
            final_status = page.locator("#status").inner_text()
            input_val = page.locator("#test-input").input_value()

            # 9. Verify telemetry and trajectory logs
            summary = telemetry.get_summary()
            traj_windows = telemetry.trajectory_collector.get_windows()

            browser.close()

            return {
                "success": result.success,
                "total_steps": result.total_steps,
                "reflex_steps": result.reflex_steps,
                "escalations": result.escalations,
                "recoveries_attempted": result.recoveries_attempted,
                "recoveries_succeeded": result.recoveries_succeeded,
                "input_value": input_val,
                "final_status": final_status,
                "trajectory_windows_count": len(traj_windows),
                "summary": summary,
            }

    except Exception as e:
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e).lower():
            pytest.skip(f"{LIVE_BROWSER_SMOKE_SKIPPED}: Chromium browser binary missing ({e})")
        raise


class TestLiveBrowserHybrid:
    """Integration test suite executing HybridRunner against live Chromium."""

    def test_live_browser_hybrid_execution(self):
        """Verify full hybrid loop: healthy step, stuck detection, escalation recovery, execution."""
        smoke_result = run_live_hybrid_smoke(headless=True)

        assert smoke_result["success"] is True
        assert smoke_result["total_steps"] >= 4
        assert smoke_result["input_value"] == "Hello Arc"
        assert smoke_result["final_status"] in {"recovered", "updated"}
        assert smoke_result["recoveries_attempted"] >= 1
        assert smoke_result["trajectory_windows_count"] >= 1
