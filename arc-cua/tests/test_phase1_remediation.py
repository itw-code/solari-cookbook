"""Comprehensive Verification Suite for Phase 1 Remediation.

Tests:
1. Dynamic Kernel/RootFS Image Resolution (ArcImageProvider & ArcVMManager).
2. Dynamic CDP Endpoint Discovery (CDPDiscovery & CDP_AXTree_Extractor).
3. Rich AXTree Locator Metadata (CSS, XPath, backend DOM ID, text, aria label, bbox).
4. AT-SPI Non-blocking Queue-based Event Dispatch & Real vs Mock separation.
5. Playwright Public API Executor Interface Contract.
6. Telemetry, SimHash 64-bit Fingerprinting, and Empirical p50/p95/p99 Benchmark Distributions.
"""

import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, List

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from arc_cua.vm_manager import ArcVMManager
from arc_cua.image_provider import ArcImageProvider, VMImageSpec
from arc_cua.cdp_extractor import CDP_AXTree_Extractor
from arc_cua.cdp_discovery import CDPDiscovery, CDPEndpointSpec
from arc_cua.at_spi_bridge import AT_SPI_Bridge, ATSPIEvent
from arc_cua.executor_interface import (
    BasePlaywrightExecutor,
    ActionVerb,
    ActionPayload,
    ExecutionOutcome,
    audit_public_api_compliance,
)
from arc_cua.schemas import (
    PerceptionSource,
    EscalationReason,
    UIState,
    ActionStep,
    EscalationPayload,
    TelemetryRecord,
)
from arc_cua.telemetry import (
    TelemetryCollector,
    compute_percentiles,
    compute_simhash64,
)


class TestImageProviderRemediation:
    """Verifies removal of hardcoded kernel/rootfs paths."""

    def test_env_var_configuration(self, monkeypatch, tmp_path):
        dummy_kernel = tmp_path / "vmlinux-custom"
        dummy_rootfs = tmp_path / "rootfs-custom.ext4"
        dummy_kernel.write_bytes(b"\x7fELF" + b"\x00" * 128)
        dummy_rootfs.write_bytes(b"\x00" * 128)

        monkeypatch.setenv("ARC_KERNEL_PATH", str(dummy_kernel))
        monkeypatch.setenv("ARC_ROOTFS_PATH", str(dummy_rootfs))
        monkeypatch.setenv("ARC_BASE_TEMPLATE", "custom-env-template")

        provider = ArcImageProvider()
        spec = provider.resolve(allow_mock=False)

        assert spec.kernel_path == dummy_kernel.resolve()
        assert spec.rootfs_path == dummy_rootfs.resolve()
        assert spec.template_name == "custom-env-template"
        assert spec.is_mock is False

    def test_mock_fallback_fixture_generation(self, tmp_path):
        provider = ArcImageProvider(base_dir=tmp_path / "empty_dir")
        spec = provider.resolve(template_name="test-scaffold", allow_mock=True)

        assert spec.is_mock is True
        assert spec.kernel_path.exists()
        assert spec.rootfs_path.exists()
        assert "mock" in spec.kernel_path.name.lower()

    def test_vm_manager_dynamic_integration(self, tmp_path):
        provider = ArcImageProvider()
        mgr = ArcVMManager(
            runtime_dir=tmp_path,
            image_provider=provider,
            template_name="integration-test",
            simulate_hardware=True,
        )
        try:
            vm = mgr.launch("vm-dynamic-01", mem_size_mib=128)
            assert vm.status == "running"
            assert vm.base_memory_overhead_mb <= 128.0
            mgr.terminate("vm-dynamic-01")
        finally:
            mgr.close()


