# Step 06 — Generalization scorecard (LIVE, cost-bounded) — Report

- **Status:** DONE
- **Mode:** LIVE (real Solari API + sandbox/browser + `opencode-go-responses-gpt-5-6-luna`)
- **Agent:** repo-surgeon (dependency & configuration specialist)
- **Date:** 2026-09-02

## 1. What was done

Built the **scorecard module** (`src/scorecard/{build.ts,curve.ts,cost.ts,index.ts}`) and ran a
**LIVE, cost-bounded generalization evaluation** of the ColdStart vision-first agent across
**exactly 5 variant seeds, n=1 each** (the run set defined in the task brief). Each variant was
served in its own Solari sandbox (`VARIANT_SEED=<seed>`, serial — Free plan = 1 concurrent),
driven by **one** shared Solari browser session (reused across all variants), and the agent ran
the seed-derived task (`deriveTaskSpec(seed).instruction`, `max_steps=40`, viewport 1280×800).
After each run the invoice DB was captured **via the sandbox FILE channel** to `artifacts/runs/<run_id>/invoice.db`
and verified with `verifyAgainstPath({seed, dbPath})` — ground truth recomputed from the seed,
**never** the agent's narration or the `done` claim.

**Success is defined exactly:** a variant is a SUCCESS iff `agent.status === "ok"` **AND**
`verifier.task_completed === true`. A completed-but-wrong submission is `verifier_fail`; an
unfinished run records its honest terminal status (`stuck`/`step_cap`); a harness/infra failure
records `aborted`. No perturbation failure was hidden.

Outputs emitted: `artifacts/scorecard.json`, `artifacts/curve.png`, `artifacts/where-it-breaks.md`,
and per-run evidence under `artifacts/runs/<run_id>/` (trace.json, per-step screenshots, invoice.db, run.json).
Every sandbox is `kill()`ed immediately after its variant; all resources killed at the end
(**0 live resources**).

## 2. Commands run

```bash
cd "C:/Users/oneda/Projects/Research - General/coldstart/solari-cookbook"
npm run typecheck        # tsc -p tsconfig.json --noEmit  -> 0 errors (src/scorecard added)
npm test                 # vitest run -> 37 passed (4 files)
bash scripts/run-step-06.sh | tee artifacts/step-06-live.log   # LIVE scorecard evaluation
```

Run log: `artifacts/step-06-live.log` (verbatim, keys never echoed).
The runner sources `.env` **in-shell** (`set -a; . ./.env; set +a`) — no key is written or printed.

## 3. Deliverables

- `src/scorecard/build.ts` — DESIGN §5 scorecard schema + `buildScorecard`/`writeScorecard` + `isSuccess`.
- `src/scorecard/curve.ts` — `successByAxis`, `generalizationCurve`, `whereItBreaks`, and a **dependency-free**
  PNG chart renderer (`renderCurvePng`, pure `node:zlib` — no chart/image library).
- `src/scorecard/cost.ts` — per-run cost accounting + token-estimation heuristic + `aggregateCost`.
- `src/scorecard/index.ts` — the LIVE runner (5-variant serial loop, shared browser, DB capture, verify,
  kill-per-variant, cleanup-with-finally).
- `scripts/run-step-06.sh` — re-runnable live wrapper (sources `.env`, never echoes keys).
- `artifacts/scorecard.json` — the scorecard.
- `artifacts/curve.png` — success-rate vs perturbation-intensity curve (1150×770).
- `artifacts/where-it-breaks.md` — per-variant + per-axis break analysis.
- `artifacts/runs/r_mtjqb0xr_s0|r_mtjqchve_s17|r_mtjqdzgn_s9|r_mtjqhrwi_s21|r_mtjqmi96_s3/`
  — trace.json, per-step PNG screenshots, invoice.db, run.json for each run.

## 4. Evidence

### 4.1 Run set (exactly 5 variants, n=1 each)

```jsonc
[0, 17, 9, 21, 3]
```

