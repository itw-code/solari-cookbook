# instructions_06.md

## Phase 5 Review Result

Status: PASS

Approved Phase 5 components:
- `src/arc_cua/cloud/arc_driver.py`
- `src/arc_cua/cortex/real_llm_cortex.py`
- `src/arc_cua/eval/live_orchestrator.py`
- `scripts/report_production.py`
- `tests/test_phase5_production.py`

Review notes:
1. The base architecture (Phases 1 through 5) is 100% complete.
2. 143 tests pass with zero regressions.
3. The system gracefully handles missing live infrastructure (API keys, KVM, Docker) by falling back to deterministic mocks.
4. Phase 6 must now build the full-scale execution pipelines, model training scripts, and final reporting generators for live production deployment.

---

## Phase 6 Mission

Execute Full-Scale Benchmarking, Monitor Training, and Final Reporting.

Work in:
```text
arc-hybrid-cua/
```

Phase 6 transitions the project from "offline architecture" to "live research execution". 

You will build:
1. Full benchmark runners for the complete WebArena (812 tasks) and OSWorld (369 tasks) datasets.
2. The actual ModernBERT training pipeline using the trajectory data collected in Phases 3B and 4.
3. A final research report and pitch-deck generator that compiles all live metrics into a polished markdown document.

---

## Strict Rules

1. Default mode must remain offline/mock if live infrastructure (Arc API, KVM, LLM keys) is missing.
2. Do not modify Phases 1-5 core logic.
3. Training scripts must gracefully skip and log `TRAINING_SKIPPED` if PyTorch/Transformers/GPU are unavailable.
4. Full benchmark runners must support chunking/resuming (e.g., running 50 tasks at a time) so they don't crash on long runs.
5. Keep final implementation inside `arc-hybrid-cua/`.

---

## Task 1: Full WebArena Benchmark Runner

Create:
```text
scripts/run_full_webarena.py
```

Purpose:
Execute the entire WebArena-Verified dataset (812 tasks) using the `WebArenaRunner` built in Phase 4B.

Requirements:
1. Ingest the full WebArena task list (from a local JSON/JSONL file or mock generator).
2. Support chunking: `--chunk-size 50` and `--chunk-index 0`.
3. Support resuming: Read an existing `webarena_results.jsonl` and skip already completed task IDs.
4. Log real-time progress to stdout.
5. If live Docker/KVM is missing, execute the first 20 tasks in mock mode to prove the pipeline works, then log `FULL_RUN_REQUIRES_LIVE_INFRA`.

---

## Task 2: Full OSWorld Benchmark Runner

Create:
```text
scripts/run_full_osworld.py
```

Purpose:
Execute the entire OSWorld dataset (369 tasks) using the `OSWorldRunner` built in Phase 4C.

Requirements:
1. Ingest the full OSWorld task list.
2. Support chunking and resuming (same as Task 1).
3. Capture AT-SPI state and file-system diffs for every task.
4. If live X11/KVM is missing, execute the first 20 tasks in mock mode, then log `FULL_RUN_REQUIRES_LIVE_INFRA`.

---

## Task 3: ModernBERT Monitor Training Pipeline

Create:
```text
scripts/train_monitors_full.py
src/arc_cua/monitors/training_pipeline.py
```

Purpose:
Train the `ModernBERT-base` (or `DeBERTa-v3-small`) Stuck and Milestone monitors using the real trajectory data collected during Phases 3B, 4A, 4B, and 4C.

Requirements:
1. Ingest all `trajectory_logs.jsonl` files from the `artifacts/` directory.
2. Use the auto-labeler from Phase 3B to generate training labels.
3. Implement a standard PyTorch/HuggingFace training loop with:
   - 80/20 train/test split.
   - Class balancing (stuck/milestone events are rare).
   - Early stopping based on F1 score.
4. Save the trained model weights to `artifacts/phase6/models/`.
5. **CRITICAL:** If `torch` or `transformers` are not installed, or if no GPU is available, immediately write `artifacts/phase6/models/TRAINING_SKIPPED.md` and exit gracefully without crashing.

---

## Task 4: Final Research & Pitch Report Generator

Create:
```text
scripts/generate_final_report.py
```

Purpose:
Compile all benchmark results, cost models, and latency metrics into a final, polished Markdown document suitable for a research paper or investor pitch.

Requirements:
1. Read `artifacts/production/final_scorecard.json`, `webarena_results.jsonl`, and `osworld_results.jsonl`.
2. Generate `artifacts/phase6/FINAL_RESEARCH_REPORT.md` with the following sections:
   - **Executive Summary:** The "ARC" value proposition (99% cost reduction, sub-10ms reflex).
   - **Architecture Overview:** Brief summary of Reflex + Cortex cascading.
   - **Benchmark Results:** Tables comparing Arc Hybrid vs. Frontier LLM baselines on WebArena and OSWorld.
   - **Cost & Latency Analysis:** Graphs/tables showing the Pareto frontier of cost vs. success rate.
   - **Monitor Efficacy:** How many escalations were prevented by the local monitors.
   - **Conclusion & Future Work.**
3. If live data is missing, populate the report with the theoretical targets and mock data, clearly marking it as `PROJECTED_BASED_ON_MOCK_EXECUTION`.

---

## Task 5: Final Tests & Documentation

Create:
```text
tests/test_phase6_full_scale.py
```

Required tests:
1. Full WebArena runner correctly chunks and resumes.
2. Full OSWorld runner correctly chunks and resumes.
3. Training pipeline gracefully handles missing PyTorch/Transformers.
4. Final report generator successfully compiles the markdown document.
5. Full 143+ test suite still passes (no regressions).

Update `ARCHITECTURE.md` and `IMPLEMENTATION_PLAN.md` to mark Phase 6 as the final deployment and reporting stage.

---

## Definition of Done

Phase 6 is complete only if:
1. Full WebArena runner exists and supports chunking/resuming.
2. Full OSWorld runner exists and supports chunking/resuming.
3. ModernBERT training pipeline exists and handles missing dependencies safely.
4. Final research report generator exists and produces a polished markdown file.
5. All tests pass.
6. Documentation is updated.

---

## Required Final Output

After completing Phase 6, create:
```text
checkpoint_06.md
```

Use this format:

```markdown
# checkpoint_06.md

## 1. Phase 6 Status

- [ ] Full WebArena runner
- [ ] Full OSWorld runner
- [ ] ModernBERT training pipeline
- [ ] Final research report generator
- [ ] Final tests
- [ ] Documentation

## 2. Files Added/Updated

List files.

## 3. Live vs Offline Execution

Clearly state what was executed live vs what was mocked/skipped due to host limitations.

## 4. Test Results

Include pass/fail count (must include all previous baseline tests).

## 5. Final Report Status

Confirm that `artifacts/phase6/FINAL_RESEARCH_REPORT.md` was generated successfully.

## 6. Project Completion Summary

Write a final 1-paragraph summary declaring the ARC project fully engineered, tested, and ready for live cloud deployment.

## 7. Remaining Blockers

List any final blockers (e.g., waiting for live cloud credentials to execute the full 812+369 task runs).
```

---

## Stop Condition

Stop after producing:
```text
checkpoint_06.md
```
