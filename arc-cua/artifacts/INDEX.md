# Artifacts Index

This index catalogs all empirical evaluation artifacts, benchmark outputs, and research deliverables generated across the development phases of the ARC project.

## Directory Structure

```text
artifacts/
├── phase3b/
│   ├── benchmark_phase3b.json
│   ├── labeled/
│   │   ├── milestone.jsonl
│   │   ├── stuck.jsonl
│   │   └── summary.json
│   └── models/
│       └── TRAINING_SKIPPED.md
├── phase4a/
│   ├── report.md
│   ├── results.jsonl
│   ├── scorecard.json
│   ├── summary.json
│   └── trajectory_logs.jsonl
├── phase6/
│   ├── FINAL_RESEARCH_REPORT.md
│   └── models/
│       └── TRAINING_SKIPPED.md
└── production/
    ├── final_scorecard.json
    ├── live_trajectory_logs.jsonl
    └── production_report.md
```

---

## Artifact Catalog

| Relative Path | Producing Phase | Format | Purpose & Description |
|---|---|---|---|
| `artifacts/phase3b/benchmark_phase3b.json` | Phase 3B | JSON | Benchmark latency percentiles (p50, p90, p95, p99) and throughput distributions for Reflex perception, state verifier, and monitors. |
| `artifacts/phase3b/labeled/milestone.jsonl` | Phase 3B | JSONL | Labeled trajectory windows used for training and evaluating milestone progress detection. |
| `artifacts/phase3b/labeled/stuck.jsonl` | Phase 3B | JSONL | Labeled trajectory windows capturing zero-delta UI loops and mechanical stalls for stuck-state classification. |
| `artifacts/phase3b/labeled/summary.json` | Phase 3B | JSON | Summary statistics of positive/negative sample distributions across stuck and milestone datasets. |
| `artifacts/phase3b/models/TRAINING_SKIPPED.md` | Phase 3B | Markdown | Documentation explaining fallback to heuristic adapters on hosts without CUDA GPU acceleration. |
| `artifacts/phase4a/report.md` | Phase 4A | Markdown | Detailed evaluation report summarizing local task execution, assertion passes, and efficiency metrics. |
| `artifacts/phase4a/results.jsonl` | Phase 4A | JSONL | Per-task execution results including task identifiers, success flags, error traces, and duration. |
| `artifacts/phase4a/scorecard.json` | Phase 4A | JSON | Scorecard serialization containing overall and domain-specific success rates, Step Efficiency Ratio (SER), and cost deltas. |
| `artifacts/phase4a/summary.json` | Phase 4A | JSON | Complete execution run summary with environment metadata, duration breakdown, and monitor triggers. |
| `artifacts/phase4a/trajectory_logs.jsonl` | Phase 4A | JSONL | Granular step-by-step action trajectories, DOM/image state hashes, and monitor decisions during evaluation. |
| `artifacts/phase6/FINAL_RESEARCH_REPORT.md` | Phase 6 | Markdown | Comprehensive final technical research report and whitepaper covering architecture, WebArena/OSWorld comparisons, and cost/latency Pareto frontiers. |
| `artifacts/phase6/models/TRAINING_SKIPPED.md` | Phase 6 | Markdown | Phase 6 validation notice certifying heuristic monitor readiness and logging training fallback conditions. |
| `artifacts/production/final_scorecard.json` | Phase 5 | JSON | Production scorecard recording 100% success rate across 10 WebArena/OSWorld production tasks, 2.31ms average step latency, and 99.69% cost reduction. |
| `artifacts/production/live_trajectory_logs.jsonl` | Phase 5 | JSONL | Execution traces and step-by-step telemetry logs from live production evaluation tasks. |
| `artifacts/production/production_report.md` | Phase 5 | Markdown | Phase 5 production readiness report covering environment diagnostics (Docker/KVM), success rates, and cost accounting. |
