# instructions_04a.md

## Phase 3B Review Result

Status: PASS

Approved Phase 3B components:

- `src/arc_cua/datasets/trajectory_collector.py`
- `src/arc_cua/datasets/labeler.py`
- `scripts/label_phase3.py`
- `src/arc_cua/monitors/model_interface.py`
- `src/arc_cua/monitors/heuristic_adapter.py`
- `src/arc_cua/monitors/feature_builder.py`
- `src/arc_cua/monitors/transformer_adapter.py`
- `scripts/train_monitors.py`
- `src/arc_cua/monitors/semantic_progress.py`
- `src/arc_cua/cortex/http_cortex.py`
- `tests/test_phase3b_live.py`
- `scripts/smoke_phase3b.py`
- `scripts/benchmark_phase3b.py`
- `tests/test_phase3b_components.py`

Review notes:

1. Phase 3B is complete.
2. Live browser hybrid smoke test is approved.
3. Mock/dry-run Cortex policy is approved.
4. Trajectory and labeling pipeline is approved.
5. Learned monitor support is correctly optional.
6. Training skip is accepted because heavy dependencies are not required.
7. Real Cortex and Arc Cloud validation remain future work.
8. The project is ready for evaluation harness work.

---

## Phase 4 Mission

Build the Evaluation & Benchmarking layer.

Phase 4 is split into:

```text
Phase 4A: local evaluation harness, synthetic task suite, scorecard, report generator.
Phase 4B: WebArena subset integration.
Phase 4C: OSWorld/desktop subset integration.
```

This instruction file is only for Phase 4A.

Do not download or run full WebArena yet.

Do not download or run full OSWorld yet.

Do not require Arc Cloud credentials.

Do not require real Cortex credentials.

---

## Phase 4A Scope

Allowed:

- local evaluation harness
- local synthetic task suite
- local HTML fixture site
- eval runner
- success assertion engine
- cost ledger
- scorecard builder
- report generator
- baseline comparison between Reflex-only and Hybrid mode
- tests
- documentation

Not allowed:

- full WebArena harness
- full OSWorld harness
- external LLM calls
- real Cortex calls
- model training
- Arc Cloud dependency
- private Playwright internals

---

## Strict Rules

1. Default mode must remain offline/mock.
2. Live browser tests must gracefully skip if Chromium is unavailable.
3. Do not modify Phase 1, Phase 2, or Phase 3 unless a bug blocks Phase 4A.
4. Use existing modules:
   - `HybridRunner`
   - `ReflexRunner`
   - `TelemetryCollector`
   - `TrajectoryCollector`
   - `StateVerifier`
   - `EscalationController`
   - `MockCortexClient`
5. Keep final implementation inside `arc-hybrid-cua/`.
6. Use `coldstart/arc-cookbook/` only as design reference.

---

## Cross-Repo Design References

Use these only as design references:

```text
coldstart/arc-cookbook/src/scorecard/build.ts
coldstart/arc-cookbook/src/scorecard/cost.ts
coldstart/arc-cookbook/src/scorecard/curve.ts
coldstart/arc-cookbook/src/scorecard/isolated.ts
coldstart/arc-cookbook/src/verify/checks.ts
coldstart/arc-cookbook/src/verify/verifier.ts
coldstart/arc-cookbook/src/qa-framework/assertions.ts
coldstart/arc-cookbook/reports/step-06-scorecard.md
coldstart/arc-cookbook/reports/step-06b-isolated-scorecard.md
```

Rules:

1. Translate TypeScript patterns into Python.
2. Do not import TypeScript code at runtime.
3. Document reused patterns in checkpoint.

---

## Task 1: Evaluation Schemas

Create:

```text
src/arc_cua/eval/__init__.py
src/arc_cua/eval/schemas.py
```

Add:

```python
EvalTask
EvalAssertion
EvalResult
EvalRunSummary
ScorecardSummary
CostRecord
```

Minimum `EvalTask`:

```yaml
task_id:
name:
category:
description:
start_url:
action_steps:
expected_assertions:
max_steps:
timeout_ms:
tags:
```

Minimum `EvalAssertion`:

```yaml
type: url|visible_text|element_state|state_hash_changed|page_title|input_value
selector:
expected:
```

Minimum `EvalResult`:

