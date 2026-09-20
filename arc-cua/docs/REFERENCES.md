# Research and Planning References

Research and planning references extracted from `IMPLEMENTATION_PLAN.md`;
publication status varies — some entries are established published papers with
stable links, others are planning-document citations reproduced here exactly as
written so reviewers can trace each design decision back to its stated source.

> **Scope note.** Benchmark headline numbers in this repository
> (`artifacts/phase6/FINAL_RESEARCH_REPORT.md`,
> `artifacts/production/final_scorecard.json`) are labeled
> `PROJECTED_BASED_ON_MOCK_EXECUTION` — deterministic harness verification on
> the host workstation, not live cloud runs. The entries below are the
> *planning references* used while writing the implementation plan.
>
> **Verification status.** `verified` = the linked arXiv / publisher page was
> checked and resolves. `† planning reference` = cited exactly as it appears in
> the planning documents, but no stable primary-source URL was independently
> re-verified in this pass — treat it as a design-planning note, not a
> confirmed bibliography entry.

## Benchmark environments (task definitions & baseline scores)

| # | Citation | Venue | Status | Used for |
|---|---|---|---|---|
| 1 | Zhou et al., *"WebArena: A Realistic Web Environment for Building Autonomous Agents"* — https://arxiv.org/abs/2307.13854 | ICLR 2024 | verified | WebArena task definitions; planning target of structured-AXTree token reduction vs raw HTML; WebArena-Verified success targets |
| 2 | Koh et al., *"VisualWebArena: Evaluating Multimodal Web Agents on Realistic Visually Grounded Tasks"* — https://arxiv.org/abs/2401.13649 | ACL 2024 | verified | WebArena-adjacent baseline band cited in planning; evaluation methodology |
| 3 | Xie et al., *"OSWorld: Benchmarking Multimodal Agents for Open-Ended Tasks in Real Computer Environments"* — https://arxiv.org/abs/2404.07972 | NeurIPS 2024 | verified | OSWorld 369-task suite; AT-SPI accessibility-state reading rationale; execution-based (not LLM-judged) grading; OSWorld-Human gold trajectories for Step Efficiency Ratio |
| 4 | Drouin et al., *"WorkArena: How Capable Are Web Agents at Solving Common Knowledge Work Tasks?"* — https://arxiv.org/abs/2405.06492 | 2024 † | † planning reference | Enterprise workflow harness concept; kernel/CDP-level input synthesis rationale; temporal-efficiency benchmarking practice |

## Agent architectures & web navigation methods

| # | Citation | Venue | Status | Used for |
|---|---|---|---|---|
| 5 | Deng et al., *"Mind2Web: Towards a Generalist Agent for the Web"* — https://arxiv.org/abs/2306.06070 | NeurIPS 2023 | verified | Pruned accessibility-tree representation target; self-healing structural locator caching rationale |
| 6 | Gur et al., *"A Real-World WebAgent with Planning, Long Context Support, and Tool Use"* | ICLR 2023 † | † planning reference | Multi-step plan → deterministic sub-goal decompilation (Cortex handback design) |
| 7 | He et al., *"WebVoyager: Building an End-to-End Web Agent with Large Multimodal Models"* — https://arxiv.org/abs/2401.13919 | 2024 | verified | Locator-cache rationale for deterministic multi-page flows |
| 8 | Song et al., *"Hierarchical Vision-Language Planning for Web Navigation"* | 2024 † | † planning reference | Milestone-monitor early-exit / semantic-drift breaker concept |
| 9 | Rawles et al., *"Android in the Wild: A Large-Scale Dataset for Android Device Control"* — https://arxiv.org/abs/2307.10088 | 2023 | verified | Deterministic automation over known structural paths (Reflex compiler rationale) |
| 10 | Wang et al., *"Mobile-Agent v2: Mobile Device Operation Assistant with Multi-Agent Collaboration"* — https://arxiv.org/abs/2406.01014 | 2024 | verified | Recovery-plan → local sub-goal execution without cloud round-trips |

## Local perception & visual grounding