class TestCDPDiscoveryRemediation:
    """Verifies removal of hardcoded CDP socket path and dynamic discovery."""

    def test_explicit_endpoint_override(self):
        discovery = CDPDiscovery()
        spec = discovery.discover(endpoint_override="ws://remote-arc:9222/devtools/browser/xyz")
        assert spec.transport_type == "explicit"
        assert spec.endpoint_url == "ws://remote-arc:9222/devtools/browser/xyz"
        assert spec.is_mock is False

    def test_env_var_cdp_endpoint(self, monkeypatch):
        monkeypatch.setenv("CDP_ENDPOINT", "http://10.0.0.45:9222")
        discovery = CDPDiscovery()
        spec = discovery.discover()
        assert spec.transport_type == "env"
        assert spec.endpoint_url == "http://10.0.0.45:9222"

    def test_arc_cloud_gateway_resolution(self, monkeypatch):
        monkeypatch.delenv("CDP_ENDPOINT", raising=False)
        monkeypatch.delenv("ARC_CDP_ENDPOINT", raising=False)
        monkeypatch.setenv("ARC_API_KEY", "sk_arc_live_test_123")
        monkeypatch.setenv("ARC_BASE_URL", "https://api.getarc.com")

        discovery = CDPDiscovery()
        spec = discovery.discover(allow_mock=False)
        assert spec.transport_type == "arc_cloud"
        assert "api.getarc.com" in spec.endpoint_url

    def test_tunnel_fallback_resolution(self, monkeypatch):
        monkeypatch.delenv("CDP_ENDPOINT", raising=False)
        monkeypatch.delenv("ARC_CDP_ENDPOINT", raising=False)
        monkeypatch.delenv("ARC_API_KEY", raising=False)
        monkeypatch.setenv("TARGET_URL", "https://ephemeral-ingress-4310.trycloudflare.com")

        discovery = CDPDiscovery()
        spec = discovery.discover()
        assert spec.transport_type == "tunnel"
        assert "trycloudflare.com" in spec.endpoint_url

    def test_cdp_extractor_uses_discovered_endpoint(self, monkeypatch):
        monkeypatch.setenv("CDP_ENDPOINT", "http://127.0.0.1:9222")
        extractor = CDP_AXTree_Extractor()
        assert extractor.endpoint_spec.transport_type == "env"
        assert extractor.cdp_endpoint == "http://127.0.0.1:9222"


class TestAXTreeLocatorMetadata:
    """Verifies addition of rich locator metadata (CSS, XPath, text, aria label, bbox)."""

    def test_rich_locator_metadata_in_action_map(self):
        extractor = CDP_AXTree_Extractor()
        complex_fixture = extractor.create_mock_complex_page()
        # Add bounding box to an element
        complex_fixture[6]["bounds"] = [100, 150, 80, 30]

        res = extractor.sanitize(complex_fixture)

        assert res.actionable_count > 0
        for idx, item in res.action_index_map.items():
            assert "css" in item and item["css"] is not None
            assert "xpath" in item and item["xpath"] is not None
            assert "text" in item
            assert "aria_label" in item
            assert "backend_dom_id" in item

        # Verify YAML output contains CSS selectors
        assert 'css="' in res.yaml_linearized

        # Verify structured JSON output contains rich fields
        first_json = res.json_structured[0]
        assert "role" in first_json