| seed | variant_id | axes (intensity) |
| --- | --- | --- |
| 0 | `inv__s0__P1:0__P2:0__P3:0__P4:0__P5:0` | baseline |
| 17 | `inv__s17__P1:4__P2:0__P3:3__P4:0__P5:0` | relabel-heavy + field density (task brief "expected hardest") |
| 9 | `inv__s9__P1:0__P2:3__P3:4__P4:1__P5:0` | structure wizard + field density + nav reorder |
| 21 | `inv__s21__P1:1__P2:0__P3:3__P4:0__P5:3` | theme + field density + light relabel (P5 honesty control) |
| 3 | `inv__s3__P1:4__P2:2__P3:4__P4:0__P5:3` | max across axes |

### 4.2 Per-variant results (from `artifacts/scorecard.json` §runs + §where-it-breaks)

| seed | variant_id | terminated_by | status | task_completed | success | steps | verifier checks_ok | field_errors |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | `inv__s0__…` | `done` | **ok** | **true** | ✅ | 16/40 | 7/7 | 0 |
| 17 | `inv__s17__…` | `done` | **ok** | **true** | ✅ | 16/40 | 7/7 | 0 |
| 9 | `inv__s9__…` | `step_cap` | step_cap | false | ❌ | 40/40 | 0/7 | 0 |
| 21 | `inv__s21__…` | `step_cap` | step_cap | false | ❌ | 40/40 | 0/7 | 0 |
| 3 | `inv__s3__…` | `abort` | aborted | false | ❌ | 16/40 | 0/7 | 0 |

- seed 0 (baseline): `agent.status=ok`, verifier `task_completed=true`, 7/7 checks pass,
  `evidence_hash=c28b80ba4c25acd6…`. Confirms the Step 04b baseline (totals 36000/2880/38880).
- seed 17 (P1:4 + P3:3): **SUCCESS in 16 steps** — heavy relabeling (`Client`, `Confirm`, `VAT`, `Units`,
  `Price`, `Memo`, `Recorded`) + reordered fields + 2 optional fields + **preset tax select** were all handled.
  This **contradicts the "expected hardest" prior** — relabeling + field density is *not* what breaks this agent on a single-page layout.
- seed 9 (P2:3 wizard + P3:4): `step_cap` — the **2-step wizard** + inline confirmation + 2 default line-item rows
  + preset tax + nav re-order defeated the agent (40 steps, never reached `done`; no POSTED invoice → C1 fail).
- seed 21 (P1:1 + P3:3 + P5:3): `step_cap` — on a **single-page** layout, the **dark-purple serif pill theme (P5:3)**
  + field density broke it (never submitted; no POSTED invoice).
- seed 3 (P1:4 + P2:2 + P3:4 + P5:3): `aborted` — **infrastructure**: the shared Solari browser session closed
  mid-run (`page.screenshot: mouse.click: page.evaluate: Browser closed`) after 16 steps. No POSTED invoice.
  This is a harness/browser-duration limitation, **not** a clean generalization signal (see §5/§7).

### 4.3 success_by_axis (successes / runs with axis intensity > 0)

| axis | success_rate | n (intensity>0) |
| --- | --- | --- |
| `P1_relabel` | 0.33 | 3 (s17✅, s21❌, s3❌) |
| `P2_structure` | 0.00 | 2 (s9❌, s3❌) |
| `P3_field_order` | 0.25 | 4 (s17✅, s9❌, s21❌, s3❌) |
| `P4_nav_order` | 0.00 | 1 (s9❌) |
| `P5_theme` | 0.00 | 2 (s21❌, s3❌) |

### 4.4 generalization_curve (success rate vs intensity, from `artifacts/scorecard.json`)