| # | Citation | Venue | Status | Used for |
|---|---|---|---|---|
| 11 | Lu et al. (Microsoft Research), *"OmniParser for Pure Vision Based GUI Agent"* — https://arxiv.org/abs/2408.00203 | 2024 | verified | Local INT8 visual-fallback parser concept for canvas/WebGL gaps; planning latency budget |
| 12 | Yang et al., *"Set-of-Mark Prompting Unleashes Extraordinary Visual Grounding in GPT-4V"* — https://arxiv.org/abs/2310.11441 | 2023 | verified | Set-of-Mark coordinate annotation in escalation payloads |
| 13 | Wang et al., *"Qwen2-VL: To See the World More Clearly"* — https://arxiv.org/abs/2409.12191 | 2024 | verified | In-VM quantized 2B SLM candidate for single-hop grounding; planning latency/accuracy targets |
| 14 | Qin et al. (ByteDance), *"UI-TARS: Pioneering Automated GUI Interaction with Native Agents"* — https://arxiv.org/abs/2501.12326 | 2025 | verified | In-VM quantized 2B SLM candidate (alternative to Qwen2-VL) |
| 15 | Hong et al., *"CogAgent: A Visual Language Model for GUI Agents"* — https://arxiv.org/abs/2312.10034 | CVPR 2024 | verified | Small-local-model grounding competitiveness argument |

## Efficient cascading, routing & anomaly detection

| # | Citation | Venue | Status | Used for |
|---|---|---|---|---|
| 16 | Wei et al., *"Step-level Optimization for Efficient Computer-use Agents"* | 2026 † | † planning reference | Stuck/milestone monitor formulation and planning recall/latency targets as stated in the plan |
| 17 | Warner et al., *"Smarter, Better, Faster, Longer: A Modern Bidirectional Encoder for Fast, Memory-Efficient Inference (ModernBERT)"* — https://arxiv.org/abs/2412.09535 | 2024 | verified | Sub-100M bidirectional encoder choice for trajectory classification |
| 18 | Chen et al., *"FrugalGPT: How to Use Large Language Models While Reducing Cost and Improving Performance"* — https://arxiv.org/abs/2305.05176 | 2023 | verified | Cascaded-model cost discipline framing (cheap-first, escalate-only) |
| 19 | Zhang et al., *"EcoAssistant: Using LLM Assistant More Affordably and Accurately"* — https://arxiv.org/abs/2310.03074 | 2023 | verified | Milestone early-exit circuit-breaker concept |
| 20 | Ong et al., *"RouteLLM: Learning to Route LLMs with Preference Data"* — https://arxiv.org/abs/2406.18665 | 2024 | verified | Escalation-dispatcher routing concept; planning escalation-budget targets |

## Virtualization substrate

| # | Citation | Venue | Status | Used for |
|---|---|---|---|---|
| 21 | Agache et al., *"Firecracker: Lightweight Virtualization for Serverless Applications"* — https://www.usenix.org/conference/nsdi20/presentation/agache | NSDI 2020 | verified | Firecracker MicroVM + UFFD snapshot/restore concept for speculative execution and state forking |

## How our measured results relate to these sources

- **Baseline cost/latency bands shown in the plan's comparison table** (e.g. "$0.40–$1.50/task", "1,800–3,500 ms/step") are repository planning targets assembled in `IMPLEMENTATION_PLAN.md` — not values quoted verbatim from any paper above. Numeric repository targets (≤5 ms UFFD restore, ≤1,200 tokens/step, monitor recall/accuracy percentages, ≤18% escalation budget, latency and SER budgets) are likewise this repo's own design targets, grounded in the rationale of the cited works but not measured by them.
- **$0.0015/task, 2.31 ms avg latency, SER 0.80** are measured by our own harness (`artifacts/production/final_scorecard.json`, labeled `PROJECTED_BASED_ON_MOCK_EXECUTION`). Link them only to repository artifacts — never to the papers.
- **94.2% / 98.1% / 100% monitor prevention rates** are measured by our Phase 3/5 suites using detection concepts related to #16–#19 — the papers supply rationale, not these numbers.
- **Sub-5 ms VM snapshot/restore target** is this repo's own design goal using the Firecracker + UFFD concept from #21 — not a value the Firecracker paper measured for this project.
