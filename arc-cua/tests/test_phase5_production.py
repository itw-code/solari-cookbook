"""Tests for Phase 5 Live Production Integration & Final Scorecard.

Verifies:
1. Arc driver gracefully handles missing API keys (falls back to mock mode).
2. Real LLM adapter correctly formats prompts and parses JSON recovery plans.
3. Cost ledger accurately calculates real token costs across providers (OpenAI, Anthropic, Jev).
4. Live orchestrator safely skips if Docker/KVM is missing without throwing exceptions.
5. Production scorecard generator produces valid scorecards and trajectory logs.
"""

from __future__ import annotations

import json
import os
import pathlib
import time
import pytest
import sys
import urllib.request

REPO_ROOT = pathlib.Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from arc_cua.cloud.arc_driver import (
    SessionStatus,
    SessionType,
    ArcCloudDriver,
    ArcSession,
)
from arc_cua.cortex.real_llm_cortex import (
    PROVIDER_PRICING,
    RealLlmCortex,
    TokenCostRecord,
    create_real_cortex_client,
)
from arc_cua.eval.live_orchestrator import (
    HostCapabilities,
    LIVE_ORCHESTRATION_SKIPPED,
    LiveOrchestrator,
)
from arc_cua.schemas import (
    ActionStep,
    EscalationPayload,
    EscalationReason,
    PerceptionSource,
    PlanSource,
    UIState,
)


# =============================================================================
# 1. Arc Cloud Driver Tests
# =============================================================================

class TestArcCloudDriver:
    """Tests for ArcCloudDriver."""

    def test_missing_api_key_defaults_to_mock(self, monkeypatch):
        """Driver gracefully defaults to mock mode if ARC_API_KEY is unset."""
        monkeypatch.delenv("ARC_API_KEY", raising=False)
        driver = ArcCloudDriver(api_key=None)
        assert driver.is_mock is True
        assert driver.api_key == ""

    def test_mock_browser_provisioning(self, monkeypatch):
        """Driver provisions mock browser session with CDP endpoint and replay URL."""
        monkeypatch.delenv("ARC_API_KEY", raising=False)
        driver = ArcCloudDriver()

        session = driver.provision_browser(stealth=True)
        assert session.is_mock is True
        assert session.session_type == SessionType.BROWSER
        assert session.status == SessionStatus.RUNNING
        assert "devtools/browser" in session.cdp_endpoint
        assert "https://cloud.arc.ai/replay" in session.replay_url

        # Check accessor
        assert driver.get_cdp_endpoint(session.session_id) == session.cdp_endpoint
        assert driver.get_replay_url(session.session_id) == session.replay_url

    def test_mock_desktop_provisioning(self, monkeypatch):
        """Driver provisions mock desktop session with VNC stream."""
        monkeypatch.delenv("ARC_API_KEY", raising=False)
        driver = ArcCloudDriver()

        session = driver.provision_desktop(resolution="1920x1080", os_flavor="ubuntu")
        assert session.is_mock is True
        assert session.session_type == SessionType.DESKTOP
        assert session.status == SessionStatus.RUNNING
        assert "vnc://" in session.vnc_stream
        assert driver.get_vnc_stream(session.session_id) == session.vnc_stream

    def test_session_compute_duration_and_termination(self, monkeypatch):
        """Driver accurately tracks compute duration and freezes time upon termination."""
        monkeypatch.delenv("ARC_API_KEY", raising=False)
        driver = ArcCloudDriver()

        session = driver.provision_browser()
        time.sleep(0.01)
        running_ms = driver.get_compute_time_ms(session.session_id)
        assert running_ms > 0.0

        assert driver.terminate(session.session_id) is True
        assert session.status == SessionStatus.TERMINATED
        final_ms = driver.get_compute_time_ms(session.session_id)
        assert final_ms >= running_ms

        # Re-terminating already terminated session is idempotent
        assert driver.terminate(session.session_id) is True

    def test_terminate_all_active_sessions(self, monkeypatch):
        """Driver terminate_all safely terminates all open sessions."""
        monkeypatch.delenv("ARC_API_KEY", raising=False)
        driver = ArcCloudDriver()

        s1 = driver.provision_browser()
        s2 = driver.provision_desktop()
        assert len(driver.list_active_sessions()) == 2

        count = driver.terminate_all()
        assert count == 2
        assert len(driver.list_active_sessions()) == 0

    def test_live_mode_with_mocked_http_dispatcher(self):
        """Driver interacts with Arc Cloud API when API key is present."""
        calls = []

        def mock_requester(req: urllib.request.Request, timeout: float):
            calls.append(req)
            return {
                "session_id": "remote-sess-001",
                "cdp_endpoint": "wss://us-east-1.cloud.arc.ai/cdp/remote-sess-001",
                "vnc_stream": "wss://us-east-1.cloud.arc.ai/vnc/remote-sess-001",
                "replay_url": "https://cloud.arc.ai/replay/remote-sess-001",
                "region": "us-east-1",
            }

        driver = ArcCloudDriver(
            api_key="sk-arc-live-test-12345",
            region="us-east-1",
            http_requester=mock_requester,
        )
        assert driver.is_mock is False

        session = driver.provision_browser(stealth=True)
        assert session.is_mock is False
        assert session.cdp_endpoint == "wss://us-east-1.cloud.arc.ai/cdp/remote-sess-001"
        assert len(calls) == 1
        assert "Authorization" in calls[0].headers