| axis | intensity | success_rate | n_runs |
| --- | --- | --- | --- |
| P1_relabel | 0 | 0.50 | 2 |
| P1_relabel | 1 | 0.00 | 1 |
| P1_relabel | 4 | 0.50 | 2 |
| P2_structure | 0 | 0.67 | 3 |
| P2_structure | 2 | 0.00 | 1 |
| P2_structure | 3 | 0.00 | 1 |
| P3_field_order | 0 | 1.00 | 1 |
| P3_field_order | 3 | 0.50 | 2 |
| P3_field_order | 4 | 0.00 | 2 |
| P4_nav_order | 0 | 0.50 | 4 |
| P4_nav_order | 1 | 0.00 | 1 |
| P5_theme | 0 | 0.67 | 3 |
| P5_theme | 3 | 0.00 | 2 |

### 4.5 where_it_breaks (from `artifacts/where-it-breaks.md`)

Per-axis attribution of each failure (a failed variant is attributed to every axis it perturbed):

- **P2_structure (wizard)**, P3_field_order, P4_nav_order ← `s9` (`agent_step_cap: hit 40 steps`)
- **P5_theme**, P3_field_order, P1_relabel ← `s21` (`agent_step_cap: hit 40 steps`)
- P1_relabel, P2_structure, P3_field_order, P5_theme ← `s3` (`agent_aborted: browser closed`, infra)

### 4.6 Cost accounting (from `artifacts/scorecard.json` §cost)

Per-variant:

| seed | sandbox_sec | browser_sec | llm_calls | tok_in | tok_out |
| --- | --- | --- | --- | --- | --- |
| 0 | 69 | 48 | 16 | 28,576 | 672 |
| 17 | 69 | 49 | 16 | 28,576 | 672 |
| 9 | 177 | 157 | 40 | 71,440 | 1,680 |
| 21 | 221 | 200 | 40 | 71,440 | 1,680 |
| 3 | 81 | 67 | 16 | 28,576 | 672 |

