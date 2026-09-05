# ColdStart — Master Audit Log

This document records the master audit trail for the ColdStart engineering lifecycle, linking every verification step to its corresponding report in [`reports/`](reports/) and evidence artifacts in [`artifacts/`](artifacts/).

---

## 📋 Master Step Audit Summary

| Step | Phase & Title | Mode | Status | Key Deliverable | Evidence / Report Link |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **00** | Environment Setup & Solari SDK Probe | LIVE | **PASS** | MicroVM lifecycle verification | [`reports/step-00-env.md`](reports/step-00-env.md) |
| **01** | System Design & Architecture Spec | MOCK | **PASS** | [`DESIGN.md`](DESIGN.md) | [`reports/step-01-design.md`](reports/step-01-design.md) |
| **02** | Seeded Variant Factory & 5 Perturbation Axes | MOCK | **PASS** | [`src/generate-variants/`](src/generate-variants/) | [`reports/step-02-variant-factory.md`](reports/step-02-variant-factory.md) |
| **03** | Sandbox-to-Browser Fast-Fork Orchestration | LIVE | **PASS** | [`src/solari/driver.ts`](src/solari/driver.ts) | [`reports/step-03-orchestration.md`](reports/step-03-orchestration.md) |
| **04** | Vision-First Agent Loop (Pixels In, Actions Out) | LIVE | **PASS** | [`src/agent/loop.ts`](src/agent/loop.ts) | [`reports/step-04-agent-loop.md`](reports/step-04-agent-loop.md) |
| **04b** | Model Calibration & Repeatability Benchmarking | LIVE | **PASS** | 3/3 Repeatability on Luna | [`reports/step-04b-repeatability.md`](reports/step-04b-repeatability.md) |
| **05** | Fail-Closed Database Verifier (C1–C7) | MOCK / LIVE | **PASS** | [`src/verify/verifier.ts`](src/verify/verifier.ts) | [`reports/step-05-verifier.md`](reports/step-05-verifier.md) |
| **06** | Mixed-Axis Scorecard Benchmark | LIVE | **PASS** | Confounded run dataset | [`reports/step-06-scorecard.md`](reports/step-06-scorecard.md) |
| **06b** | Axis-Isolated Causal Benchmark Evaluation | LIVE | **PASS** | [`artifacts/scorecard.json`](artifacts/scorecard.json) | [`reports/step-06b-isolated-scorecard.md`](reports/step-06b-isolated-scorecard.md) |
| **07** | Submission Packaging & Showcase Media | MOCK | **PASS** | [`artifacts/showcase.gif`](artifacts/showcase.gif) | [`reports/step-07-packaging.md`](reports/step-07-packaging.md) |
| **CI** | Continuous Integration & GitHub Pages | LIVE | **PASS** | [`.github/workflows/`](.github/workflows/) | [CI Workflow](https://github.com/itw-code/solari-cookbook/actions) |

---

## 🔒 Security & Cleanliness Attestation

- **Zero Secrets**: All API tokens (`SOLARI_API_KEY`, `LLM_API_KEY`) are dynamically injected via environment variables and checked with regex scanners in CI.
- **Zero Resource Leaks**: All sandbox sessions are wrapped in strict `try ... finally` shutdown hooks, guaranteeing `0` orphaned microVMs.

## Grounding disclosure

The model receives screenshots and emits pixel coordinates. The harness then performs a
small `page.evaluate` query to snap an imprecise click to the nearest visible interactive
element. No DOM text, selectors, accessibility tree, or element boxes are returned to the
model. This is **vision plus harness grounding**, not a pure no-DOM implementation.