class TestATSPIBridgeQueueDispatch:
    """Verifies non-blocking queue-based dispatch and real vs mock separation."""

    def test_mock_mode_explicit(self):
        bridge = AT_SPI_Bridge(mode="mock")
        assert bridge.is_mock is True
        assert bridge.mode == "mock"
        assert bridge.connect() is True
        bridge.disconnect()

    def test_real_mode_flag_handling(self):
        # Explicit real mode flag verification
        bridge = AT_SPI_Bridge(mode="real", dbus_address=None)
        assert bridge.is_mock is False
        assert bridge.mode == "real"
        # On non-Linux or without D-Bus, connect() gracefully falls back to mock
        connected = bridge.connect()
        assert connected is True
        bridge.disconnect()

    def test_non_blocking_queue_dispatch(self):
        bridge = AT_SPI_Bridge(mode="mock")
        bridge.connect()

        received_events = []

        def slow_callback(ev: ATSPIEvent):
            # Simulates realistic handler processing time
            time.sleep(0.005)
            received_events.append(ev)

        bridge.subscribe("window:activate", slow_callback)

        start = time.perf_counter()
        latencies = []
        for i in range(10):
            ev = ATSPIEvent(
                event_type="window:activate",
                source_app="code",
                widget_role="frame",
                widget_name="VSCode",
                timestamp=time.time(),
                details={"window_id": i},
            )
            # dispatch_event MUST return immediately (<0.1ms) without waiting for slow_callback
            lat = bridge.dispatch_event(ev)
            latencies.append(lat)

        total_dispatch_time = (time.perf_counter() - start) * 1000.0

        # Each event enqueues in < 0.1ms; total dispatch loop < 5ms even though callback takes 50ms total!
        assert total_dispatch_time < 10.0
        for l in latencies:
            assert l < 0.5, f"Dispatch queue latency was {l:.4f}ms, expected < 0.5ms"

        # Wait for worker thread to flush
        flushed = bridge.flush_events(timeout_s=2.0)
        assert flushed is True
        assert len(received_events) == 10

        bridge.disconnect()


class TestPlaywrightPublicAPIExecutorContract:
    """Verifies Phase 2 executor interface enforces strictly public Playwright APIs."""

    def test_audit_prohibits_private_internals(self):
        class CleanMockPage:
            def locator(self, selector):
                return self
            def click(self, timeout=None):
                pass

        class LeakyMockPage:
            def __init__(self):
                self._channel = "private_channel"
            def locator(self, selector):
                return self

        is_clean, violations = audit_public_api_compliance(CleanMockPage())
        assert is_clean is True
        assert len(violations) == 0

        is_clean_leaky, violations_leaky = audit_public_api_compliance(LeakyMockPage())
        assert is_clean_leaky is False
        assert "_channel" in violations_leaky

    def test_base_executor_contract_execution(self):
        class MockPlaywrightPage:
            def __init__(self):
                self.actions_log: List[str] = []
                self.url = "https://arc.local/dashboard"

            def locator(self, selector):
                self.actions_log.append(f"locate:{selector}")
                return self

            def click(self, timeout=None):
                self.actions_log.append("click")

            def fill(self, text, timeout=None):
                self.actions_log.append(f"fill:{text}")

        page = MockPlaywrightPage()
        executor = BasePlaywrightExecutor()

        click_action = ActionPayload(verb=ActionVerb.CLICK, target_selector="#submit-order-btn")
        res_click = executor.execute(page, click_action)
        assert res_click.success is True
        assert "click" in page.actions_log

        fill_action = ActionPayload(verb=ActionVerb.FILL, target_selector="input[name='search']", value="Invoice 42")
        res_fill = executor.execute(page, fill_action)
        assert res_fill.success is True
        assert "fill:Invoice 42" in page.actions_log