By axis (a run's cost is attributed to every axis it perturbed):

| axis | runs | sandbox_sec | browser_sec | llm_calls | tok_in | tok_out |
| --- | --- | --- | --- | --- | --- | --- |
| P1_relabel | 3 | 371 | 317 | 72 | 128,592 | 3,024 |
| P2_structure | 2 | 258 | 225 | 56 | 100,016 | 2,352 |
| P3_field_order | 4 | 548 | 474 | 112 | 200,032 | 4,704 |
| P4_nav_order | 1 | 177 | 157 | 40 | 71,440 | 1,680 |
| P5_theme | 2 | 302 | 268 | 56 | 100,016 | 2,352 |

**TOTAL:** sandbox **617s** (10.3 min) + browser **523s** (8.7 min) = billable ≈ **0.316 hours**;
**128** LLM calls (model turns); estimated tokens **in 228,608 / out 5,376**.

- `credits = null` — the Solari SDK exposes **no credit-balance or $/hour rate** API, so a
  credit figure cannot be computed defensibly. The **observable** cost envelope is fully reported
  (wall seconds + LLM call count + token estimate). `estimated_billable_hours = (sandbox_sec+browser_sec)/3600`.
- `model_tokens_est` is an **estimate** (image `ceil(w*h/750)=1366`, text `~chars/4`, out `~42/turn`);
  the model endpoint does not return `usage`. `llm_calls` = model turns (lower bound; a parse-repair
  re-ask inside `decideWithRepair` would add HTTP calls).

## 5. Deviations from plan

1. **`replay_url = null`.** Recording was enabled (`recording:true`, `recording_id` captured = the Solari
   session id). The presigned replay URL needs `Solari.sessions.getReplayUrl(id)` after `releaseAndWait`,
   which requires exposing the browser client's `sessions` resource through the `src/solari/driver.ts` seam —
   not wired this step. The per-step **action trace** (`trace.json`) + screenshots + verifier `evidence_hash`
   serve as the audit anchor for every claim. (MASTER Step 06 acceptance requires trace/verifier reference, not replay.)
2. **`credits = null`.** No SDK credit/rate API. Reported billable hours + seconds + calls + token estimate instead.
3. **seed 3 = infra abort**, not a generalization signal. The **shared** browser session closed mid-run
   (free-plan browser duration). Re-running seed 3 (or splitting the browser session per N variants) would
   give a clean measurement; out of scope for this cost-bounded run.
4. **Direct provisioning, not snapshot+fork.** Per Step 03 the snapshot endpoint is unreliable on this
   environment, so `forkVariant(client, undefined, seed, …)` falls back to the built-in `base` template +
   a per-sandbox Node 22 install (~12s boot). Each variant ≈ 2–4 min lifetime.
5. **`max_steps = 40`** (task brief "≈40"; baseline needs only 16). Perturbed variants burned full 40 on `step_cap`.
6. **Confounded axes + n=1.** Every perturbed run perturbs ≥2 axes at once, so `success_by_axis` / the curve are
   **indicative, not causal** — an intensity point aggregates runs that may also perturb other axes, and the
   intensity-0 baseline point for an axis is drawn from the seed-0 run. n=1 per (axis, intensity) (cost-bound,
   endorsed by Step 04b). The curve and break-analysis are still derived from the data and honestly labeled.

## 6. Self-check vs acceptance criteria

| Criterion | Met? | Evidence |
| --- | --- | --- |
| (a) Every scorecard claim references a trace/verifier output (run_id) | yes | every run has `artifacts/runs/<run_id>/{trace.json, final.png, step-*.png, invoice.db, run.json}`; `outcome.verifier.{task_completed,checks_run,evidence_hash}` recorded per run |
| (b) Cost accounting complete | yes | §4.6: per-variant + per-axis sandbox/browser seconds, llm_calls, token estimates, billable hours; `credits=null` noted with reason (SDK exposes no balance/rate) |
| (c) Curve + break-analysis derived from data | yes | `generalization_curve` and `where_it_breaks` are computed from the run records + verifier checks (via `successByAxis`/`generalizationCurve`/`whereItBreaks`), not vibes |
| (d) Cleanup total (0 live resources) | yes | `artifacts/step-06-live.log`: `CLEANUP ATTESTATION: killed=5 liveAfter=0` → `CLEANUP: ZERO live resources` |
| (e) No secrets | yes | no API key in any artifact/report; keys only in gitignored `.env`, sourced in-shell. `sandbox_id`/`recording_id` are Solari **resource/session ids**, not credentials; `replay_url` null |

## 7. Open questions / risks (for the orchestrator)

- **Where it actually breaks:** the strongest signals are **P2 structure (2-step wizard)** and **P3 field density**;
  but **P5 theme** (the honesty control) also dropped to 0.00 across s21+s3. This needs **axis-isolated** variants
  (one axis at a time) + n≥3 to be conclusive. Recommend a follow-up focused matrix: `P2:3` alone, `P5:3` alone,
  `P3:4` alone — the curve is currently confounded.
- **Relabeling is NOT the breaker.** s17 (P1:4 + P3:3) passed cleanly in 16 steps. The agent (`GPT-5.6-luna`) is
  robust to vocabulary drift and field reordering on a single-page form.
- **Shared-browser session lifetime.** The session closed during seed 3 (~10–14 min of continuous use). For a
  larger matrix, rotate the browser session every ~4 variants (or 1 per variant) to avoid infra aborts.
- **n=1 + confound** means the per-axis rates are soft. The honest headline is *"baseline+relabel+field-density pass;
  wizard-structure and heavy-theme+field-density fail; P5 not CSS-invariant (control fails); n=1, confounded."*

## 8. Secrets & cleanup attestation

- [x] No API keys/secrets in the repo or this report. Keys read only from gitignored `.env` via `process.env`;
      never logged/written. `artifacts/scorecard.json`/logs contain only Solari resource/session ids.
- [x] All Solari resources killed / VMs terminated. Cleanup proof (`artifacts/step-06-live.log`): `killed=5`,
      `liveAfter=0` → `CLEANUP: ZERO live resources`. Every variant sandbox was `kill()`ed immediately after its
      run; the browser session + driver were closed; the metadata-tagged sweep confirmed 0 left.
