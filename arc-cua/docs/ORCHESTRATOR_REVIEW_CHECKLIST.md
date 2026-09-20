# Orchestrator & Principal Review Checklist: ARC

This document outlines the formal review gates and criteria required before transitioning from the **RFC & Planning Phase** to active development.

---

## Gate 0: Conceptual & Architectural Alignment
- [ ] **Problem Formulation**: Confirm the "Vision Tax" characterization (1.8s–3.5s latency, 1.6k–3.2k tokens/step, $0.01–$0.05/step) accurately reflects our benchmark baseline data.
- [ ] **Dual-Tier Hierarchy**: Validate the separation of concerns between the **Reflex Loop** (in-VM deterministic execution + local quantized SLM) and **Cortex Loop** (cloud frontier reasoning).
- [ ] **MicroVM Runtime Viability**: Confirm Arc Firecracker microVM image specifications (Linux kernel `userfaultfd` support, D-Bus session support, and Xvfb display architecture).

---

## Gate 1: Phase 1 Review (Infrastructure & Perception)
- [ ] **Task 1.1 (MicroVM Snapshotting)**: Review Firecracker snapshot restore latency target ($\le 5.0\,\text{ms}$) and state-forking mechanics (Agache et al., 2020).
- [ ] **Task 1.2 (CDP AXTree Extraction)**: Review zero-copy Unix domain socket bridge and token-budget ceiling ($\le 1,200$ tokens per state) (Zhou et al., 2024; Deng et al., 2023).
- [ ] **Task 1.3 (Linux AT-SPI D-Bus)**: Verify desktop widget state-change event subscriptions and X11 window coordination (Xie et al., 2024).
- [ ] **Task 1.4 (Visual Fallback Trigger)**: Confirm the criteria for triggering local INT8 OmniParser (canvas presence, sparse AXTree) and the confidence cutoff ($\tau \le 0.70$) for immediate Cortex escalation.

---

## Gate 2: Phase 2 Review (The Reflex Engine)
- [ ] **Task 2.1 (Sub-Goal Playwright Compiler)**: Review Playwright primitive action execution contracts (`CLICK`, `TYPE`, `SELECT`, `SCROLL`, `WAIT`).
- [ ] **Task 2.2 (Local Quantized SLM)**: Review model selection (Qwen2-VL-2B vs. UI-TARS-2B), INT4 quantization overhead, and JSON grammar-guided decoding constraints.
- [ ] **Task 2.3 (Invariant Selector Cache)**: Validate LRU caching strategy and Levenshtein distance thresholds for self-healing locators.
- [ ] **Task 2.4 (Input Synthesizer)**: Confirm bypass methods for anti-bot detection in Arc stealth profiles.

---

## Gate 3: Phase 3 Review (The Cortex Engine & Cascading)
- [ ] **Task 3.1 (Stuck Monitor & ModernBERT)**: Confirm 64-bit SimHash state fingerprinting and 2-step hysteresis dampening parameters.
- [ ] **Task 3.2 (Milestone Monitor)**: Review cosine progress alignment and maximum stall step count ($N \ge 3$).
- [ ] **Task 3.3 (Escalation Dispatcher)**: Confirm payload specification (pruned tree + trajectory history + SoM annotations) and verify that the target escalation budget ($\le 18\%$ of total steps) is feasible.
- [ ] **Task 3.4 (Plan Decompiler)**: Review conversion logic from frontier model JSON recovery plans into local Reflex execution queues.

---

## Gate 4: Phase 4 Review (Evaluation & Benchmarks)
- [ ] **OSWorld Testbed**: Verify deployment plan across 369 desktop tasks and confirm target success rate ($\ge 32.0\%$).
- [ ] **WebArena-Verified Harness**: Confirm target completion rate ($\ge 38.5\%$) and execution wall-clock time reduction ($\ge 65\%$).
- [ ] **Step Efficiency Ratio (SER)**: Review formula and verify the target threshold ($\text{SER} \le 1.30$) relative to human gold paths.

---

## Sign-Off Log

| Reviewer Name | Role | Decision | Date | Comments |
| :--- | :--- | :--- | :--- | :--- |
| *Pending* | Orchestrator | Awaiting Review | - | Ready for initial inspection. |
| *Pending* | Systems Architect | Awaiting Review | - | Research foundations validated. |
