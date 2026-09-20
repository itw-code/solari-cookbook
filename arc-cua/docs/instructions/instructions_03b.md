# instructions_03b.md

## Phase 3A Review Result

Status: PASS

Approved Phase 3A components:

- `src/arc_cua/monitors/stuck_monitor.py`
- `src/arc_cua/monitors/milestone_monitor.py`
- `src/arc_cua/monitors/escalation_controller.py`
- `src/arc_cua/cortex/cortex_interface.py`
- `src/arc_cua/cortex/mock_cortex.py`
- `src/arc_cua/cortex/recovery_compiler.py`
- `src/arc_cua/hybrid_runner.py`
- `src/arc_cua/schemas.py`
- `src/arc_cua/telemetry.py`
- `tests/test_phase3_monitors.py`
- `scripts/benchmark_phase3.py`

Review notes:

1. Deterministic monitors are approved.
2. Escalation controller policy is approved.
3. Mock Cortex is approved.
4. Recovery compiler validation is approved.
5. Hybrid runner orchestration is approved.
6. Telemetry extension is approved.
7. Phase 3A is mostly mock-based for browser and Cortex.
8. Phase 3B must add live-browser validation and a path toward learned monitors.

---

## Phase 3B Mission

Upgrade Phase 3 from deterministic mock escalation to a production-ready escalation layer.

Work in:

```text
arc-hybrid-cua/
```

Phase 3B includes:

- trajectory data collection
- labeling pipeline
- monitor model adapter
- optional learnable monitor support
- optional semantic milestone estimator
- real Cortex adapter behind environment flags
- live browser hybrid smoke test
- extended benchmarks
- documentation

Do not build Phase 4 full benchmark harness yet.

Do not replace the existing deterministic monitors.

Keep deterministic monitors as the default fallback.

---

## Strict Rules

1. Default mode must remain offline/mock.
2. Do not call external APIs unless explicitly enabled.
3. Do not log secrets or API keys.
4. Do not use private Playwright internals.
5. Do not create Python-to-TypeScript runtime dependencies.
6. Keep final implementation inside `arc-hybrid-cua/`.
7. Heavy model training must be optional.
8. Tests must pass without requiring GPU, Torch, Transformers, or network access.

---

## Input Dependencies From Phase 3A

Use these existing modules:

```text
src/arc_cua/hybrid_runner.py
src/arc_cua/monitors/stuck_monitor.py
src/arc_cua/monitors/milestone_monitor.py
src/arc_cua/monitors/escalation_controller.py
src/arc_cua/cortex/cortex_interface.py
src/arc_cua/cortex/mock_cortex.py
src/arc_cua/cortex/recovery_compiler.py
src/arc_cua/schemas.py
src/arc_cua/telemetry.py
```

Do not rewrite Phase 3A unless a bug blocks Phase 3B.

---

## Cross-Repo Design References

Use these only as design references:

```text
coldstart/arc-cookbook/src/config/model-router.ts
coldstart/arc-cookbook/src/agent/loop.ts
coldstart/arc-cookbook/src/agent/model.ts
coldstart/arc-cookbook/src/agent/trace.ts
coldstart/arc-cookbook/src/scorecard/cost.ts
coldstart/arc-cookbook/src/qa-framework/heuristics.ts
```

Rules:

1. Translate TypeScript patterns into Python.
2. Do not import TypeScript code at runtime.
3. Document reused patterns in checkpoint.

---

## Task 1: Trajectory Dataset Collector

Update:

```text
src/arc_cua/telemetry.py
```

Create:

```text
src/arc_cua/datasets/__init__.py
src/arc_cua/datasets/trajectory_collector.py
```

Purpose:

Collect structured trajectory windows that can later be used to train or evaluate learned monitors.

Each trajectory record must include:

```yaml
run_id:
task_id:
step_id:
timestamp:
action_type:
target_locator:
locator_strategy:
readiness_passed:
execution_success:
state_hash_before:
state_hash_after:
state_changed:
hamming_distance:
url_before:
url_after:
url_changed:
error_detected:
error_type:
monitor_stuck_score:
monitor_milestone_score:
escalation_decision:
recovery_attempted:
recovery_success:
integration_mode:
```

Also collect a sliding window of the last 5 steps.

Requirements:

1. Must export JSONL.
2. Must support redaction of secrets.
3. Must not store full credentials.
4. Must support optional output directory:

```text
artifacts/phase3b/trajectory_logs/
```

---

## Task 2: Auto-Labeling Pipeline

Create:

```text
scripts/label_phase3.py
src/arc_cua/datasets/labeler.py
```

Purpose:

Generate initial labels for stuck and milestone events without requiring an external model.

Labels:

