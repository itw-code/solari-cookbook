# Cross-Repository Architectural Reference & Evidence Map

**Repository:** `arc-hybrid-cua`  
**Date:** 2026-09-20  
**Status:** Phase 1 Remediation Complete  

This document maps architectural decisions, protocol conventions, and configuration parameters in `arc-hybrid-cua` to primary source evidence in **`coldstart/arc-cookbook`** and **`research-assets/arc-docs`**.

---

## 1. MicroVM Image & Template Resolution

| Feature / Contract | `arc-hybrid-cua` Implementation | Upstream Reference | Evidence / Notes |
| :--- | :--- | :--- | :--- |
| **Base Template Identifier** | `ArcImageProvider` checks `os.environ["ARC_BASE_TEMPLATE"]` defaulting to `"base"`. | `coldstart/arc-cookbook/src/arc/orchestrate.ts:30` | `const BASE_TEMPLATE = process.env.ARC_BASE_TEMPLATE ?? "base"` |
| **Dynamic Image Resolution** | `src/arc_cua/image_provider.py` resolves kernels and ext4 rootfs without hardcoded paths. | `research-assets/arc-docs/changelog.html:266-267` | Arc supports snapshots, reusable templates, and custom images (`apt`/`pip` builds). |
| **Kernel & Drive Overrides** | `ARC_KERNEL_PATH` and `ARC_ROOTFS_PATH` env vars override defaults. | `coldstart/arc-cookbook/src/arc/orchestrate.ts:32-33` | Follows standard configuration pattern (`COLDSTART_APP_PORT`, `COLDSTART_DB_PATH`). |
| **Mock Fixture Fallback** | `ArcImageProvider.resolve(allow_mock=True)` creates sparse mock images in `/tmp`. | `coldstart/arc-cookbook/src/arc/driver.ts:133-145` | Mirrors `MockArc.createSandbox()` pattern for deterministic CI / local host execution. |

---

## 2. Chrome DevTools Protocol (CDP) Endpoint Discovery

| Feature / Contract | `arc-hybrid-cua` Implementation | Upstream Reference | Evidence / Notes |
| :--- | :--- | :--- | :--- |
| **Single API Gateway Routing** | `CDPDiscovery` supports `https://api.getarc.com/v1/browser/cdp`. | `research-assets/arc-docs/changelog.html:186-189` | *"Browser, sandbox, and desktop requests now go through one host: api.getarc.com"*. |
| **Managed CDP Client Endpoint** | `CDPDiscovery` checks `cdpEndpoint`, `ARC_CDP_ENDPOINT`, and `CDP_ENDPOINT`. | `research-assets/arc-docs/changelog.html:248` | *"launch() returns a Playwright browser; or take a cdpEndpoint for any CDP client."* |
| **Autonomous Ingress Tunnel Bridge** | `CDPDiscovery` checks `TARGET_URL` (from Cloudflare Quick Tunnel) before mock fallback. | `coldstart/arc-cookbook/src/qa-framework/tunnel.ts:37-41,114-118` | `coldstart tunnel <port>` starts Cloudflare Quick Tunnel (`https://*.trycloudflare.com`) and exports `process.env.TARGET_URL`. |
| **Local Debugging Probe** | Probes TCP `127.0.0.1:9222`/`9223` and standard Linux UDS `/tmp/chromium-cdp.sock`. | `coldstart/arc-cookbook/src/qa-framework/session-guard.ts:10-15` | Fallback loop for local containerized Chromium instances. |

---

## 3. Playwright Public API Compliance (Phase 2 Interface Contract)

| Feature / Contract | `arc-hybrid-cua` Implementation | Upstream Reference | Evidence / Notes |
| :--- | :--- | :--- | :--- |
| **Public Locator Automation** | `PlaywrightActionExecutorInterface` strictly uses `page.locator().click()`, `fill()`, `select_option()`. | `coldstart/arc-cookbook/src/agent/index.ts:66-70` | Native Playwright `Page` methods (`newPage()`, `setViewportSize()`, `emulateMedia()`). |
| **Internal Banning Audit** | `audit_public_api_compliance()` actively checks for and forbids `_channel`, `_connection`, `_impl_obj`. | Reviewer Checkpoint 01 Feedback | Prohibits dependency on private Node/Python CDP transport bindings; guarantees portability across Playwright version bumps. |
| **Input Synthesis & Natural Jitter** | `ActionPayload` and `BasePlaywrightExecutor` prepare structured tuples for Phase 2 Reflex execution. | `ARCHITECTURE.md:43-51` | $\text{Action} = \langle \text{Verb}, \text{TargetLocator}, \text{Parameters} \rangle$. |

---

## 4. Perception Pipeline & Accessibility Representation

| Feature / Contract | `arc-hybrid-cua` Implementation | Upstream Reference | Evidence / Notes |
| :--- | :--- | :--- | :--- |
| **Rich Locator Metadata** | `AXNode` outputs `css_selector`, `xpath`, `backend_dom_id`, `text`, `aria_label`, `bbox`. | `coldstart/arc-cookbook/src/qa-framework/selectors.ts` | Empowers local Reflex cache to generate self-healing selectors without DOM re-traversal. |
| **Token Budget Compliance** | Compact linearized YAML consumes $\le 1,200$ tokens ($p_{50}=1,008$ tokens with full locators). | `IMPLEMENTATION_PLAN.md:96` | Deng et al. (2023, Mind2Web), Zhou et al. (2024, WebArena). |
| **Token Reduction Target** | Achieves $>86\%$ (measured $90.15\%$) reduction compared to raw HTML representations. | `IMPLEMENTATION_PLAN.md:95` | Eliminates $1,600 - 3,200$ vision token tax per step. |

---

## 5. Non-Blocking Desktop Perception & Telemetry

| Feature / Contract | `arc-hybrid-cua` Implementation | Upstream Reference | Evidence / Notes |
| :--- | :--- | :--- | :--- |
| **Queue-Based Event Dispatch** | `AT_SPI_Bridge` pushes events to background worker thread in $<0.005\,\text{ms}$ ($p_{50}=0.0014\,\text{ms}$). | `ARCHITECTURE.md:23-30` | Eliminates perception stalling during fast window switching or slow subscriber callbacks. |
| **Real vs. Mock Classification** | Explicit `mode="real"` vs. `mode="mock"` with `is_mock` property. | `coldstart/arc-cookbook/src/arc/driver.ts:63-65` | Distinct separation between live environment probing and deterministic test fixtures. |
| **64-bit SimHash State Tracking** | `compute_simhash64()` in `src/arc_cua/telemetry.py`. | `ARCHITECTURE.md:67-73` | Computes $H(s_t)$ for zero-pixel traps and ModernBERT cyclic oscillation detection. |
| **Escalation Logging** | `TelemetryCollector` exports to JSONL and summary JSON with p50/p95/p99. | `IMPLEMENTATION_PLAN.md:286` | Records telemetry for offline ModernBERT classifier training. |
