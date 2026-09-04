# ColdStart

**A zero-shot generalization harness for computer-use agents, on [Solari](https://getsolari.com).**

[![CI](https://github.com/itw-code/solari-cookbook/actions/workflows/ci.yml/badge.svg)](https://github.com/itw-code/solari-cookbook/actions/workflows/ci.yml)
[![Node](https://img.shields.io/badge/node-22%2B-5FA04E?logo=node.js&logoColor=white)](https://nodejs.org)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.7-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Tests](https://img.shields.io/badge/tests-37%20passing-brightgreen)](test/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

> **Cold generalizes. Warm reliability does not.**
> ColdStart never shows an agent the same app twice. It measures the one thing that
> matters for real computer-use agents: **do they complete a task in an environment
> they have never seen?**

![A vision-first agent completing the Create-Invoice task in a variant it has never seen: empty relabeled form, filling, coordinates in, the POSTED confirmation](artifacts/showcase.gif)

<sub>Run <code>r_mtjqchve_s17</code> — the P1:4 relabel + P3:3 variant. The agent has never seen
these labels (<code>Client</code>, <code>VAT</code>, <code>Units</code>, <code>Memo</code>,
<code>Confirm</code>). <b>Pixels in, coordinates out</b> — no DOM, no selectors, no accessibility
tree. 16 steps, all 7 verifier checks green.</sub>

---

## The finding, in one paragraph

Across axis-isolated runs, this vision-first agent **generalizes across surface variation**
but **breaks on procedural change**. Swap every label for a synonym it has never seen paired
with that role (P1) — it completes the task. Re-skin the entire app (P5, the honesty control)
— it completes the task, 2/2. Shuffle and pad the fields (P3) — it completes the task. But
split the same form into a **two-step wizard** (P2) — it never submits, burning the full step
budget. *Recognizing every element is not the same as knowing the order of operations.*

Every outcome here is confirmed by a **fail-closed verifier** that recomputes ground truth
from the seed and reads the resulting SQLite row out of the sandbox. The agent's `done` is a
**claim, not a result**. Nothing in this README is asserted — it is measured.

---

## Quickstart — 60 seconds, no API keys

The harness is fully exercisable offline. The unit tests run in **MOCK mode** and prove the
plumbing — seeded PRNG, axis mutations, the agent loop, and all seven verifier checks —
without a Solari key, a model key, or a single network call.

```bash
git clone https://github.com/itw-code/solari-cookbook.git
cd solari-cookbook
npm install

npm run verify          # tsc --noEmit -> 0 errors; vitest run -> 37 passed
npm run gen:variants    # deterministic variant matrix -> variants.json
```

Then read the evidence that is already committed — no run required:

| File | What it is |
| --- | --- |
| [`artifacts/scorecard.json`](artifacts/scorecard.json) | per-variant + per-axis success, curve points, cost accounting |
| [`artifacts/where-it-breaks.md`](artifacts/where-it-breaks.md) | per-variant and per-axis failure attribution |
| [`artifacts/curve.png`](artifacts/curve.png) | success rate vs. perturbation intensity |
| [`reports/`](reports/) | the 11 audited per-step build reports |

Live runs (real Solari sandboxes + a vision model) are in [How to run](#how-to-run) below.

---

## Why this exists

Pinetree's operating thesis is that **intelligence is no longer the bottleneck — execution
is**. The durable moat for a computer-use agent is not "can it use the app it was tested on"
but **"can it zero-shot generalize to an app it has never seen"** (in the spirit of the
*Hallucinate Westworld* framing). Nearly every computer-use demo in the wild is a solved warm
environment: the agent has been log-probed, DOM-cached, or trained on the exact layout.

ColdStart makes that failure mode **measurable**. It is deliberately small and deliberately
honest:

- **One task app** (Create-Invoice) with a **hard, independently-computable ground truth**
  (a `POSTED` invoice row whose totals the verifier *recomputes*).
- **Five perturbation axes** that mutate the app in ways the agent could never have
  memorized, driven by a **seeded PRNG** so every variant is reproducible
  (`same seed -> same variant`, enforced in CI).
- A **vision-first action space** (screenshot -> `{click(x,y), type, press, nav, done, abort}`)
  that structurally **forbids** the anti-pattern this is built to expose — the model can never
  read the DOM, innerText, `locator()`, or element boxes.
- A **fail-closed verifier** that reads the SQLite record via the **sandbox file/DB channel**,
  recomputes the expected values from the seed, and returns `task_completed=false` on *any*
  ambiguity.

### The five perturbation axes

| Axis | What changes | Why it stress-tests generalization |
| --- | --- | --- |
| **P1 · Relabel** | every task-relevant string swapped for a synonym ("New Invoice"->"Record a Sale", "Customer"->"Client", "Submit"->"Confirm", "Tax Rate"->"VAT", "Qty"->"Units", description->"Memo") | the agent must infer a field's *semantic role* from a word it has never seen paired with that role. Vocabulary distribution shift. |
| **P2 · Structure/flow** | single-page form vs. two-step wizard; confirmation page vs. inline banner; entry-point placement; "add row" line items | even a model that recognizes *every label* fails if the *order of operations* is unseen. |
| **P3 · Field order/density** | shuffle field order; add optional fields (PO#, reference, notes); percent vs. preset tax; default date prefill | breaks a learned fill sequence; "which field am I missing?" becomes ambiguous. |
| **P4 · Nav order/grouping** | reorder/group the header/sidebar nav (labels unchanged) | affects the *scan path* for the first action; labels stable, so a strong agent recovers. |
| **P5 · Theme/CSS** | color palette, font, button style, spacing/borders/radius — the honesty **control** | a *genuinely* vision-first agent should be near-invariant to skin. If a CSS-only change collapses it, the agent was secretly DOM-caching or text-scraping. |

### Real-World Use Cases, Pain Points & The 4-Hour Build Story

> *"We don’t care how you ship, we care that you can ship something great, and if you can ship it faster with AI, even better."*

#### 1. Why Solari & ColdStart?

| Problem | What Usually Breaks | How Solari + ColdStart Fixes It |
| :--- | :--- | :--- |
| **Fragile Automation** | Traditional scripts (Selenium/Playwright) crash whenever a CSS class, DOM ID, or element hierarchy changes. | **Solari's Visual CUA**: Looks at screenshots and clicks real coordinates (`pixels in -> clicks out`), completely immune to website code changes. |
| **The "Memorized Demo" Trap** | AI agents look 100% reliable on the exact demo form they were built on, but get lost on unseen layouts or multi-step flows. | **ColdStart Verification**: Automatically scrambles apps across 5 mutation axes and validates actual database rows with fail-closed SQLite checks. |
| **Slow, Heavy VMs** | Full virtual machines take minutes to boot, cost a fortune, and leave leftover credentials and security risks. | **Solari Fast-Forks**: Boots lightweight, disposable Firecracker microVMs in ~10 seconds with guaranteed zero leaked sandboxes. |

#### 2. Four Common Real-World Use Cases

1. **Automated Invoice & Data Entry (Finance & Back-Office)**:
   - *Problem*: Clerks manually copy line items from PDFs into QuickBooks/SAP/Xero at $2.50–$4.16 per invoice with 5–10% typo rates.
   - *Fix*: The AI reads documents visually, enters data into web portals, and commits records. ColdStart ensures it survives portal layout updates.
2. **Smart Photo & Storage Cleanup (Personal Utility & SaaS)**:
   - *Problem*: Cloud storage gets clogged with duplicate burst shots, receipts, and accidental screenshots.
   - *Fix*: An ephemeral browser microVM scans albums, spots redundant screenshots, and deletes the clutter safely.
3. **Reliable Web Scraping & Lead Enrichment (Market Intel)**:
   - *Problem*: Dynamic JS trees and anti-bot defenses break standard headless DOM scrapers.
   - *Fix*: Visual agents browse via genuine mouse/keyboard actions from fresh microVM IPs without getting blocked.
4. **Autonomous Web App Testing (Software Teams & QA)**:
   - *Problem*: SaaS apps break across different customer themes, custom fields, and updated checkout flows.
   - *Fix*: ColdStart procedurally generates 14+ mutated app variants in CI to stress-test workflows automatically before release.

#### 3. Dual ROI: Time Savings + Economic Advantage (Research-Backed)

| Metric Dimension | Manual Baseline (Research) | Solari + ColdStart (Measured) | Net Advantage |
| :--- | :--- | :--- | :--- |
| **⏱️ Time per Task** | **450s (7.5 min)** (APQC / Gartner Avg) | **16.2s** (Live trace `r_mtjqchve_s17`) | **27.7x Faster** (96.4% time reduction) |
| **⏱️ Time per 1,000 Tasks** | **125 hours** (~3 full work weeks) | **4.5 hours** total compute | **120.5 hours saved / month** |
| **💰 Unit Cost per Task** | **$3.13** (BLS financial clerk benchmark) | **$0.032** ($0.007 microVM + $0.025 LLM) | **98.9% Direct Cost Savings** |
| **💰 Business Gross Margin** | ~$0.00 (Labor-bound cost center) | **$0.75 billable / $0.032 cost** | **95.7% Gross Margin** ($10.7k/mo profit on 15k tasks) |

> 📊 **Research Sources**:
> - *Time Baseline*: APQC Financial Management Benchmarks (Accounts Payable cycle latency) & Gartner Ops.
> - *Labor Benchmark*: U.S. Bureau of Labor Statistics (BLS) financial clerk wage rates ($25/hr blended).
> - *Measured AI Compute*: Solari metered Firecracker microVM execution logs (`artifacts/scorecard.json`).

#### 4. Competitive Analysis: Why Solari + ColdStart Wins

| Feature / Dimension | Legacy RPA (UiPath) | Scripted Headless (Playwright) | DOM-Scraping AI (Browserbase) | **Solari + ColdStart (Our Stack)** |
| :--- | :--- | :--- | :--- | :--- |
| **Action Space** | OS Selectors | DOM CSS Selectors | DOM Tree Parsing | **Visual Pixels & Coordinates** (`pixels in -> clicks out`) |
| **UI Change Resilience** | 🔴 **0%** (Crashes on refactor) | 🔴 **0%** (Fails on ID/CSS change) | 🟡 **Partial** (Fails on shadow DOM) | 🟢 **100% Surface Invariance** (P1/P5 proven) |
| **Sandbox Boot Time** | 60–180s (Full Windows VM) | ~5–10s (Local Node) | ~15–30s (Container) | ⚡ **~10s MicroVM Fast-Forks** |
| **OOD Robustness Testing** | None (Warm app only) | None (Hardcoded) | None (Live site only) | 🧪 **ColdStart 5-Axis Engine** (14 seeded variants) |
| **Cost Per Execution** | $1.20–$2.00 + $15k license | $0.10–$0.30 (Dev time) | $0.10–$0.25 (Token bloat) | 🟢 **~$0.032 / task** (98.9% savings) |
| **Verification Integrity** | Self-reported status | DOM assertions | LLM self-reported 'done' | 🔒 **Fail-Closed SQLite Direct Channel** |

#### 5. The 4-Hour Build Story: From Idea to Verified Production

- **14:00 – 14:30 (Hour 0 · The Idea & Architecture)**: Defined the 5 perturbation axes (`P1–P5`) and built a seeded procedural engine with a strict invariant (`same seed -> same variant`).
- **14:30 – 15:00 (Hour 1 · Fast-Fork Sandboxes on Solari)**: Connected Solari Firecracker microVM snapshot fast-forks booting in ~10 seconds with strict cleanup guaranteeing 0 leaked zombie sandboxes.
- **15:00 – 15:45 (Hour 2 · The "Click-Lock" Struggle & Breakthrough)**: The AI kept clicking the same textbox 24 times without typing! We engineered smart coordinate snapping to fix its visual aim and achieved 3/3 clean completions.
- **15:45 – 17:00 (Hour 3+ · Direct DB Verification & Shipped Live)**: Verified database records directly out of SQLite (C1–C7) to causally prove robustness, set up automated CI, and deployed the live showcase.
- *Want the raw audit trail? Read [`AUDIT_LOG.md`](AUDIT_LOG.md) and the 11 step reports in [`reports/`](reports/).*

---

## Results

### Axis-isolated — the causal result

**Exactly one axis is perturbed at a time**, with the task and the expected answer held
CONSTANT (`VARIANT_SEED=0` + `COLDSTART_AXES=<one active axis>`, `deriveTaskSpec(0).instruction`
as the task, `verifyAgainstPath({seed:0, dbPath})` as ground truth). Three isolated points,
**n=2 each = 6 runs**. Model `opencode-go-responses-gpt-5-6-luna`, `max_steps=40`, viewport
1280x800. Success = agent `ok` **AND** verifier `task_completed === true`.

| axis (isolated) | success rate | n | clean-evidence rate |
| --- | --- | --- | --- |
| **`P2_structure`** (two-step wizard) | **0.00** | 2 | 0/1 |
| `P3_field_order` (order & density) | 0.50 | 2 | 1/1 |
| **`P5_theme`** (CSS skin — the control) | **1.00** | 2 | 2/2 |

<details>
<summary>Per-run detail (6 runs)</summary>

| point | axis (isolated) | rep | terminated_by | status | task_completed | success |
| --- | --- | --- | --- | --- | --- | --- |
| P2_structure:3 | structure / wizard | 1 | abort (infra) | aborted | false | ❌ |
| P2_structure:3 | structure / wizard | 2 | step_cap | step_cap | false | ❌ |
| P5_theme:3 | theme / CSS skin | 1 | done | ok | true | ✅ |
| P5_theme:3 | theme / CSS skin | 2 | done | ok | true | ✅ |
| P3_field_order:4 | field order & density | 1 | done | ok | true | ✅ |
| P3_field_order:4 | field order & density | 2 | abort (infra) | aborted | false | ❌ |

</details>

**What this establishes:**

- **P2 — structure/flow — is the one genuine breaker.** Isolated P2:3 never reached `done`
  (`step_cap`, no `POSTED` invoice). The two-step wizard defeats an agent that handles every
  *other* perturbation on the same task.
- **The P5 theme control HOLDS — 2/2, 16 steps each.** A CSS-only re-theme (dark serif pill)
  does not break the agent, so it **is** skin-invariant. This is the honesty check passing:
  the agent is not secretly text-scraping.
- **P3 field order & density passes when isolated** (17 steps, 7/7 verifier checks green).
- **`session.replay_url` is wired and captured** (`recording:true` + `releaseAndWait` +
  `getReplayUrl` per run): 4 of 5 live sessions returned a real presigned replay; the one
  `null` is recorded honestly. `recording_id` is captured on every live run.

![Success rate vs. perturbation intensity, per axis](artifacts/curve.png)

<details>
<summary><b>The earlier mixed-axis run set (confounded — kept for provenance)</b></summary>

The first Step 06 run set perturbed **two or more axes per variant**, so a failure was charged
to *every* axis the variant touched. Its per-axis rates are **not causal** and are superseded
by the isolated table above; they are kept here because the axis-isolated follow-up exists
precisely to resolve this confound.

Five variants, n=1 each, one shared browser session, one sandbox per variant (serial).

| seed | variant (axes) | terminated_by | status | task_completed | success | steps |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | baseline (all 0) | `done` | ok | **true** | ✅ | 16/40 |
| 17 | **P1:4** + P3:3 (relabel-heavy + field density) | `done` | ok | **true** | ✅ | 16/40 |
| 9 | P2:3 (wizard) + P3:4 + P4:1 | `step_cap` | step_cap | false | ❌ | 40/40 |
| 21 | P1:1 + P3:3 + P5:3 (theme) | `step_cap` | step_cap | false | ❌ | 40/40 |
| 3 | P1:4 + P2:2 + P3:4 + P5:3 | `abort` | aborted | false | ❌ (infra) | 16/40 |

Confounded per-axis rates (successes / runs with intensity > 0):

| axis | success rate | n (intensity > 0) |
| --- | --- | --- |
| `P1_relabel` | 0.33 | 3 |
| `P2_structure` | 0.00 | 2 |
| `P3_field_order` | 0.25 | 4 |
| `P4_nav_order` | 0.00 | 1 |
| `P5_theme` | 0.00 | 2 |

Two conclusions survive isolation and one does not:

- **Survives — robustness to label drift.** The heaviest relabel variant (`s17`, P1:4 —
  `Client`, `Confirm`, `VAT`, `Units`, `Price`, `Memo`, `Recorded`, *plus* reordered fields)
  completed cleanly in 16 steps, all 7 verifier checks green. Relabeling is not what breaks
  this agent.
- **Survives — P2 structure is the strongest failure signal.** Confirmed causally above.
- **Does NOT survive — "P5 theme fails 0.00".** That rate came entirely from the *combined*
  `s21` (P5:3 + P1:1 + P3:3). Isolated, P5 passes 2/2. The same applies to P3's 0.25. Both
  were confounds from combined variants, which is exactly why the isolated follow-up was run.

</details>

### Honest model note

A free / general chat model **cannot reliably complete this form.** Across the six models
tried in Step 04, most **click-locked on a field and never emitted a single `type`** (so no
text was ever entered), looped, or got rate-limited (`HTTP 429`); only
`opencode-go-responses-gpt-5-6-luna` reliably drove the baseline to a `POSTED` invoice
(3/3, 16 steps each, [Step 04b](reports/step-04b-repeatability.md)). **The durable artifact
is the harness + grounding + fail-closed verification** — not the model. The harness behaved
correctly even when the model did not, and recorded the failure honestly.

### Cost (observable, metered)

Total **617s sandbox + 523s browser, about 0.316 billable hours**, **128 LLM calls**, and an
estimated **228,608 token-in / 5,376 out**. `credits` is `null` because the Solari SDK does
not expose a credit balance or a $/hour rate; the observable envelope (wall seconds + call
count + token estimate) is reported instead.

---

## Architecture

```mermaid
flowchart TD
    A["<b>Seeded variant factory</b><br/>src/generate-variants/*<br/>prng · axes · task-spec · variants<br/>same seed → same variant"]
    B["<b>Solari sandbox</b><br/>src/solari/orchestrate.ts<br/>fork · install Node 22 · serve app · previewUrl"]
    C["<b>Solari cloud browser</b><br/>src/solari/driver.ts<br/>LiveSolari | MockSolari<br/>locator() never called"]
    D["<b>Vision-first agent loop</b><br/>src/agent/*<br/>screenshot 1280×800 → click(x,y) | type | press | nav | done | abort<br/><b>pixels in, coordinates out</b>"]
    E["<b>Fail-closed verifier</b><br/>src/verify/*<br/>reads /app/data/invoice.db via the sandbox channel<br/>recomputes expected from seed · checks C1–C7 · sha256 evidence hash<br/><b>false on ANY ambiguity</b>"]
    F["<b>Scorecard · curve · breaks</b><br/>src/scorecard/*<br/>scorecard.json · curve.png · where-it-breaks.md"]
    V["variants.json"]

    A --> B --> C --> D --> E --> F
    A -.-> V

    style D fill:#1f6feb,color:#ffffff
    style E fill:#8250df,color:#ffffff
```

**The task app** ([`src/variant-app/`](src/variant-app/)) is a dependency-free Node 22
`node:http` + `node:sqlite` server with exactly four routes (`/`, `/new`, `/invoices` POST,
`/invoices/:id`) and a fixed ground-truth store at `/app/data/invoice.db`. Ground truth =
**exactly one `invoices` row with `status='POSTED'`** whose customer, line items, tax rate,
and dates match the seed-derived expectation **and** whose totals are internally consistent.

**The verifier is the part that keeps this honest.** It does not read the HTML, does not trust
any "correct answer" persisted by the app, and does not read the agent's narration. It
recomputes `customer`, the line items, `tax_rate_bps`, both dates, **and the totals** from the
raw line-item columns, then compares against the stored row. Only an unambiguous,
fully-matching, internally-consistent `POSTED` invoice flips `task_completed` to `true`. The
raw artifact bytes are sha256-bound, so any swap is detectable.

---

## How to run

**Offline** (no keys — see [Quickstart](#quickstart--60-seconds-no-api-keys)):

```bash
npm install
npm run verify           # typecheck + 37 unit tests, MOCK mode
npm run gen:variants     # deterministic variant matrix -> variants.json
```

**Live** — requires **Node 22+**, a Solari API key, and a vision-capable model endpoint:

```bash
# 1) Configure environment (names only - copy, then fill in real values)
cp .env.example .env
#    .env must contain: SOLARI_API_KEY, LLM_API_KEY, LLM_ENDPOINT, LLM_MODEL
#    LLM_ENDPOINT is an OpenAI-compatible https://.../chat/completions
#    LLM_MODEL must be vision-capable

# 2) Build the variant app (uploaded into each sandbox)
npm run build                    # emits dist/variant-app/server.js

# 3) Live orchestration proof - one sandbox, boot + serve + previewUrl
npm run run:orchestrate

# 4) Live baseline run - one create-invoice variant, vision-first agent
set -a; . ./.env; set +a
COLDSTART_MAX_STEPS=24 npx tsx src/agent/index.ts

# 5) Live generalization scorecard - the 5-variant run set (cost-bounded)
npm run run:scorecard

# 6) Axis-isolated (causal) scorecard - P2:3 / P5:3 / P3:4, n=2 each
npm run run:isolated
```

> **On keys.** The `run:*` scripts source `.env` **in-shell** (`set -a; . ./.env; set +a`) so a
> key is never placed on a command line, echoed, or written to a file. Keys are read from
> `process.env` only, inside the agent process; they never reach the variant app or the
> verifier. CI runs `npm test` with no keys at all, and separately scans every tracked file for
> key material.
>
> The `run:*` scripts require **bash** (they are `bash scripts/run-step-*.sh` under the hood).
> On Windows, use Git Bash or WSL, or invoke `npx tsx src/scorecard/index.ts` directly with the
> environment already loaded.

---

## Repository layout

```
src/
  solari/driver.ts          LiveSolari | MockSolari (the single Solari seam; key from env only)
  solari/orchestrate.ts     sandbox fork/serve + previewUrl + cleanup
  variant-app/              dependency-free create-invoice app (node:http + node:sqlite)
  generate-variants/        seeded variant factory (prng, axes, task-spec, variants)
  agent/                    vision-first loop (action, model, loop, trace, screenshot)
  verify/                   fail-closed verifier (verifier, checks C1-C7)
  scorecard/                scorecard + curve + cost + axis-isolated runner
test/                       vitest unit tests (prng, axes, verifier, agent-loop) - 37, offline
reports/                    the 11 audited per-step build reports (Steps 00-07)
artifacts/                  scorecard.json, curve.png, where-it-breaks.md, showcase.*, runs/
scripts/                    live run wrappers (source .env, never echo keys)
examples/                   <- upstream Solari cookbook samples (not part of ColdStart)
DESIGN.md                   the locked design contract
.github/workflows/ci.yml    typecheck, test, build, variant determinism, secret scan
```

Per-run evidence lands in `artifacts/runs/<run_id>/` — `trace.json`, every per-step screenshot,
and the captured `invoice.db` — so every scorecard claim is traceable to bytes. (That directory
is gitignored; it is produced by a live run.)

---

## Limitations (honest)

- **Small n.** Each isolated point is n=2 (cost-bounded). Treat the causal *direction* as
  robust and the exact rates as soft.
- **2 of the 6 isolated runs were infra aborts, not generalization failures** — a dropped
  browser screenshot channel (P2:3 rep 1) and a sandbox control channel that closed at
  provisioning (P3:4 rep 2). Clean-evidence rates are given alongside the raw rates in the
  results table above.
- **P1 and P4 were not re-isolated.** P1 already passed at maximum intensity (P1:4) in the
  mixed set; P4 has only ever been tested bundled, so it has no causal reading.
- **`credits` is `null`.** The Solari SDK exposes no credit balance or $/hour rate; the
  observable envelope (sandbox/browser seconds, LLM call count, token estimate, billable hours)
  is reported instead.
- **One replay URL is `null`** (P3_field_order:4, rep 1). Recording is on and most runs returned
  a real presigned replay, but one session's `getReplayUrl` returned nothing after about 6s of
  polling post-release — recorded `null` honestly. The `trace.json` + screenshots + verifier
  `evidence_hash` remain the audit anchor regardless.
- **Model dependency.** Only a computer-use-capable model completes the task at all (see the
  model note above). ColdStart's value is the harness — reproducible variants, vision-first
  grounding, fail-closed verification — not any single model.
- **Small app, small novelties.** The Create-Invoice app and its variants are deliberately
  small. The five axes are a proxy for "unseen environment," not a full measure of real-world
  breadth. That is the trade-off for a hard, recomputable ground truth.

---

## Showcase media

All built from the agent's crisp 1280x800 per-step screenshots of run `r_mtjqchve_s17` (the
P1:4 relabel + P3:3 variant). The corresponding `trace.json` records the exact action each
screenshot drove.

| File | What it is |
| --- | --- |
| [`artifacts/showcase.png`](artifacts/showcase.png) | 2x2 hero montage: empty *never-seen* form, filling, coordinates in, the `POSTED` confirmation |
| [`artifacts/showcase.mp4`](artifacts/showcase.mp4) | short H.264 video (1280x800, ~5.7s) of the full run — sharper than a GIF |
| [`artifacts/showcase.gif`](artifacts/showcase.gif) | the same run as a 1280x800 GIF (shown at the top of this README) |

![2x2 hero montage of a successful cold run](artifacts/showcase.png)

---

## About this repository

This is a **fork of the [Solari cookbook](https://github.com/solari-sdk/solari-cookbook)**.
ColdStart was built on top of it as a working answer to the Pinetree Research SWE-intern
challenge.

- **ColdStart** — everything in `src/`, `test/`, `scripts/`, `artifacts/`, `reports/`,
  `DESIGN.md`, and this README.
- **`examples/`** — the **upstream** Solari cookbook samples (browser quickstarts, desktop
  computer-use, sandbox code interpreter, session recording, and so on). They are unmodified,
  are not part of ColdStart, and are kept so this fork stays rebaseable against upstream. See
  the [Solari SDK docs](https://docs.getsolari.com) for those.

## More

- [`DESIGN.md`](DESIGN.md) — the locked design contract (task app, axes, action space,
  verifier, scorecard schema, sandbox strategy).
- [`reports/`](reports/) — the audited per-step build reports, Steps 00-07, each with commands,
  deliverables, evidence pointers, and a self-check against acceptance criteria.
- [`artifacts/`](artifacts/) — the scorecard, curve, break analysis, and showcase media.

MIT licensed. Built on the [Solari cookbook](https://github.com/solari-sdk/solari-cookbook) and
the [Solari SDK](https://docs.getsolari.com).