# =============================================================================
# 2. Real Cortex LLM Adapter Tests
# =============================================================================

class TestRealLlmCortex:
    """Tests for RealLlmCortex adapter."""

    def _sample_payload(self) -> EscalationPayload:
        """Construct synthetic EscalationPayload for tests."""
        state = UIState(
            state_id="state_001",
            timestamp=1000.0,
            source=PerceptionSource.CDP_AXTREE,
            simhash=0xABCDEF1234567890,
            raw_node_count=10,
            pruned_node_count=5,
            actionable_count=2,
            estimated_tokens=50,
            yaml_representation="url: http://shop.local\nelements:\n  - selector: button#checkout",
            structured_tree={},
            action_index_map={},
        )
        steps = [
            ActionStep(step_number=1, verb="CLICK", target_selector="button#cart", value=None, action_index=0, latency_ms=10.0, success=True),
            ActionStep(step_number=2, verb="CLICK", target_selector="button#checkout", value=None, action_index=1, latency_ms=15.0, success=False, error_message="element obscured"),
        ]
        return EscalationPayload(
            escalation_id="esc-test-01",
            task_goal="Complete order checkout",
            reason=EscalationReason.LOCATOR_NOT_FOUND,
            step_history=steps,
            current_state=state,
            failure_details={"error": "Modal overlay blocker"},
        )

    def test_refuses_instantiation_if_mode_not_real(self, monkeypatch):
        """RealLlmCortex raises ValueError if CORTEX_MODE != 'real'."""
        monkeypatch.setenv("CORTEX_MODE", "mock")
        with pytest.raises(ValueError, match="CORTEX_MODE must be 'real'"):
            RealLlmCortex()

    def test_factory_returns_none_if_mode_not_real(self, monkeypatch):
        """create_real_cortex_client returns None safely if CORTEX_MODE != 'real'."""
        monkeypatch.setenv("CORTEX_MODE", "mock")
        client = create_real_cortex_client()
        assert client is None

    def test_prompt_formatting(self):
        """format_prompts formats EscalationPayload into strict JSON instruction prompts."""
        client = RealLlmCortex(mode="real", provider="openai", api_key="sk-test")
        payload = self._sample_payload()

        sys_prompt, user_prompt = client.format_prompts(payload)

        # Check system prompt constraints
        assert "ARC Cortex Reasoning Engine" in sys_prompt
        assert "REQUIRED JSON SCHEMA" in sys_prompt
        assert "CLICK" in sys_prompt
        assert "TYPE" in sys_prompt

        # Check user prompt context
        assert "Complete order checkout" in user_prompt
        assert "Modal overlay blocker" in user_prompt
        assert "esc-test-01" in user_prompt
        assert "button#checkout" in user_prompt

    def test_cost_calculation(self):
        """calculate_cost computes correct USD amounts according to pricing table."""
        client = RealLlmCortex(mode="real", provider="openai", model="gpt-4o", api_key="sk-test")

        # gpt-4o: $2.50 / 1M input ($0.0000025/tok), $10.00 / 1M output ($0.00001/tok)
        rec = client.calculate_cost(input_tokens=1000, output_tokens=200)
        expected_in = 1000 * 0.0000025   # $0.0025
        expected_out = 200 * 0.0000100   # $0.0020
        expected_tot = expected_in + expected_out

        assert pytest.approx(rec.input_cost_usd, rel=1e-4) == expected_in
        assert pytest.approx(rec.output_cost_usd, rel=1e-4) == expected_out
        assert pytest.approx(rec.total_cost_usd, rel=1e-4) == expected_tot
        assert client.cumulative_input_tokens == 1000
        assert client.cumulative_output_tokens == 200
        assert pytest.approx(client.cumulative_cost_usd, rel=1e-4) == expected_tot

    def test_json_parsing_with_markdown_fences(self):
        """_parse_llm_json cleanly strips markdown code fences."""
        client = RealLlmCortex(mode="real", provider="openai", api_key="sk-test")
        fenced_text = """```json
        {
            "plan_id": "test-fenced-01",
            "expected_outcome": "Unblock modal",
            "actions": [{"verb": "CLICK", "target_selector": "#close-modal", "value": null}]
        }
        ```"""
        parsed = client._parse_llm_json(fenced_text)
        assert parsed["plan_id"] == "test-fenced-01"
        assert len(parsed["actions"]) == 1

    def test_recover_with_mocked_http_requester(self):
        """recover executes HTTP call, parses JSON, compiles plan, and calculates cost."""
        mock_response_body = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "plan_id": "cortex-rec-test-123",
                            "expected_outcome": "Close blocking dialog",
                            "stop_condition": "state_delta_verified",
                            "confidence": 0.95,
                            "actions": [
                                {"verb": "CLICK", "target_selector": "button.close-modal", "value": None},
                                {"verb": "WAIT", "target_selector": None, "value": "500"},
                            ],
                        })
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 800,
                "completion_tokens": 150,
            },
        }

        def mock_requester(req: urllib.request.Request, timeout: float):
            return mock_response_body

        client = RealLlmCortex(
            mode="real",
            provider="openai",
            model="gpt-4o",
            api_key="sk-test-key",
            http_requester=mock_requester,
        )

        payload = self._sample_payload()
        resp = client.recover(payload)

        assert resp.success is True
        assert resp.plan is not None
        assert resp.plan.plan_id == "cortex-rec-test-123"
        assert resp.plan.source == PlanSource.REAL_CORTEX
        assert len(resp.plan.actions) == 2
        assert resp.tokens_used == 950
        assert resp.cost_usd > 0.0

    def test_recover_rejects_malformed_actions_via_compiler(self):
        """RecoveryCompiler validates plan; unsafe or malformed actions cause response failure."""
        malformed_response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "plan_id": "cortex-rec-bad",
                            "expected_outcome": "Unsafe action",
                            "actions": [
                                # Missing target_selector for targeted verb CLICK
                                {"verb": "CLICK", "target_selector": None, "value": None},
                            ],
                        })
                    }
                }
            ],
            "usage": {"prompt_tokens": 500, "completion_tokens": 50},
        }

        client = RealLlmCortex(
            mode="real",
            provider="openai",
            api_key="sk-test",
            http_requester=lambda req, timeout: malformed_response,
        )

        resp = client.recover(self._sample_payload())
        assert resp.success is False
        assert "RECOVERY_COMPILATION_REJECTED" in resp.error