```text
stuck: true|false
milestone: true|false
label_source: heuristic
```

Heuristic stuck labels:

1. Three consecutive no-state-change actions.
2. Same locator failed at least twice.
3. Cyclic state hash oscillation.
4. Repeated readiness timeout.
5. Repeated action exception.

Heuristic milestone labels:

1. Expected state change verified.
2. URL reached expected target.
3. Expected visible text appeared.
4. State changed and no error detected.

Output:

```text
artifacts/phase3b/labeled/
```

Include:

```text
stuck.jsonl
milestone.jsonl
summary.json
```

Minimum summary fields:

```yaml
total_windows:
stuck_positive:
stuck_negative:
milestone_positive:
milestone_negative:
label_source:
```

Requirements:

1. Must work offline.
2. Must be deterministic.
3. Must support future strong-model labeling behind a flag.
4. Must not call external model by default.

---

## Task 3: Monitor Model Interface

Create:

```text
src/arc_cua/monitors/model_interface.py
```

Define:

```python
class MonitorModel:
    def predict(self, window: MonitorWindow) -> MonitorPrediction:
        ...
```

Minimum prediction:

```python
MonitorPrediction:
    score: float
    reason: str
    evidence: dict
    model_name: str
```

Create adapters:

```text
src/arc_cua/monitors/heuristic_adapter.py
```

Implement:

```python
HeuristicStuckModelAdapter
HeuristicMilestoneModelAdapter
```

These adapters must wrap the existing deterministic monitors.

Requirements:

1. Existing deterministic monitors remain default.
2. Model adapter must be pluggable.
3. If no learned model is available, fallback to heuristic adapter.
4. No external dependencies required.

---

## Task 4: Feature Builder

Create:

```text
src/arc_cua/monitors/feature_builder.py
```

Purpose:

Convert telemetry windows into features for heuristic or learned monitors.

Features must include:

```yaml
window_size:
action_repeat_count:
locator_repeat_count:
locator_failure_count:
readiness_timeout_count:
action_exception_count:
consecutive_no_state_change:
hamming_distance_sequence:
state_hash_cycle_detected:
url_changed:
error_detected:
expected_state_change_verified:
visible_text_delta:
action_type_sequence:
target_role_sequence:
target_name_sequence:
```

Requirements:

1. Must be deterministic.
2. Must support JSON serialization.
3. Must run under 10 ms p95.
4. Must not require screenshots.

---

## Task 5: Optional Learned Monitor Support

Create:

```text
src/arc_cua/monitors/transformer_adapter.py
```

This module must be optional.

It should support a small local encoder model if installed:

```text
transformers
torch
```

Example model classes:

```text
ModernBERT-base
DeBERTa-v3-small
distilbert-base-uncased
```

Rules:

1. Do not make this required for tests.
2. If dependencies are missing, return:

```text
LEARNED_MONITOR_UNAVAILABLE
```

3. Do not download models by default unless explicitly enabled.
4. Must support loading local model path only.

Create optional training script:

```text
scripts/train_monitors.py
```

Requirements:

1. Must train only if dependencies are available.
2. Must use labeled dataset from Task 2.
3. Must support tiny smoke training mode.
4. Must output model artifacts to:

```text
artifacts/phase3b/models/
```

If training is skipped, write:

```text
artifacts/phase3b/models/TRAINING_SKIPPED.md
```

---

## Task 6: Semantic Milestone Estimator Upgrade

Update or extend:

```text
src/arc_cua/monitors/milestone_monitor.py
```

Create:

```text
src/arc_cua/monitors/semantic_progress.py
```

Implement pluggable estimator:

```python
class SemanticProgressEstimator:
    def estimate(self, goal: str, window: MonitorWindow) -> float:
        ...
```

Default implementation:

```python
HeuristicProgressEstimator
```

Optional implementation:

```python
EmbeddingProgressEstimator
```

Rules:

1. Default must be heuristic and offline.
2. Embedding estimator must be optional.
3. Do not call remote embedding API by default.
4. If local embedding model unavailable, fallback silently to heuristic.

---

## Task 7: Real Cortex Adapter

Create:

```text
src/arc_cua/cortex/http_cortex.py
```

Implement:

```python
class HttpCortexClient(CortexClient):
    def recover(self, payload: EscalationPayload) -> CortexResponse:
        ...
```

Configuration via environment:

```text
CORTEX_MODE=mock|real|dry_run
CORTEX_PROVIDER=
CORTEX_MODEL=
CORTEX_API_KEY=
CORTEX_ENDPOINT=
CORTEX_TIMEOUT_MS=
```

Rules:

