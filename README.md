# ColdStart — Zero-shot generalization harness for computer-use agents (on Solari)

> **Cold generalizes. Warm reliability does not.**
> ColdStart never shows an agent the same app twice. It measures the one thing
> that matters for real computer-use agents: **do they complete a task in an
> environment they have never seen?**

ColdStart is a self-contained evaluation harness that procedurally generates
never-before-seen variants of a small enterprise workflow (a "Create Invoice" app),
has a **vision-first** agent complete the identical task *cold* in each one
(**pixels in, coordinates out** — no DOM, no selectors, no accessibility tree),
verifies the outcome **independently** against a recomputed ground truth
(**fail-closed**, sha256-bound), and emits a **generalization scorecard**, a
success-vs-novelty **curve**, and a **"where it breaks"** analysis.

It runs on [Solari](https://getsolari.com) (cloud browser + sandbox) and was built
as a working answer to the Pinetree Research SWE-intern challenge.

---

## Why this exists

Pinetree's operating thesis is that **intelligence is no longer the bottleneck —
execution is**. The durable moat for a computer-use agent is not "can it use the
app it was tested on" but **"can it zero-shot generalize to an app it has never
seen"** (in the spirit of the *Hallucinate Westworld* framing). Nearly every
computer-use demo in the wild is a solved warm environment: the agent has been
log-probed, DOM-cached, or trained on the exact layout.

ColdStart makes that failure mode **measurable**. It is deliberately small and
deliberately honest:

- **One task app** (Create-Invoice) with a **hard, independently-computable ground
  truth** (a `POSTED` invoice row whose totals the verifier *recomputes*).
- **Five perturbation axes** that mutate the app in ways the agent could never have
  memorized, driven by a **seeded PRNG** so every variant is reproducible
  (`same seed → same variant`).
- A **vision-first action space** (screenshot ≥ `{click(x,y), type, press, nav,
  done, abort}`) that structurally **forbids** the anti-pattern Pinetree hates —
  the model can never read the DOM, innerText, `locator()`, or element boxes.
- A **fail-closed verifier** that reads the SQLite record via the **sandbox
  file/DB channel**, recomputes the expected values from the seed, and returns
  `task_completed=false` on *any* ambiguity. The agent's `done` is a **claim, not a
  result**.

---

## What it measures

ColdStart answers precisely: *"Across a spread of unseen variants, how often does a
vision-first agent actually complete the task — and which kind of change breaks
it?"* It produces:

- `artifacts/scorecard.json` — per-variant + per-axis success, generalization curve
  points, and cost accounting (sandbox/browser seconds, LLM calls, token estimate).
- `artifacts/curve.png` — success rate vs. perturbation intensity per axis.
- `artifacts/where-it-breaks.md` — per-variant and per-axis failure attribution.
- `artifacts/runs/<run_id>/` — per-run `trace.json`, per-step screenshots, and the
  captured `invoice.db`, so every scorecard claim is traceable to evidence.
- `artifacts/demo.gif` — a short animated walkthrough of a successful run.

### The five perturbation axes (ranked hardest → easiest)

| Axis | What changes | Why it stress-tests generalization |
| --- | --- | --- |
| **P1 · Relabel** | every task-relevant string is swapped for a synonym ("New Invoice"→"Record a Sale", "Customer"→"Client", "Submit"→"Confirm", "Tax Rate"→"VAT", "Qty"→"Units", description→"Memo") | the agent must infer a field's *semantic role* from a word it has never seen paired with that role. Vocabulary distribution shift. |
| **P2 · Structure/flow** | single-page form ↔ two-step wizard; confirmation page ↔ inline banner; entry-point placement; "add row" line items | even a model that recognizes *every label* fails if the *order of operations* is unseen. |
| **P3 · Field order/density** | shuffle field order; add optional fields (PO#, reference, notes); percent vs. preset tax; default date prefill | breaks a learned fill sequence; "which field am I missing?" becomes ambiguous. |
| **P4 · Nav order/grouping** | reorder/group the header/sidebar nav (labels unchanged) | affects the *scan path* for the first action; labels stable so a strong agent recovers. |
| **P5 · Theme/CSS** | color palette, font, button style, spacing/borders/radius (the honesty **control**) | a *genuinely* vision-first agent should be near-invariant to skin. If a CSS-only change collapses it, the agent was secretly DOM-caching or text-scraping. |

---

## Architecture

```
variants.json  ◄───────────── src/generate-variants/*   seeded variant factory
   │                              prng.ts · axes.ts · task-spec.ts · variants.ts
   │                              (sameSeed → sameVariant; domain-separated streams)
   ▼
Solari sandbox ────────────── src/solari/orchestrate.ts  fork, install Node 22,
   │                              serve create-invoice app, previewUrl (URL-safe)
   ▼
Solari cloud browser ──────── src/solari/driver.ts       LiveSolari | MockSolari
   │                              (Playwright-compatible; locator() never called)
   ▼
Vision-first agent loop ───── src/agent/action.ts model.ts loop.ts trace.ts screenshot.ts
   │                              screenshot (1280x800 PNG) → {click(x,y)|type|press|nav|done|abort}
   │                              pixels in, coordinates out. NO DOM/selectors/bounding boxes.
   ▼
Fail-closed verifier ──────── src/verify/verifier.ts checks.ts
   │                              reads /app/data/invoice.db via the sandbox channel
   │                              recomputes expected from seed; runs C1–C7; sha256 evidence hash
   │                              task_completed=false on ANY ambiguity (empty DB, wrong values,
   │                              DRAFT-only, extra row, unreadable artifact)
   ▼
Scorecard + curve + breaks ── src/scorecard/build.ts curve.ts cost.ts index.ts
                                  artifacts/scorecard.json · curve.png · where-it-breaks.md
                                  artifacts/demo.gif
```

**The task app** (`src/variant-app/`) is a dependency-free Node 22 `node:http` +
`node:sqlite` server with exactly four routes (`/`, `/new`, `/invoices` POST, `/invoices/:id`)
and a fixed ground-truth store at `/app/data/invoice.db`. Ground truth = **exactly one
`invoices` row with `status='POSTED'`** whose customer, line items, tax rate, and dates
match the seed-derived expectation **and** whose totals are internally consistent.

**The verifier is the part that keeps this honest.** It does not read the HTML, does not
trust any "correct answer" persisted by the app, and does not read the agent's narration.
It recomputes `customer`, the line items, `tax_rate_bps`, both dates, **and the totals**
from the raw line-item columns, then compares against the stored row. Only an unambiguous,
fully-matching, internally-consistent `POSTED` invoice flips `task_completed` to `true`.
The raw artifact bytes are sha256-bound so any swap is detectable.

---

## Results (Step 06 · LIVE, cost-bounded)

Five variants, n=1 each, one shared browser session, one sandbox per variant (serial).
Model: `opencode-go-responses-gpt-5-6-luna`. Success = agent `ok` **AND** verifier
`task_completed === true`.

| seed | variant (axes) | terminated_by | status | task_completed | success | steps |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | baseline (all 0) | `done` | ok | **true** | ✅ | 16/40 |
| 17 | **P1:4** + P3:3 (relabel-heavy + field density) | `done` | ok | **true** | ✅ | 16/40 |
| 9 | P2:3 (wizard) + P3:4 + P4:1 | `step_cap` | step_cap | false | ❌ | 40/40 |
| 21 | P1:1 + P3:3 + P5:3 (theme) | `step_cap` | step_cap | false | ❌ | 40/40 |
| 3 | P1:4 + P2:2 + P3:4 + P5:3 | `abort` | aborted | false | ❌ (infra) | 16/40 |

### success_by_axis (successes / runs with intensity > 0)

| axis | success rate | n (intensity > 0) |
| --- | --- | --- |
| `P1_relabel` | 0.33 | 3 |
| `P2_structure` | 0.00 | 2 |
| `P3_field_order` | 0.25 | 4 |
| `P4_nav_order` | 0.00 | 1 |
| `P5_theme` | 0.00 | 2 |

### The raw (mixed-axis) result — superseded by the causal finding (below)

> ⚠️ This first Step 06 run set perturbed **≥2 axes per variant**, so its per-axis attribution is **confounded** (a failure is charged to every axis a variant touched). **Read the Step 06b axis-isolated / causal result below as the conclusion; this table is the raw, confounded observation.**

- **Robust to label-vocabulary drift.** The heaviest relabel variant (`s17`, P1:4 —
  `Client`, `Confirm`, `VAT`, `Units`, `Price`, `Memo`, `Recorded` — *plus* reordered
  fields) completed cleanly in **16 steps** with all 7 verifier checks green. This
  contradicts the "expected hardest" prior: relabeling + field density is *not* what
  breaks this agent on a single-page form.
- **Breaks on structure/flow and high field density.** The **two-step wizard** (`s9`,
  P2:3) and the heavy theme + field-density combo (`s21`) both burned the full 40-step
  budget without submitting. The strongest failure signals are **P2 structure** and
  **P3 field density**.
- **P5 (the theme control) fails.** The dark-purple serif theme on `s21` (and `s3`)
  collapsed the agent. A CSS-only change dropping to 0.00 is the honest-control signal
  that this agent is *not* fully skin-invariant — the very anti-pattern P5 was designed
  to expose, and exactly the information a "does it really generalize" reviewer wants.

### Honest model note

A free / general chat model **cannot reliably complete this form.** Across the six models
we tried in Step 04, most **click-locked on a field and never emitted a single `type`**
(so no text was ever entered), looped, or got rate-limited (`HTTP 429`); only
**`opencode-go-responses-gpt-5-6-luna`** reliably drove the baseline to a `POSTED`
invoice (3/3, 16 steps each, Step 04b). **The durable insight is the harness + grounding
+ fail-closed verification** — not the model. The harness behaved flawlessly even when
the model did not, and it records the failure honestly.

### Cost (observable, metered)

Total **617s sandbox + 523s browser ≈ 0.316 billable hours**, **128 LLM calls**, and an
estimated **228,608 token-in / 5,376 out**. `credits` is `null` because the Solari SDK
does not expose credit balance or a $/hour rate; the observable envelope (wall seconds +
call count + token estimate) is reported instead.

---

### Step 06b — AXIS-ISOLATED & CAUSAL (Option C)

The Step 06 run set perturbed **≥2 axes per variant**, so its per-axis rates were
**confounded** (a failure was attributed to *every* axis a variant touched). Step 06b
removes the confound: **exactly one axis is perturbed at a time** while the task and the
expected answer are held CONSTANT (`VARIANT_SEED=0` + `COLDSTART_AXES=<one active axis>`,
`deriveTaskSpec(0).instruction` as the task, `verifyAgainstPath({seed:0, dbPath})` as ground
truth). Three isolated points, **n=2 each = 6 runs** (same model, `max_steps=40`, viewport 1280×800):

| point | axis (isolated) | rep | terminated_by | status | task_completed | success |
| --- | --- | --- | --- | --- | --- | --- |
| P2_structure:3 | structure / wizard | 1 | abort (infra) | aborted | false | ❌ |
| P2_structure:3 | structure / wizard | 2 | step_cap | step_cap | false | ❌ |
| P5_theme:3 | theme / CSS skin | 1 | done | ok | true | ✅ |
| P5_theme:3 | theme / CSS skin | 2 | done | ok | true | ✅ |
| P3_field_order:4 | field order & density | 1 | done | ok | true | ✅ |
| P3_field_order:4 | field order & density | 2 | abort (infra) | aborted | false | ❌ |

**success_by_axis (isolated — causal, no cross-axis attribution):**

| axis | success rate | n (isolated) |
| --- | --- | --- |
| `P2_structure` | 0.00 | 2 |
| `P5_theme` | 1.00 | 2 |
| `P3_field_order` | 0.50 | 2 |

### The causal finding (it resolves the Step 06 confound)

- **The one genuine breaker is P2 — structure / flow (the two-step wizard).** Isolated
  P2:3 never reached `done` (`step_cap`, no `POSTED` invoice). This confirms Step 06's
  strongest signal and is the causal breaker.
- **The theme honesty control (`P5`) HOLDS when isolated — 2/2 pass in 16 steps each.**
  Step 06 reported P5:0.00, but that came from the **combined** `s21` (P5:3 + P1:1 + P3:3).
  In isolation a CSS-only re-theme (dark serif pill) does **not** break the agent — so the
  agent *is* skin-invariant, exactly as the P5 control is designed to check. The Step 06 P5
  failure was a **confound** (the interaction of theme with relabel + field density), not a
  P5 effect.
- **Field order & density (P3:4) passes when isolated** (17 steps, 7/7 verifier checks green).
  Step 06's "P3 fails" was likewise drawn from combined variants.
- **`session.replay_url` is now wired and captured** (`recording:true` + `releaseAndWait` +
  `getReplayUrl` per run): 4 of 5 live sessions returned a real presigned replay; the one
  `null` (P3_field_order:4 × 1) is recorded honestly (the SDK returned nothing after ~6s of
  polling post-release). `recording_id` is captured on every live run.

**Honest caveat:** 2 of the 6 runs were **infra aborts**, not generalization failures
(P2:3 rep1 — the browser screenshot channel dropped mid-run; P3:4 rep2 — the sandbox control
channel closed at provisioning). Clean-evidence rates are therefore P2 **0/1**, P5 **2/2**, P3
**1/1**. n=2 with two infra-aborts is a small sample — treat the causal *direction* as robust
and the exact rates as soft.

---

## How to run

Prerequisites: **Node 22+**, and for live runs a Solari API key + a vision model endpoint.

```bash
# 1) Install
npm install

# 2) Configure environment (names only — copy to .env and fill in real values)
cp .env.example .env
#    .env must contain: SOLARI_API_KEY, LLM_API_KEY, LLM_ENDPOINT, LLM_MODEL
#    (LLM_ENDPOINT is an OpenAI-compatible https://…/chat/completions; LLM_MODEL must be vision-capable)

# 3) Generate the seeded variant matrix  (deterministic; same seed → same variant)
npm run gen:variants            # writes variants.json

# 4) Type-check and unit-test (offline; no keys needed)
npm run typecheck               # tsc --noEmit  → 0 errors
npm test                        # vitest run    → 37 passed

# 5) Build the variant app (uploaded into each sandbox)
npm run build                   # emits dist/variant-app/server.js

# 6) Live baseline run — one create-invoice variant, vision-first agent
set -a; . ./.env; set +a
COLDSTART_MAX_STEPS=24 npx tsx src/agent/index.ts

# 7) Live generalization scorecard — the 5-variant run set (cost-bounded)
bash scripts/run-step-06.sh     # drives src/scorecard/index.ts; env sourced in-shell

# 8) Axis-isolated (causal) scorecard follow-up — P2:3 / P5:3 / P3:4, n=2 each
bash scripts/run-step-06b.sh    # drives src/scorecard/isolated.ts; env sourced in-shell
```

> The run scripts source `.env` **in-shell** (`set -a; . ./.env; set +a`) so a key is
> **never** placed on a command line, echoed, or written to a file. Keys are read from
> `process.env` only, in the agent process; they never reach the variant app or the
> verifier. Run the unit tests (`npm test`) in **MOCK mode** with no model key — they
> prove the plumbing offline.

---

## Repository layout

```
src/
  solari/driver.ts          LiveSolari | MockSolari (the single Solari seam; key from env only)
  solari/orchestrate.ts     sandbox fork/serve + previewUrl + cleanup
  variant-app/              dependency-free create-invoice app (node:http + node:sqlite)
  generate-variants/        seeded variant factory (prng, axes, task-spec, variants)
  agent/                    vision-first loop (action, model, loop, trace, screenshot)
  verify/                   fail-closed verifier (verifier, checks C1–C7)
  scorecard/                scorecard + curve + cost + axis-isolated runner (build, curve, cost, index, isolated)
test/                       vitest unit tests (prng, axes, verifier, agent-loop)
artifacts/                  scorecard.json · curve.png · where-it-breaks.md · demo.gif · runs/
scripts/run-step-03.sh      live orchestration proof wrapper
scripts/run-step-06.sh      live scorecard wrapper (sources .env, never echoes keys)
scripts/run-step-06b.sh     live axis-isolated scorecard wrapper (sources .env, never echoes keys)
DESIGN.md                   the locked design contract
```

---

## Limitations (honest)

- **Small-n + infra-aborts.** Step 06b is n=2 per isolated point (cost-bounded), and 2 of
  its 6 runs were **infra aborts** (a dropped browser screenshot channel; a sandbox control
  channel that closed at provisioning) — not generalization failures. Clean-evidence rates
  are P2 0/1, P5 2/2, P3 1/1. Causal *direction* is robust, exact rates are soft.
- **Mixed-axis confound RESOLVED by Step 06b (causal).** The original Step 06 set perturbed
  ≥2 axes per variant, so its per-axis rates were indicative, not causal. Step 06b runs one
  axis at a time with a constant task, and shows the **P5 theme control actually holds** and
  **P3 field density passes** — the Step 06 P5/P3 failures were confounds from combined
  variants. **P2 structure (the two-step wizard) is the genuine breaker.** P4 and P1 were
  not re-isolated in this follow-up (P1 already passed at P1:4 in Step 06; P4 was only ever
  tested bundled).
- **`credits` is `null`.** The Solari SDK exposes no credit balance or $/hour rate; the
  observable envelope (sandbox/browser seconds, LLM call count, token estimate, billable
  hours) is reported instead. Replay URL is now captured (see Results).
- **Per-run replay has one `null` (P3_field_order:4 × 1).** Recording is on and most runs
  returned a real presigned replay, but one session's `getReplayUrl` returned nothing after
  polling — recorded `null` honestly; the `action_trace.json` + screenshots + verifier
  `evidence_hash` remain the audit anchor regardless.
- **Model dependency.** Only a computer-use-capable model completes the task. A general
  chat/vision model cannot (see the honest model note above). ColdStart's value is the
  harness — the reproducibility of the variants, the vision-first grounding, and the
  fail-closed verifier — not any single model.
- **Small app, small novelties.** The Create-Invoice app and its variants are deliberately
  small. The perturbation axes are a proxy for "unseen environment," not a full measure of
  real-world breadth. That is the trade-off for a hard, recomputable ground truth.

---

## Demo

`artifacts/demo.gif` — a 16-frame animated walkthrough of a **successful** run
(`r_mtjqchve_s17`, the P1:4 relabel + P3:3 field-density variant), stitched from the
agent's per-step screenshots. It shows the vision-first agent filling the relabeled form
(`Client`, `VAT`, `Units`, `Price`, `Memo`), submitting with `Confirm`, and landing on the
`Recorded` confirmation page — all from coordinates, no DOM. The corresponding
`trace.json` (same run) records the exact action each screenshot drove.

---

## More

- `DESIGN.md` — the locked design contract (task app, axes, action space, verifier,
  scorecard schema, sandbox strategy).
- `src/` — the implementation.
- `reports/` — the audited per-step reports (in the parent `reports/` dir).
- `artifacts/` — the scorecard, curve, break-analysis, per-run evidence, and demo.

MIT licensed. Built on the [Solari cookbook](https://github.com/solari-sdk/solari-cookbook)
and the [Solari SDK](https://docs.getsolari.com).