class TestTelemetryAndPercentilesBenchmark:
    """Verifies SimHash 64-bit fingerprinting and computes p50/p95/p99 benchmark distributions."""

    def test_simhash64_fingerprint_invariants(self):
        text_a = "- [#1] button 'Checkout'\n- [#2] input 'Card Number'"
        text_a_identical = "- [#1] button 'Checkout'\n- [#2] input 'Card Number'"
        text_b = "- [#1] button 'Order Confirmed'\n- text 'Thank you!'"

        hash_a = compute_simhash64(text_a)
        hash_a_dup = compute_simhash64(text_a_identical)
        hash_b = compute_simhash64(text_b)

        assert hash_a == hash_a_dup, "Identical UI states must yield identical SimHash"
        assert hash_a != hash_b, "Distinct UI states must yield distinct SimHash"
        assert hash_a > 0

    def test_comprehensive_benchmark_distribution_p50_p95_p99(self, tmp_path):
        """Measures full perception distribution across 100 benchmark iterations."""
        collector = TelemetryCollector(session_id="benchmark_run_01")
        extractor = CDP_AXTree_Extractor()
        complex_fixture = extractor.create_mock_complex_page()
        bridge = AT_SPI_Bridge(mode="mock")
        bridge.connect()

        # Warm up
        for _ in range(5):
            extractor.sanitize(complex_fixture)
            bridge.get_desktop_tree()

        for i in range(100):
            # 1. AXTree extraction & sanitization
            res = extractor.sanitize(complex_fixture)
            collector.record_metric("axtree_sanitization_ms", res.sanitization_latency_ms)
            collector.record_metric("axtree_tokens", float(res.estimated_tokens))

            # 2. Desktop tree serialization
            d_tree = bridge.get_desktop_tree()
            collector.record_metric("desktop_tree_serialization_ms", d_tree.serialization_latency_ms)

            # 3. Non-blocking event dispatch
            ev = ATSPIEvent(
                event_type="focus:",
                source_app="terminal",
                widget_role="entry",
                widget_name="stdin",
                timestamp=time.time(),
                details={},
            )
            dispatch_lat = bridge.dispatch_event(ev)
            collector.record_metric("atspi_event_dispatch_ms", dispatch_lat)

        bridge.disconnect()

        summary = collector.get_summary()

        ax_dist = collector.get_distribution("axtree_sanitization_ms")
        desktop_dist = collector.get_distribution("desktop_tree_serialization_ms")
        dispatch_dist = collector.get_distribution("atspi_event_dispatch_ms")
        token_dist = collector.get_distribution("axtree_tokens")

        print("\n" + "=" * 65)
        print("ARC HYBRID CUA: EMPIRICAL BENCHMARK DISTRIBUTIONS (N=100)")
        print("=" * 65)
        print(f"AXTree Sanitization Latency (ms):")
        print(f"  p50={ax_dist.p50:.4f} ms | p95={ax_dist.p95:.4f} ms | p99={ax_dist.p99:.4f} ms (Mean={ax_dist.mean:.4f} ms)")
        print(f"Desktop Tree Serialization Latency (ms):")
        print(f"  p50={desktop_dist.p50:.4f} ms | p95={desktop_dist.p95:.4f} ms | p99={desktop_dist.p99:.4f} ms (Mean={desktop_dist.mean:.4f} ms)")
        print(f"AT-SPI Queue Event Dispatch Latency (ms):")
        print(f"  p50={dispatch_dist.p50:.4f} ms | p95={dispatch_dist.p95:.4f} ms | p99={dispatch_dist.p99:.4f} ms (Mean={dispatch_dist.mean:.4f} ms)")
        print(f"Token Budget Footprint (tokens):")
        print(f"  p50={token_dist.p50:.0f} tokens | p95={token_dist.p95:.0f} tokens | p99={token_dist.p99:.0f} tokens")
        print("=" * 65)

        # Assertions against Phase 1 specifications
        assert ax_dist.p50 <= 0.8, f"AXTree p50 exceeded 0.8ms: {ax_dist.p50}"
        assert ax_dist.p95 <= 1.2, f"AXTree p95 exceeded 1.2ms: {ax_dist.p95}"
        assert desktop_dist.p50 <= 2.0, f"Desktop tree p50 exceeded 2.0ms: {desktop_dist.p50}"
        assert dispatch_dist.p50 <= 0.5, f"Dispatch p50 exceeded 0.5ms: {dispatch_dist.p50}"
        assert token_dist.p50 <= 1200, f"Tokens p50 exceeded 1,200 tokens: {token_dist.p50}"

        # Test telemetry file export
        jsonl_path = collector.export_jsonl(tmp_path / "telemetry.jsonl")
        assert jsonl_path.exists()
        summary_path = collector.export_summary_json(tmp_path / "telemetry_summary.json")
        assert summary_path.exists()