1. Default must remain `mock`.
2. `dry_run` must build the request but not send it.
3. `real` must only activate if explicitly configured.
4. Must validate Cortex response using existing schemas.
5. Must pass response through `RecoveryCompiler`.
6. Must retry with bounded backoff.
7. Must timeout safely.
8. Must never log API key.
9. Must return structured failure if Cortex response is invalid.

Minimum request payload:

```yaml
task_goal:
escalation_reason:
recent_trajectory:
current_state_hash:
recent_state_hashes:
last_actions:
locator_attempts:
errors:
budget:
```

Minimum expected response:

```yaml
plan_id:
actions:
expected_outcome:
stop_condition:
confidence:
```

---

## Task 8: Live Browser Hybrid Smoke Test

Create:

```text
tests/test_phase3b_live.py
```

Or if better:

```text
scripts/smoke_phase3b.py
```

Purpose:

Validate HybridRunner against a real local Chromium browser if available.

Flow:

1. Open a simple local or public test page.
2. Extract state.
3. Execute one healthy typed action.
4. Force a stuck condition using a no-op repeated action.
5. Verify Stuck Monitor detects it.
6. Verify Escalation Controller triggers recovery.
7. Use Mock Cortex to generate recovery plan.
8. Verify recovery action executes.
9. Log telemetry.

Requirements:

1. Must not require Arc Cloud.
2. Must not require external LLM.
3. Must use Mock Cortex by default.
4. If live browser unavailable, mark:

```text
LIVE_BROWSER_SMOKE_SKIPPED
```

5. Do not fake the live test.

---

## Task 9: Benchmark Phase 3B

Measure:

```yaml
feature_builder_latency_ms:
heuristic_monitor_latency_ms:
learned_monitor_latency_ms_or_null:
trajectory_collector_latency_ms:
labeler_throughput_records_per_sec:
mock_cortex_recovery_latency_ms:
dry_run_cortex_payload_latency_ms:
live_browser_hybrid_step_latency_ms:
```

For each metric report:

```yaml
p50:
p95:
p99:
sample_size:
environment:
integration_mode: real|mock
```

Targets:

```yaml
feature_builder_p95: "<10ms"
heuristic_monitor_p95: "<10ms"
trajectory_collector_p95: "<10ms"
mock_cortex_recovery_p95: "<20ms"
dry_run_cortex_payload_p95: "<20ms"
live_browser_hybrid_step_p95: "<1000ms"
```

If target is not met, report it and explain why.

---

## Task 10: Documentation

Update:

```text
ARCHITECTURE.md
IMPLEMENTATION_PLAN.md
```

Add:

1. Phase 3B trajectory dataset design.
2. Labeling pipeline.
3. Monitor model adapter design.
4. Optional learned monitor policy.
5. Real Cortex adapter policy.
6. Live browser smoke test policy.
7. Default mock/offline behavior.

---

## Definition of Done

Phase 3B is complete only if:

1. Trajectory collector exists.
2. Auto-labeling pipeline exists.
3. Monitor model interface exists.
4. Heuristic adapters wrap existing monitors.
5. Feature builder exists.
6. Optional learned monitor support exists but is not required.
7. Optional training script exists but is not required.
8. Semantic milestone estimator is pluggable.
9. Real Cortex adapter exists.
10. Default mode remains mock/offline.
11. Live browser smoke test exists or is clearly skipped.
12. Tests pass without network access.
13. Tests pass without GPU/Torch/Transformers.
14. Documentation is updated.

---

## Required Final Output

After completing Phase 3B, create:

```text
checkpoint_03b.md
```

Use this format:

```markdown
# checkpoint_03b.md

## 1. Phase 3B Status

- [ ] Trajectory collector
- [ ] Auto-labeling pipeline
- [ ] Monitor model interface
- [ ] Heuristic adapters
- [ ] Feature builder
- [ ] Optional learned monitor support
- [ ] Optional training script
- [ ] Semantic milestone estimator
- [ ] Real Cortex adapter
- [ ] Live browser smoke test
- [ ] Benchmarks
- [ ] Documentation

## 2. Files Added/Updated

List files.

## 3. Real vs Mocked

Clearly say what was real and what was mocked.

## 4. Test Results

Include pass/fail count.

## 5. Benchmark Results

Include p50/p95/p99.

## 6. Live Browser Smoke Result

Explain result or why skipped.

## 7. Cortex Adapter Result

Explain mock/dry_run/real status.

## 8. Remaining Blockers

List blockers.
```

---

## Stop Condition

Do not start Phase 4.

Do not build full OSWorld/WebArena harness.

Do not require GPU/Torch/Transformers for normal tests.

Do not call real Cortex unless explicitly configured.

Stop after producing:

```text
checkpoint_03b.md
```
