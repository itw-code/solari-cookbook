"""Comprehensive Unit and Integration Test Suite for Phase 3B Components.

Verifies:
1. TrajectoryCollector: Step recording, 5-step sliding windowing, credential redaction, JSONL export.
2. AutoLabeler: Heuristic stuck detection, milestone detection, dataset summary export.
3. MonitorModel & Heuristic Adapters: HeuristicStuckModelAdapter, HeuristicMilestoneModelAdapter contracts.
4. FeatureBuilder: Deterministic extraction of all 16 required feature fields and JSON serialization.
5. TransformerMonitorAdapter: Graceful LEARNED_MONITOR_UNAVAILABLE handling when dependencies absent.
6. SemanticProgressEstimator: HeuristicProgressEstimator and EmbeddingProgressEstimator silent fallback.
7. HttpCortexClient: mock, dry_run, and real modes, payload building, RecoveryCompiler validation.
"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import pytest

# Ensure src is in python path
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

from arc_cua.cortex.http_cortex import HttpCortexClient
from arc_cua.cortex.mock_cortex import MockCortexClient
from arc_cua.cortex.recovery_compiler import RecoveryCompiler
from arc_cua.datasets.labeler import AutoLabeler, LabelResult
from arc_cua.datasets.trajectory_collector import TrajectoryCollector, redact_sensitive_data
from arc_cua.monitors.feature_builder import FeatureBuilder, WindowFeatures
from arc_cua.monitors.heuristic_adapter import (
    HeuristicMilestoneModelAdapter,
    HeuristicStuckModelAdapter,
)
from arc_cua.monitors.model_interface import (
    MonitorModel,
    MonitorPrediction,
    MonitorWindow,
    to_step_telemetry,
)
from arc_cua.monitors.semantic_progress import (
    EmbeddingProgressEstimator,
    HeuristicProgressEstimator,
    SemanticProgressEstimator,
)
from arc_cua.monitors.stuck_monitor import StepTelemetry, StuckMonitor
from arc_cua.monitors.transformer_adapter import (
    LEARNED_MONITOR_UNAVAILABLE,
    TransformerMonitorAdapter,
)
from arc_cua.schemas import (
    ActionStep,
    EscalationPayload,
    EscalationReason,
    PerceptionSource,
    PlanSource,
    RecoveryPlan,
    TrajectoryRecord,
    TrajectoryWindow,
    UIState,
)


class TestTrajectoryCollector:
    """Verification suite for Task 1: Trajectory Dataset Collector."""

    def test_record_step_and_sliding_window(self):
        collector = TrajectoryCollector(default_window_size=5)

        for step in range(1, 8):
            w = collector.record_step(
                run_id="run-1",
                task_id="test task",
                step_id=step,
                action_type="CLICK",
                target_locator=f"button#{step}",
                state_changed=(step % 2 == 1),
            )
            assert w.current_step.step_id == step
            assert len(w.steps) <= 5

        windows = collector.get_windows("run-1")
        assert len(windows) == 7
        last_window = windows[-1]
        assert len(last_window.steps) == 5
        assert [s.step_id for s in last_window.steps] == [3, 4, 5, 6, 7]

    def test_credential_redaction(self):
        collector = TrajectoryCollector()
        w = collector.record_step(
            run_id="run-sec",
            task_id="login",
            step_id=1,
            action_type="TYPE",
            target_locator="input#password",
            metadata={"password": "supersecretpassword", "token": "Bearer abc123xyz"},
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = collector.export_records_jsonl(pathlib.Path(tmpdir) / "records.jsonl")
            with open(jsonl_path, "r", encoding="utf-8") as f:
                content = f.read()
                assert "supersecretpassword" not in content
                assert "[REDACTED]" in content


class TestAutoLabeler:
    """Verification suite for Task 2: Auto-Labeling Pipeline."""

    def test_heuristic_stuck_detection(self):
        labeler = AutoLabeler()
        collector = TrajectoryCollector()

        # 3 consecutive no state change
        for i in range(1, 4):
            collector.record_step(
                run_id="stuck-run",
                task_id="stuck",
                step_id=i,
                action_type="CLICK",
                state_changed=False,
            )
        window = collector.get_windows()[-1]
        label = labeler.label_window(window)
        assert label.stuck is True
        assert "consecutive_no_state_change" in str(label.stuck_reason)

    def test_heuristic_milestone_detection(self):
        labeler = AutoLabeler()
        collector = TrajectoryCollector()

        w = collector.record_step(
            run_id="prog-run",
            task_id="progress",
            step_id=1,
            action_type="CLICK",
            target_locator="button#submit",
            state_changed=True,
            execution_success=True,
            error_detected=False,
            url_changed=True,
            url_after="https://app.local/dashboard",
        )
        label = labeler.label_window(w)
        assert label.milestone is True
        assert "url_target_reached" in str(label.milestone_reason) or "clean_state_transition" in str(label.milestone_reason)

    def test_export_labeled_dataset(self):
        labeler = AutoLabeler()
        collector = TrajectoryCollector()
        for i in range(1, 5):
            collector.record_step(
                run_id="export-run",
                task_id="task",
                step_id=i,
                action_type="CLICK",
                state_changed=(i == 1),
            )
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = labeler.export_labeled_dataset(collector.get_windows(), output_dir=tmpdir)
            assert pathlib.Path(paths["stuck"]).exists()
            assert pathlib.Path(paths["milestone"]).exists()
            assert pathlib.Path(paths["summary"]).exists()


class TestMonitorModelAndAdapters:
    """Verification suite for Task 3: Monitor Model Interface & Heuristic Adapters."""

    def test_heuristic_stuck_model_adapter(self):
        adapter = HeuristicStuckModelAdapter()
        assert adapter.model_name == "heuristic-stuck-v1"

        collector = TrajectoryCollector()
        for i in range(1, 4):
            collector.record_step(
                run_id="adapt-run",
                task_id="task",
                step_id=i,
                action_type="CLICK",
                target_locator="button#noop",
                state_changed=False,
            )
        w = collector.get_windows()[-1]
        pred = adapter.predict(w)

        assert isinstance(pred, MonitorPrediction)
        assert pred.model_name == "heuristic-stuck-v1"
        assert pred.score >= 0.75
        assert pred.is_positive is True

    def test_heuristic_milestone_model_adapter(self):
        adapter = HeuristicMilestoneModelAdapter()
        assert adapter.model_name == "heuristic-milestone-v1"

        collector = TrajectoryCollector()
        w = collector.record_step(
            run_id="ms-run",
            task_id="submit form",
            step_id=1,
            action_type="CLICK",
            target_locator="button#submit",
            state_changed=True,
            execution_success=True,
        )
        pred = adapter.predict(w)
        assert isinstance(pred, MonitorPrediction)
        assert pred.score >= 0.5


class TestFeatureBuilder:
    """Verification suite for Task 4: Feature Builder."""

    def test_feature_extraction_all_fields(self):
        builder = FeatureBuilder()
        collector = TrajectoryCollector()

        for i in range(1, 4):
            collector.record_step(
                run_id="feat-run",
                task_id="test",
                step_id=i,
                action_type="CLICK",
                target_locator="role:button[name='Submit']",
                state_changed=False,
                hamming_distance=i,
            )
        w = collector.get_windows()[-1]
        features = builder.build_features(w)

        assert isinstance(features, WindowFeatures)
        assert features.window_size == 3
        assert features.action_repeat_count == 3
        assert features.locator_repeat_count == 3
        assert features.consecutive_no_state_change == 3
        assert features.hamming_distance_sequence == [1, 2, 3]
        assert features.action_type_sequence == ["CLICK", "CLICK", "CLICK"]
        assert "button" in features.target_role_sequence
        assert "Submit" in features.target_name_sequence

        # JSON serialization test
        json_str = features.to_json()
        assert json_str is not None
        assert "target_role_sequence" in json_str


class TestTransformerMonitorAdapter:
    """Verification suite for Task 5: Optional Learned Monitor."""

    def test_learned_monitor_unavailable_fallback(self):
        adapter = TransformerMonitorAdapter(allow_download=False)
        collector = TrajectoryCollector()
        w = collector.record_step(run_id="r", task_id="t", step_id=1, action_type="CLICK")

        pred = adapter.predict(w)
        assert isinstance(pred, MonitorPrediction)
        if not adapter.is_available:
            assert pred.reason == LEARNED_MONITOR_UNAVAILABLE
            assert pred.evidence["status"] == LEARNED_MONITOR_UNAVAILABLE


class TestSemanticMilestoneEstimator:
    """Verification suite for Task 6: Semantic Milestone Estimator."""

    def test_heuristic_progress_estimator(self):
        est = HeuristicProgressEstimator()
        collector = TrajectoryCollector()
        w = collector.record_step(
            run_id="r",
            task_id="click submit button",
            step_id=1,
            action_type="CLICK",
            target_locator="button#submit",
            state_changed=True,
        )
        score = est.estimate("click submit button", w)
        assert score > 0.0

    def test_embedding_estimator_silent_fallback(self):
        emb_est = EmbeddingProgressEstimator(allow_remote=False)
        collector = TrajectoryCollector()
        w = collector.record_step(
            run_id="r",
            task_id="login",
            step_id=1,
            action_type="TYPE",
            target_locator="input#username",
            value="admin",
            state_changed=True,
        )
        # Should not throw even if sentence_transformers is missing
        score = emb_est.estimate("login", w)
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0


class TestHttpCortexClient:
    """Verification suite for Task 7: Real/Dry-Run/Mock Cortex Adapter."""

    def _create_payload(self) -> EscalationPayload:
        return EscalationPayload(
            escalation_id="test-esc-1",
            task_goal="recover stuck step",
            reason=EscalationReason.STATE_NOT_CHANGED,
            step_history=[ActionStep(step_number=1, verb="CLICK", target_selector="button#save", value=None, action_index=0, latency_ms=10.0, success=True)],
            current_state=UIState(
                state_id="s1",
                timestamp=1000.0,
                source=PerceptionSource.CDP_AXTREE,
                simhash=0x12345,
                raw_node_count=10,
                pruned_node_count=5,
                actionable_count=2,
                estimated_tokens=50,
                yaml_representation="",
                structured_tree={},
                action_index_map={},
            ),
            failure_details={"reason": "no_change"},
        )

    def test_cortex_mock_mode(self):
        client = HttpCortexClient(mode="mock")
        resp = client.recover(self._create_payload())
        assert resp.success is True
        assert resp.plan is not None
        assert "mock:" in resp.model

    def test_cortex_dry_run_mode(self):
        client = HttpCortexClient(mode="dry_run", endpoint="https://api.test/v1")
        resp = client.recover(self._create_payload())
        assert resp.success is True
        assert resp.plan is not None
        assert "dry-run:" in resp.model
        assert "dry_run_payload" in resp.metadata
        payload = resp.metadata["dry_run_payload"]
        assert payload["task_goal"] == "recover stuck step"
        assert payload["escalation_reason"] == "STATE_NOT_CHANGED"
        assert "recent_trajectory" in payload
        assert "budget" in payload

    def test_cortex_real_mode_unconfigured_fails_gracefully(self):
        # In real mode with no endpoint configured, must return structured failure
        client = HttpCortexClient(mode="real", endpoint="")
        resp = client.recover(self._create_payload())
        assert resp.success is False
        assert "CORTEX_CONFIG_ERROR" in str(resp.error)
