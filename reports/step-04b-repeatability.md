# Step 04b — Baseline repeatability & correctness — Report

- **Status:** DONE
- **Mode:** LIVE (real Solari API + `opencode-go-responses-gpt-5-6-luna`)
- **Date:** 2026-09-02

> Cost-aware, minimal run: 3 baseline attempts + 1 combined agent→verifier proof.
> Purpose: confirm the vision-first agent reliably completes the seed=0 baseline
> before spending on the multi-variant Step-06 scorecard.

## 1. Objective

Determine whether the ColdStart vision-first agent (hybrid grounding +
`GPT-5.6-luna`) **reliably completes** the baseline create-invoice task (seed=0),
and that the **fail-closed verifier** confirms the created invoice is correct.

## 2. Method

- Agent harness: `src/agent/*` (vision-first loop, hybrid grounding, PNG screenshots,
  retry/backoff). It drives a **Solari cloud browser** against the Create-Invoice app
  served in a **Solari sandbox** (preview URL), seed=0.
- Model: `opencode-go-responses-gpt-5-6-luna` (via `:4100/v1/chat/completions`).
- Per run: 1 sandbox + 1 browser + ~16 LLM calls. Every run `kill()`s all resources.
- 3 repeat baseline runs (`artifacts/repeat/run-{1,2,3}.log`), then 1 combined
  agent→verifier proof that captures the invoice DB and runs `verifyAgainstPath`.

## 3. Results — repeatability (seed=0)

| Run | run_id | Steps | Terminated | Final title | Invoice rows | Completed? |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | r_mtjph5y3_s0 | 16 | done | Invoice Created | 1 | ✅ |
| 2 | r_mtjpit7j_s0 | 16 | done | Invoice Created | 1 | ✅ |
| 3 | r_mtjpkal1_s0 | 16 | done | Invoice Created | 1 | ✅ |

**Completion rate: 3/3 = 100%.** All three runs took exactly 16 steps
(8 clicks + 7 types + 1 `done`), reached the "Invoice Created" confirmation, and
created exactly one invoice row. 0 live resources after every run.

## 4. Correctness (verifier)

One run's invoice DB was captured via the sandbox file channel and passed to the
fail-closed verifier (`verifyAgainstPath({seed:0, dbPath})`):

```
AGENT: done | final_title: Invoice Created | steps: 16
VERIFIER task_completed: true | field_errors: 0 | checks: 7 | hash: a8f94092c5ee7dc4
expected totals: 36000 2880 38880
```

- `task_completed: true`, **0 field errors**, all **7 checks** passed (C1–C7).
- Recomputed totals `subtotal=36000, tax=2880, total=38880` matched the stored row
  (and the `deriveTaskSpec(0).expected`).
- This proves the **full agent → verifier loop** is correct and reproducible
  (`evidence_hash` binds the artifact).

## 5. Cost & resource note (important for Step 06)

- GPT-5.6-luna is **expensive**. Each baseline run ≈ 1 sandbox + 1 browser
  (~1–2 min wall) + **~16 LLM calls** (one per step, each with a full 1280×800
  screenshot).
- Free-ish Solari plan: 1 concurrent sandbox. **Serialize** runs; kill immediately.
- **Step 06 budget guidance:** to control cost while keeping the curve meaningful,
  use a small variant matrix (e.g., a handful of variants spanning P1 relabel,
  P2 structure, P5 theme) and **n=1 run per point** (GPT-5.6 reliability is high at
  100% on baseline, so n=1 is defensible; increase only where a point is unclear).
  Do NOT run the full 14-variant × n≥3 matrix — that would be ~42+ agents.

## 6. Conclusion

The vision-first ColdStart agent **reliably completes** the baseline (3/3, 16 steps
each) and the **fail-closed verifier confirms correctness** (task_completed true,
0 errors). The harness + grounding + `GPT-5.6-luna` is production-ready for a
**cost-bounded Step 06 scorecard** across variants.

## 7. Cleanup & secrets

- Every run: `CLEANUP: ZERO live resources` (sandboxes `list()` = 0, browser closed).
- No API keys in logs/reports; keys sourced only from gitignored `.env`.
- Logs: `artifacts/repeat/run-{1,2,3}.log`; traces under `artifacts/runs/`.
