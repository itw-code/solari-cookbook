# Checkpoints Index

Timeline index of all development checkpoints across the ARC project lifecycle.

| File | Phase | Status | Test Count | Key Metric |
|---|---|---|:---:|---|
| `checkpoint_01.md` | Phase 1: MicroVM Foundation & Perception | COMPLETE | 9 | AT-SPI desktop serialization latency $p_{50} = 0.018\text{ ms}$, CDP AXTree extraction $p_{50} = 0.024\text{ ms}$ |
| `checkpoint_01b.md` | Phase 1 Remediation: Dynamic Config & Interfaces | COMPLETE | 25 | 100% pass rate; dynamic image/CDP providers; zero hardcoded paths; AST compliance checks |
| `checkpoint_02.md` | Phase 2: Deterministic Reflex Engine | COMPLETE | 52 | Reflex action step latency $p_{50} = 1.05\text{ ms}$; 64-bit SimHash state verification; public Playwright compliance |
| `checkpoint_03.md` | Phase 3A: Monitors & Mock Cortex | COMPLETE | 70 | Stuck monitor latency $p_{95} = 0.048\text{ ms}$; Recovery compiler validation $p_{95} = 0.009\text{ ms}$ |
| `checkpoint_03b.md` | Phase 3B: Dataset Pipeline & Pluggable Monitors | COMPLETE | 85 | Heuristic monitor $p_{95} = 0.0475\text{ ms}$; 16-feature vector $p_{95} = 0.041\text{ ms}$; live Chromium hybrid test passed |
| `checkpoint_04a.md` | Phase 4A: Local Evaluation Harness | COMPLETE | 100 | Hybrid vs Reflex success rate 92.3% vs 46.2% (+46.2%); assertion latency $p_{95} = 0.005\text{ ms}$ |
| `checkpoint_04b.md` | Phase 4B: WebArena Integration | COMPLETE | 112 | 100% mock task pass rate (12/12); dual-layer SQLite diffing; URL/DOM/SQL assertion engines |
| `checkpoint_04c.md` | Phase 4C: OSWorld Integration | COMPLETE | 125 | 100% mock task pass rate (12/12); AT-SPI state matching; POSIX filesystem and terminal assertions |
| `checkpoint_05.md` | Phase 5: Production Deployment & Orchestration | COMPLETE | 143 | 100% production task pass rate (10/10); SER 0.80; average step latency 2.31 ms; 99.69% cost reduction |
| `checkpoint_06.md` | Phase 6: Full-Scale Benchmarking & Report | COMPLETE | 152 | Final whitepaper generated; 99.69% cost reduction ($0.0015/task); 99.90% latency reduction; 152/152 tests passed |
| `checkpoint_07.md` | Phase 7: Codebase Consolidation & HTML Showcase | COMPLETE | 154 | Codebase consolidated into `docs/`; `showcase.html` interactive demo created; 154/154 tests pass |
| `checkpoint_08.md` | Phase 8: Audit Remediation — Reflex & Perception Layer | COMPLETE | 180 | 5/5 benchmark-report §F defects remediated; 19/23 new regression tests fail pre-fix; sanitizer p50 0.553 ms (target ≤ 0.8 ms); 178 passing, 2 pre-existing timing flakes |