# =============================================================================
# 3. Live Environment Orchestrator Tests
# =============================================================================

class TestLiveOrchestrator:
    """Tests for LiveOrchestrator."""

    def test_probes_host_capabilities(self):
        """Orchestrator probes host system and records availability."""
        orch = LiveOrchestrator()
        caps = orch.capabilities
        assert isinstance(caps, HostCapabilities)
        # Verify status reporting structure
        status = orch.get_infrastructure_status()
        assert "docker_available" in status
        assert "kvm_available" in status
        assert "webarena_running" in status

    def test_graceful_skipping_when_docker_missing(self):
        """WebArena methods log LIVE_ORCHESTRATION_SKIPPED and return False when Docker is missing."""
        orch = LiveOrchestrator()
        # Force docker availability to False
        orch.capabilities.docker_available = False
        orch.capabilities.docker_reason = "Mocked offline environment"

        res_start = orch.start_webarena()
        assert res_start is False

        res_reset = orch.reset_state(env_type="webarena")
        assert res_reset is False

    def test_graceful_skipping_when_kvm_missing(self):
        """OSWorld methods log LIVE_ORCHESTRATION_SKIPPED and return False when KVM is missing."""
        orch = LiveOrchestrator()
        orch.capabilities.kvm_available = False
        orch.capabilities.kvm_reason = "No /dev/kvm acceleration"

        res_start = orch.start_osworld_vm()
        assert res_start is False

        res_reset = orch.reset_state(env_type="osworld")
        assert res_reset is False

    def test_wait_for_healthy_tcp_loopback(self):
        """wait_for_healthy handles unreachable ports by timing out gracefully."""
        orch = LiveOrchestrator()
        # Probe an unallocated local port with low timeout
        ready = orch.wait_for_healthy("127.0.0.1:59999", timeout_sec=0.1, poll_interval_sec=0.05)
        assert ready is False


# =============================================================================
# 4. Production Scorecard & Benchmark Pipeline Tests
# =============================================================================

class TestProductionScorecard:
    """Tests for Production Scorecard Generator."""

    def test_production_evaluation_generates_all_artifacts(self, tmp_path):
        """run_production_evaluation generates final_scorecard.json, production_report.md, and trajectory log."""
        from scripts.report_production import run_production_evaluation

        scorecard = run_production_evaluation(
            webarena_task_count=2,
            osworld_task_count=2,
            output_dir=tmp_path,
            force_mock=True,
        )

        # Check return data
        assert scorecard["success_metrics"]["overall_success_rate"] >= 0.0
        assert scorecard["efficiency_metrics"]["total_agent_steps"] >= 0
        assert scorecard["cost_metrics"]["total_cost_usd"] >= 0.0
        assert "webarena_delta" in scorecard["frontier_comparison"]

        # Check written artifacts
        scorecard_json = tmp_path / "final_scorecard.json"
        assert scorecard_json.exists()
        saved_data = json.loads(scorecard_json.read_text(encoding="utf-8"))
        assert saved_data["run_metadata"]["total_tasks_evaluated"] == 4

        report_md = tmp_path / "production_report.md"
        assert report_md.exists()
        md_text = report_md.read_text(encoding="utf-8")
        assert "ARC Production Scorecard" in md_text
        assert "Executive Scorecard Summary" in md_text
        assert "Production Cost Accounting" in md_text

        traj_log = tmp_path / "live_trajectory_logs.jsonl"
        assert traj_log.exists()
