# instructions_05.md

## Phase 4C Review Result

Status: PASS

Approved Phase 4C components:

- `src/arc_cua/eval/osworld_env.py`
- `src/arc_cua/eval/osworld_mapper.py`
- `src/arc_cua/eval/osworld_assertions.py`
- `src/arc_cua/eval/tasks_osworld.py`
- `src/arc_cua/eval/osworld_runner.py`
- `tests/test_phase4c_osworld.py`

Review notes:

1. OSWorld environment adapter and mock POSIX filesystem are approved.
2. Task mapper and assertion adapter (File, Terminal, AT-SPI) are approved.
3. Full repository test suite (125 tests) passes with 100% success.
4. Phases 1 through 4 are officially complete.
5. Phase 5 must now bridge the gap between offline CI mocks and live production infrastructure.

---

## Phase 5 Mission

Build the Live Production Integration & Final Scorecard layer.

Work in:

```text
arc-hybrid-cua/
```

Phase 5 connects the fully tested offline architecture to real-world production infrastructure:
1. Real Arc Cloud MicroVMs/Browsers (via Arc REST API / SDK).
2. Real Cortex LLM (e.g., TypeSafe Jev, OpenAI, or Anthropic).
3. Live Benchmark Orchestration (WebArena Docker / OSWorld VM).
4. Final Production Cost & Success Scorecard.

---

## Phase 5 Scope

Allowed:

- Arc Cloud REST/SDK driver
- Real Cortex LLM HTTP adapter with strict cost tracking
- Live environment orchestrator (Docker/VM provisioning)
- Production scorecard generator
- End-to-end live smoke test
- Final documentation and packaging

Not allowed:

- Rewriting Phase 1-4 core logic
- Breaking the 125-test offline CI suite
- Hardcoding API keys or secrets

---

## Task 1: Arc Cloud Driver

Create:

```text
src/arc_cua/cloud/arc_driver.py
```

Purpose:

Connect to the real Arc Cloud API to provision and manage ephemeral MicroVMs, stealth browsers, and desktops.

Requirements:

1. Support environment variables: `ARC_API_KEY`, `ARC_REGION`.
2. Implement methods: `provision_browser()`, `provision_desktop()`, `get_cdp_endpoint()`, `get_vnc_stream()`, `terminate()`.
3. Implement automatic session recording and replay URL capture.
4. If `ARC_API_KEY` is missing, gracefully fallback to local/mock mode without crashing.
5. Track Arc compute time (ms) for the final cost ledger.

---

## Task 2: Real Cortex LLM Adapter

Create:

```text
src/arc_cua/cortex/real_llm_cortex.py
```

Purpose:

Connect the `HttpCortexClient` to a real frontier or System-1 model (e.g., TypeSafe Jev, OpenAI GPT-4o, Anthropic Claude).

Requirements:

1. Support environment variables: `CORTEX_MODE=real`, `CORTEX_PROVIDER` (jev|openai|anthropic), `CORTEX_API_KEY`, `CORTEX_MODEL`.
2. Format the `EscalationPayload` into a strict system/user prompt demanding a JSON `RecoveryPlan`.
3. Parse the LLM response and pass it through the existing `RecoveryCompiler`.
4. Track exact input/output tokens and calculate real API cost using provider pricing.
5. Implement strict timeout and retry logic.
6. If `CORTEX_MODE != real`, do not instantiate this client.

---

## Task 3: Live Environment Orchestrator

Create:

```text
src/arc_cua/eval/live_orchestrator.py
```

Purpose:

Manage the lifecycle of real WebArena Docker containers or OSWorld VMs for live benchmark runs.

Requirements:

1. Support `docker-compose` commands for WebArena (if Docker is available on the host).
2. Support SSH/QEMU commands for OSWorld (if KVM is available).
3. Implement `wait_for_healthy()` to ensure databases and web servers are ready before running tasks.
4. Implement `reset_state()` to wipe databases and restore VM snapshots between tasks.
5. If live infrastructure is unavailable, log `LIVE_ORCHESTRATION_SKIPPED` and exit gracefully.

---

## Task 4: Production Scorecard Generator

Create:

```text
scripts/report_production.py
```

Purpose:

Run a small subset of live tasks (e.g., 5 WebArena, 5 OSWorld) and generate the final production report.

Requirements:

1. Calculate real total cost: Arc VM time + Real LLM tokens + Proxy/Storage costs.
2. Calculate real wall-clock time and Step Efficiency Ratio (SER).
3. Compare live Hybrid success rate vs. theoretical baseline.
4. Output artifacts to `artifacts/production/`:
   - `final_scorecard.json`
   - `production_report.md`
   - `live_trajectory_logs.jsonl`

---

## Task 5: Final Tests & Documentation

Create:

```text
tests/test_phase5_production.py
```

Required tests:

1. Arc driver gracefully handles missing API keys.
2. Real LLM adapter correctly formats prompts and parses JSON.
3. Cost ledger accurately calculates real token costs.
4. Live orchestrator safely skips if Docker/KVM is missing.
5. Full 125-test offline CI suite still passes (no regressions).

Update `ARCHITECTURE.md` and `IMPLEMENTATION_PLAN.md` with Phase 5 completion, production deployment guide, and final metric targets.

---

## Definition of Done

Phase 5 is complete only if:

1. Arc Cloud driver exists and handles missing keys safely.
2. Real Cortex LLM adapter exists and tracks token costs.
3. Live orchestrator exists and handles missing Docker/KVM safely.
4. Production scorecard generator exists.
5. Tests pass without regressions.
6. Final documentation is updated.

---

## Required Final Output

After completing Phase 5, create:

```text
checkpoint_05.md
```

Use this format:

```markdown
# checkpoint_05.md

## 1. Phase 5 Status

- [ ] Arc Cloud driver
- [ ] Real Cortex LLM adapter
- [ ] Live environment orchestrator
- [ ] Production scorecard generator
- [ ] Final tests
- [ ] Final documentation

## 2. Files Added/Updated

List files.

## 3. Live vs Offline Status

Clearly state what was tested live vs what was skipped due to missing host infrastructure (Docker/KVM/API Keys).

## 4. Test Results

Include pass/fail count (must include the 125 baseline tests).

## 5. Production Cost Model

Explain how real Arc + LLM costs are calculated.

## 6. Final Project Status

Summarize the completion of Phases 1 through 5.

## 7. Remaining Blockers

List blockers (e.g., waiting for live Arc API keys to run full benchmark).
```

---

## Stop Condition

Stop after producing:

```text
checkpoint_05.md
```
