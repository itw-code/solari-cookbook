# ARC Index economics reel

A 15-second piece comparing a traditional browser agent with ARC Index on the same denial appeal: the same letters, the same stand-in portal, and Solari cloud browsers on both sides. Output: `artifacts/arc-index-economics-showreel.mp4`.

Every figure is measured (`scripts/benchmark_appeal_baseline.py`, `artifacts/benchmarks/appeal/summary.json`, `docs/ARC_INDEX_PLAN.md` §11). Gemini 3.8 Flash, API usage, n=10 appeals per harness (2 letters × 5):

| Per appeal | Traditional agent | ARC Index | |
|---|---|---|---|
| Input tokens | 26,955 | 1,209 | 22× fewer |
| Model cost ($0.75 / $3.75 per M) | $0.02203 | $0.00257 | 8.6× less |
| + Solari browser time ($0.15/h) | $0.02575 | $0.00305 | **8.4× less** |
| Wall time, mean | 89 s | 11.4 s | 7.8× faster |
| Fields right / wrong values let through | 49/60, 0 | 49/60, 0 | same |

- **Traditional agent:** the model gets the letter's text and the goal, and drives the portal with Solari's page tools, one call per turn and 11.7 calls on average. Each turn resends the conversation. It was told to leave a field blank when the letter lacks it or more than one value fits, and in these 10 runs it did.
- **ARC Index:** one extraction call, the grounding checks, then one batched fill and submit.
- **Claude Sonnet 5.5** (Claude Code subagents): model cost $0.02201 → $0.00524, 4.2× less. Its tokens are estimated at chars/4, the way a bare API loop would be billed, so it has no time figure.
- **Time varies a lot for the agent:** 13–137 s. Most of it is Solari tool latency (68 s of 89 s on average); its model time averages 21 s.

On accuracy the two tie here. Both filled 49 of 60 graded fields correctly and let no wrong value through. The difference is how they get there: the agent follows its instruction, while ARC rejects ambiguous fields by rule, whatever the model answers (`media/arc-index-bench-reel/`).

- `econ.html`: a 1920×1080 canvas, `window.render(t)`. It uses the same helpers as the other two reels, with the figures in one `D` object at the top.
- `render.py` and `soundtrack.py`: as in `media/arc-index-bench-reel/`.

Encode as in `media/arc-index-bench-reel/README.md`, with `arc-index-economics-showreel.mp4` as the output.
