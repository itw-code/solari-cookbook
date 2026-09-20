# Phase 4A Local Evaluation Report

> Generated on: `2026-09-20 21:55:23`  
> Benchmark Engine: `ARC Eval Harness v1.0`

## Run Metadata

| Property | Value |
| :--- | :--- |
| **Platform** | `Windows-11-10.0.26200-SP0` |
| **Python Version** | `3.12.10` |
| **Execution Engine** | `Headless Chromium (Real Browser)` |
| **Offline / Mock Mode** | `False` |
| **Total Tasks Evaluated** | `13` |
| **Cortex Client** | `EvalMockCortexClient (Zero Network Calls)` |
| **Fixture Site** | `tests/fixtures/eval_site.html` |

## Success Rate

- **Hybrid Mode:** `12/13` tasks passed (**92.3%**)
- **Reflex-Only Mode:** `6/13` tasks passed (**46.2%**)
- **Success Rate Delta:** **+46.2%**

Hybrid mode meets or exceeds the local benchmark target (>=90% success on solvable tasks).

## Latency

| Mode | Avg Duration | p50 Duration | p95 Duration | p99 Duration |
| :--- | :--- | :--- | :--- | :--- |
| **Reflex-Only** | 1138.0 ms | 867.9 ms | 4029.2 ms | 4029.2 ms |
| **Hybrid** | 1656.4 ms | 1205.3 ms | 6661.7 ms | 6661.7 ms |

## Escalation Behavior

- **Hybrid Escalation Rate:** `46.2%` (6 tasks triggered escalation)
- **Reflex Escalation Rate:** `46.2%` (escalations halt execution in reflex mode)
- **Escalation Signals Detected:**
  - `STATE_NOT_CHANGED` / Stuck loop on inert buttons
  - `LOCATOR_NOT_FOUND` on missing selectors
  - `READINESS_TIMEOUT` on hidden/zero-pixel elements

## Recovery Behavior

- **Recovery Attempts in Hybrid:** `6`
- **Recovery Successes in Hybrid:** `4`
- **Hybrid Recovery Success Rate:** **66.7%**
- **Reflex Recovery Success Rate:** `0.0%` (Reflex engine cannot self-recover)

Hybrid mode successfully demonstrated closed-loop reasoning recovery from forced stuck states.

## Cost

| Component | Reflex-Only | Hybrid |
| :--- | :--- | :--- |
| **Local Reflex Actions** | $0.000074 | $0.000106 |
| **Mock Cortex Calls** | $0.000000 | $0.000000 |
| **Estimated Compute Cost** | $0.000074 | $0.000106 |
| **Average Cost / Task** | $0.000006 | $0.000008 |

## Reflex-Only vs Hybrid

| Metric | Reflex-Only | Hybrid | Delta / Note |
| :--- | :--- | :--- | :--- |
| **Task Success Rate** | 46.2% | 92.3% | **+46.2%** |
| **Recovery Success Rate** | 0.0% | 66.7% | **+66.7%** |
| **Abort Rate** | 46.2% | 0.0% | Lower in Hybrid |
| **Milestones Detected** | 0 | 8 | Tracked by MilestoneMonitor |
| **Reflex Step Share** | 100.0% | 65.1% | Bulk of routine steps run locally |

## Failed Tasks

| Task ID | Category | Aborted | Abort Reason | Assertion Failures |
| :--- | :--- | :--- | :--- | :--- |
| `task_assertion_failure` | `assertion_failure` | `False` | `None` | `Intentionally mismatched expected text to prove assertion failure detection` |

*Note: `task_assertion_failure` is an intentional negative test confirming that unexpected DOM states fail the assertion engine without crashing.*

## Notes

1. **Zero External Network Calls:** All evaluations ran strictly offline against `tests/fixtures/eval_site.html`.
2. **Public Playwright API Compliance:** Full compliance preserved; no private internals accessed.
3. **Zero-Pixel Trap Defense:** Element states and visibility verified with positive bounding boxes and opacity checks adapted from `coldstart/arc-cookbook`.
4. **Trajectory Collection:** Successfully recorded per-step transitions and SimHash state deltas to `trajectory_logs.jsonl`.
5. **Readiness for Phase 4B:** Local baseline, scorecard generator, and assertion engine are validated and ready for WebArena subset integration.