```yaml
task_id:
success:
total_steps:
reflex_steps:
escalations:
recoveries_attempted:
recoveries_succeeded:
milestones_detected:
aborted:
abort_reason:
duration_ms:
cost_usd:
telemetry_summary:
assertion_results:
```

---

## Task 2: Local Fixture Site

Create:

```text
tests/fixtures/eval_site.html
```

The fixture page must support these task categories:

1. Simple form task.
2. Navigation task.
3. Select dropdown task.
4. Scroll-to-reveal task.
5. Input validation task.
6. No-op stuck task.
7. Recovery task.
8. Milestone progression task.

Requirements:

1. Must be fully local.
2. Must not require network.
3. Must expose stable test IDs.
4. Must expose at least one intentionally broken/no-op element.
5. Must expose one recovery element that changes visible state.
6. Must expose one hidden/unavailable element for readiness guard testing.

---

## Task 3: Synthetic Task Suite

Create:

```text
src/arc_cua/eval/tasks_local.py
```

Define at least 12 local tasks.

Categories:

```text
healthy_form
healthy_navigation
healthy_dropdown
healthy_scroll
healthy_input_validation
stuck_noop
stuck_missing_locator
recovery_after_noop
recovery_after_timeout
milestone_multi_step
readiness_blocked_element
assertion_failure
```

Requirements:

1. Each task must use typed `ActionStep` objects.
2. Each task must include expected assertions.
3. At least 3 tasks must force escalation/recovery.
4. At least 2 tasks must intentionally fail if no recovery occurs.
5. At least 2 tasks must validate milestone detection.
6. All tasks must run against local fixture site.

---

## Task 4: Success Assertion Engine

Create:

```text
src/arc_cua/eval/assertions.py
```

Implement assertion checks:

```python
check_url
check_visible_text
check_element_state
check_input_value
check_page_title
check_state_hash_changed
```

Requirements:

1. Must use public Playwright APIs only.
2. Must return structured assertion results.
3. Must support timeout.
4. Must not throw unhandled exceptions for failed assertions.
5. Must integrate with `StateVerifier` where useful.

---

## Task 5: Eval Runner

Create:

```text
src/arc_cua/eval/runner.py
```

Purpose:

Run `EvalTask` objects through the existing execution stack.

Modes:

```text
reflex_only
hybrid
```

Flow:

```text
load fixture/start URL
    -> convert EvalTask.action_steps
    -> run ReflexRunner or HybridRunner
    -> evaluate assertions
    -> collect telemetry
    -> collect trajectory logs
    -> produce EvalResult
```

Requirements:

1. Must support headless Chromium.
2. Must support mock mode if browser unavailable.
3. Must support per-task timeout.
4. Must capture duration, steps, escalations, recoveries, and assertions.
5. Must not call real Cortex.
6. Must use Mock Cortex in hybrid mode.

---

## Task 6: Cost Ledger

Create:

```text
src/arc_cua/eval/cost.py
```

Purpose:

Track estimated cost per task.

For Phase 4A:

```yaml
mock_cortex_cost_usd: 0.0
local_reflex_cost_usd: 0.0
browser_runtime_ms:
estimated_infra_cost_usd:
total_cost_usd:
```

Requirements:

1. Must support future real Cortex token pricing.
2. Must support future Arc VM/browser time pricing.
3. Must not require real credentials.
4. Must record cost in `EvalResult`.

---

## Task 7: Scorecard Builder

Create:

```text
src/arc_cua/eval/scorecard.py
```

Purpose:

Aggregate eval results into a scorecard.

Metrics:

```yaml
total_tasks:
successful_tasks:
success_rate:
avg_duration_ms:
p50_duration_ms:
p95_duration_ms:
p99_duration_ms:
total_steps:
avg_steps_per_task:
reflex_step_share:
escalation_rate:
recovery_attempt_rate:
recovery_success_rate:
milestone_detection_count:
abort_rate:
total_cost_usd:
avg_cost_per_task_usd:
assertion_failure_count:
```

Also compare:

```text
reflex_only vs hybrid
```

Requirements:

1. Must generate JSON scorecard.
2. Must generate Markdown scorecard.
3. Must include p50/p95/p99 where relevant.
4. Must include real vs mocked mode.

---

## Task 8: Report Generator

Create:

```text
scripts/report_phase4a.py
```

Purpose:

Run local task suite and produce artifacts.

Output directory:

```text
artifacts/phase4a/
```

Outputs:

```text
report.md
scorecard.json
results.jsonl
trajectory_logs.jsonl
summary.json
```

Minimum `report.md` sections:

```markdown
# Phase 4A Local Evaluation Report

## Run Metadata

## Success Rate

## Latency

## Escalation Behavior

## Recovery Behavior

## Cost

## Reflex-Only vs Hybrid

## Failed Tasks

## Notes
```

---

## Task 9: Tests

Create:

```text
tests/test_phase4a_eval.py
```

Required tests:

1. Eval schemas validate.
2. Local task suite contains at least 12 tasks.
3. Local task suite has required categories.
4. Assertion engine detects success.
5. Assertion engine detects failure.
6. Eval runner runs in mock mode.
7. Eval runner produces `EvalResult`.
8. Cost ledger produces cost record.
9. Scorecard builder aggregates results.
10. Report generator writes artifacts.
11. Hybrid mode recovers at least one forced stuck task.
12. Reflex-only mode fails at least one forced stuck task.
13. Public Playwright API compliance remains enforced.
14. No external network calls occur.

If live browser is available, run one live local eval smoke task.

If unavailable, mark:

```text
LIVE_BROWSER_EVAL_SMOKE_SKIPPED
```

---

## Task 10: Benchmark Targets

Measure:

```yaml
eval_runner_overhead_ms:
assertion_evaluation_latency_ms:
scorecard_build_latency_ms:
task_success_rate:
hybrid_recovery_success_rate:
escalation_rate:
average_task_duration_ms:
```

Targets:

```yaml
eval_runner_overhead_p95: "<50ms"
assertion_evaluation_p95: "<250ms"
scorecard_build_p95: "<100ms"
local_task_success_rate_reflex_only: ">=70%"
local_task_success_rate_hybrid: ">=90%"
hybrid_recovery_success_rate: ">=90%"
```

If target is not met, report it and explain why.

---

## Task 11: Documentation

Update:

```text
ARCHITECTURE.md
IMPLEMENTATION_PLAN.md
```

Add:

1. Phase 4A evaluation harness design.
2. Local task suite categories.
3. Assertion engine design.
4. Scorecard metrics.
5. Cost ledger design.
6. Reflex-only vs hybrid comparison policy.
7. Future WebArena/OSWorld integration points.

---

## Definition of Done

Phase 4A is complete only if:

1. Evaluation schemas exist.
2. Local fixture site exists.
3. Local task suite exists.
4. Assertion engine exists.
5. Eval runner exists.
6. Cost ledger exists.
7. Scorecard builder exists.
8. Report generator exists.
9. Tests pass.
10. Hybrid mode outperforms or equals Reflex-only on local suite.
11. Hybrid mode recovers forced stuck tasks.
12. Artifacts are generated.
13. No external network calls are required.
14. Documentation is updated.

---

## Required Final Output

After completing Phase 4A, create:

```text
checkpoint_04a.md
```

Use this format:

```markdown
# checkpoint_04a.md

## 1. Phase 4A Status

- [ ] Evaluation schemas
- [ ] Local fixture site
- [ ] Local task suite
- [ ] Assertion engine
- [ ] Eval runner
- [ ] Cost ledger
- [ ] Scorecard builder
- [ ] Report generator
- [ ] Tests
- [ ] Benchmark results
- [ ] Documentation

## 2. Files Added/Updated

List files.

## 3. Real vs Mocked

Clearly say what was real and what was mocked.

## 4. Test Results

Include pass/fail count.

## 5. Local Evaluation Results

Include:

- reflex_only success rate
- hybrid success rate
- escalation rate
- recovery success rate
- average task duration
- cost estimate

## 6. Benchmark Results

Include p50/p95/p99 where relevant.

## 7. Cross-Repo Patterns Used

List reused patterns from coldstart/arc-cookbook.

## 8. Remaining Blockers

List blockers.
```

---

## Stop Condition

Do not start Phase 4B.

Do not start Phase 4C.

Do not integrate full WebArena.

Do not integrate full OSWorld.

Do not call real Cortex.

Do not train monitors.

Stop after producing:

```text
checkpoint_04a.md
```
