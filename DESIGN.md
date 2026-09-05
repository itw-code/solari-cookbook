# ColdStart — DESIGN.md (Step 01 · Design Lock)

> **Status: LOCKED.** This document is the contract that Steps 02–06 build against.
> No code exists yet. Any build step that "improvises" against this doc is a defect
> and routes back for rework. All paths below are **relative to the working repo
> root** `solari-cookbook/` (the forked `solari-sdk/solari-cookbook`).

---

## 0. What ColdStart is (one paragraph)

ColdStart measures **zero-shot generalization**: it procedurally generates
never-before-seen variants of a small task app, lets a **vision-first** agent complete
the same task *cold* in each one (pixels in, coordinates out, with harness-side click
grounding), verifies the
outcome against ground truth via the **DB/files channel** (never the agent's narration),
and emits a **generalization scorecard** (success % by perturbation axis, a
success-vs-novelty curve, replay links, cost). It operationalizes Pinetree's actual
thesis — generalization to unseen environments, *not* reliability on a known app — which
is the one claim no other applicant touched.

**Decisions locked in this file:** the task app (Create-Invoice), 5 perturbation axes,
the vision-first action space, the fail-closed verifier contract, the scorecard schema,
TypeScript + source layout, the sandbox/snapshot strategy, and the risk register.

> This step produces **no software**. It is a design doc. `Mode: N/A (design, no code)`.

---

## 1. TASK APP — Create-Invoice (deskless billing)

### Decision

**One concrete enterprise CRUD workflow: "create an invoice."** Server-rendered HTML,
single store = SQLite, ground truth = a `POSTED` invoice row + its line items.

### Why invoice over "file support ticket"

The task requires a **hard, independently-computable ground-truth record**. A support
ticket's "correct answer" is fuzzy (free-text description, no arithmetic). An invoice has
**deterministic arithmetic**: line items → subtotal → tax → total. The verifier can
*recompute* the totals from the raw line-item columns and confirm the stored record is
internally consistent — so neither a buggy app nor a guessed form submission can slip a
wrong total past it. That is a genuinely hard ground truth, and it reads as the kind of
boring, enterprise, "keep-it-simple" workflow Pinetree values.

### Ground-truth artifact (SQLite)

Fixed guest path: `/app/data/invoice.db`. Created fresh by `ensureSchema()` on every fork
boot (so each variant sandbox starts **empty** — no leftover invoice).

```sql
CREATE TABLE invoices (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_no    TEXT    NOT NULL UNIQUE,          -- auto: INV-YYYY-####
  customer      TEXT    NOT NULL,
  status        TEXT    NOT NULL CHECK (status IN ('DRAFT','POSTED')),
  subtotal_cents INTEGER NOT NULL,
  tax_cents     INTEGER NOT NULL,
  total_cents   INTEGER NOT NULL,
  tax_rate_bps  INTEGER NOT NULL,                 -- basis points: 800 = 8%
  invoice_date  TEXT    NOT NULL,                 -- ISO yyyy-mm-dd
  due_date      TEXT    NOT NULL,                 -- ISO yyyy-mm-dd
  created_at    TEXT    NOT NULL
);

CREATE TABLE invoice_items (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id      INTEGER NOT NULL REFERENCES invoices(id),
  position        INTEGER NOT NULL,
  description     TEXT    NOT NULL,
  qty             INTEGER NOT NULL CHECK (qty > 0),
  unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents >= 0),
  line_total_cents INTEGER NOT NULL               -- qty * unit_price_cents
);
```

**"Task done" = exactly one `invoices` row with `status='POSTED'`** whose customer,
line items, tax rate, and dates match the seed-derived expectation **and** whose totals
are internally consistent. A `DRAFT` row (filled but never posted) or a row with wrong
values is **not** done.

### Minimal UI surface (server-rendered, no client JS)

Four routes, all server-rendered HTML. No SPA, no client framework, no headless build.

| Route | Method | Purpose | Perturbable surface |
| --- | --- | --- | --- |
| `/` | GET | Invoice **list** (empty on a fresh variant) + the entry point for "new" | entry-point label + nav position |
| `/new` | GET | **Form** page (customer, dates, line items, tax) | field order/labels, field count, single vs. multi-step |
| `/invoices` | POST | Validate → insert (transaction) → set `POSTED` → assign `invoice_no` → 302 | submission button label |
| `/invoices/:id` | GET | **Confirmation** page (invoice_no, customer, items, totals, "Invoice created") | separate page vs. inline confirmation |
| `/healthz` | GET | Readiness probe for orchestration | none (fixed) |

The form fields: `customer`, `invoice_date`, `due_date`, `tax_rate` (as a % input or a
select preset), and line items `description`, `qty`, `unit_price` (1 row by default,
add-row for more). `notes` is optional and **not** verified.

### Language / framework for the app

**Node.js 22 + built-in `node:http` + built-in `node:sqlite`.** Zero third-party runtime
dependencies. Justification: it is the simplest thing that runs in a Solari sandbox and
produces a real SQLite record — no web framework, no ORM, no native module, no
`--experimental-sqlite` flag (verified working on Node 22.23.1). It is also **TypeScript**,
so the whole repo stays one language, compiled by one tsconfig (see §6). The base snapshot
prepares Node 22 + the compiled app (Step 03); the app serves on `:3000`.

### Task spec (what the agent is told) — deterministic per seed

The **seed** drives both the variant *and* the task spec. `seed → (perturbation params,
task spec)` via a pure function (§2). The agent receives a natural-language instruction —
the same thing a human would hand a new operator:

```
[Run seed=…] Open the billing app and create an invoice for customer
"ACMECORP" with one line item: description "Consulting", qty 3, unit price
$120.00, tax rate 8%, invoice date 2026-10-01, due date 2026-10-31.
Leave everything else at its default. Submit and confirm the invoice is
created, then report done.
```

The exact customer name, line-item values, and dates are derived from the seed (never
hardcoded, never revealed as "the answer"), so the agent cannot memorize them and the
account can't cheat by matching a fixed fixture. The harness, not the app, renders this
instruction; it is **never** drawn into the HTML and **never** sent to the verifier as a
trusted value (the verifier recomputes expected independently).

---

## 2. PERTURBATION AXES — the "unseen environment factory"

### Determinism rule

Every axis is a **pure, seeded** function of the variant seed. `sameSeed → same variant`.
Implementation: a single seeded PRNG (e.g. `mulberry32`); each axis draws from a
**domain-separated sub-stream** (`stream = prng(seed ^ hash(axisId))`) so axes don't
interfere and adding an axis can never perturb another axis's output. Axis **intensity** is
an integer `k ∈ [0, K_max]`; `k=0` is always the canonical baseline (the un-perturbed
`seed=0` app). This is what makes the matrix auditable/reproducible.

### The axes, ranked HARDEST first

> Ranking principle: the axis that can break the agent *before it can even recognize the
> target* is hardest. Relabeling removes recognition entirely; structural reorder changes
> the *procedure*; theme/CSS is (for a genuine vision agent) a near-control.

### P1 — Semantic relabeling & copy drift  (HARDEST)
- **What changes:** every task-relevant string is swapped for a synonym / different idiom:
  - "Create Invoice / New Invoice / Add Invoice" → "New Bill", "Generate a Charge", "Record a Sale"
  - "Customer" → "Client", "Billed To", "Account", "Bill To"
  - "Submit / Save / Create / Post" → "Confirm", "Record", "Done", "Finalize"
  - "Tax Rate / Tax %" → "VAT", "Sales Tax", "Tax"
  - "Qty / Unit Price" → "Units", "Rate", "Amount per Unit"
  - "Description" → "Detail", "Memo", "Item"
  - Confirmation heading "Invoice Created" → "Recorded", "Saved", "Posted!"
- **Intensity `k`:** fraction of task-relevant labels renamed. `k=2`≈25% … `k=K_max`≈90%.
- **Why it matters for generalization:** the agent must go from seeing a word on a pixel to
  inferring its semantic role. This is the exact vocabulary distribution-shift a zero-shot
  agent fails on — a model that overfit to "Submit" stalls on "Finalize." It is the
  single axis that most directly stress-tests the "an agent you've never seen this app
  before" claim.

### P2 — Structure & flow reorder  (VERY HARD)
- **What changes:** the *shape* of the task, not its labels.
  - Single-page form ↔ **two-step wizard** (Step 1 "customer + dates", Step 2 "line items + tax").
  - Confirmation as a **separate page** ↔ an **inline** success block/banner on the same page.
  - Entry point placed top-bar / sidebar / floating action button / mid-body.
  - Line items as a single row, vs. a table you grow via an "Add row" button.
- **Intensity `k`:** `k=1` minor layout rearragement, `k=2` two-step wizard, `k=3` wizard
  + inline confirmation + add-row line items, `…` up to full restructure.
- **Why it matters:** even a model that **correctly recognizes every label** can fail,
  because the *order of operations* (which page holds which field, whether you must click
  "Next") was never seen. This is true novel-environment structural shift and it breaks
  procedurally-learned step scripts hard.

### P3 — Form field-order & density  (HARD)
- **What changes:** shuffle field order in the form (`customer` ↔ `invoice_date` ↔ `due_date`);
  change the order of `description`/`qty`/`unit_price`; add **optional** fields (`PO number`,
  `reference`, `notes`), vary whether tax is a select-preset vs. a raw % box; vary default
  date prefill (blank vs. today).
- **Intensity `k`:** number of fields shuffled / added. `k=0` baseline, `k=K_max` full
  reorder + 2 optional fields + preset-tax.
- **Why it matters:** agents fill in a learned sequence; reordering forces re-scanning and
  re-planning per field, and optional/moved fields make "which am I missing?" ambiguous.

### P4 — Navigation order & grouping  (MODERATE)
- **What changes:** reorder / re-group the header/sidebar nav (Invoices, New, Reports),
  possibly nesting "Invoices" under a menu, moving the "new" entry relative to the list.
  Labels stay the same.
- **Intensity `k`:** number of nav items moved / grouped.
- **Why it matters:** affects the scan path for the *first* action (find the create entry),
  but because labels are stable a strong vision agent can still recover. Lower risk than
  P1/P3; good for separating "recognize" vs. "locate" failures.

### P5 — Theme / CSS skin  (EASIEST — the control axis)
- **What changes:** color palette (light/dark, brand hue), font family/size, button style
  (solid vs outline vs pill), spacing, borders, radius. *(Stretch, Step 06 optional: swap
  CSS framework entirely — e.g. generic→Bootstrap→Tailwind-classes.)*
- **Intensity `k`:** magnitude of visual delta up to a full re-theme.
- **Why it matters:** a *genuinely* vision-first agent should be largely invariant to skin.
  If a **CSS-only** change collapses the agent's success rate, that is a powerful,
  embarrassing signal that the agent was secretly DOM-caching or text-scraping — exactly
  the anti-pattern Pinetree forbids. So P5 is the honesty control: it must stay near-baseline.

**Variant matrix (Step 02):** ≥10 variants across P1–P5, each `variant_id` =
`inv__s<seed>__P1:<k>__P2:<k>__P3:<k>__P4:<k>__P5:<k>`. Same seed → identical variant and
task spec (the Step 02 audit re-runs the generator twice on one seed and diffs output).

---

## 3. AGENT ACTION SPACE — vision-first loop contract

### Doctrine (non-negotiable)

The agent is **pixels in, coordinates out.** It may observe the rendered page **only** as an
image, and may act **only** through the bounded action set below. It is **explicitly
FORBIDDEN** from using any DOM-selector / element-handle / accessibility-tree access. This is
Pinetree's vision-first moat and the entire point of the submission. Note: the underlying
Solari browser is Playwright-compatible (`patchright-core`) and *does* expose `locator()` —
the harness simply **never calls it**. We make this a hard rule, not a preference.

**Allowed observation channels (exactly three):**
1. `page.screenshot()` → PNG bytes (the current viewport, rendered).
2. The natural-language task instruction (from the seed-derived task spec).
3. A compact textual trace of prior actions `[{step, action, ok}]` (for state; never DOM text).

Everything else — `innerText`, `locator`, `$eval`, `accessibility snapshot`, response bodies,
getByRole, HTML source, element bounding boxes returned to the model — is **verboten**.

### Bounded action set (closed union)

```ts
type Action =
  | { kind: "click"; x: number; y: number }  // click at viewport CSS coords
  | { kind: "type";  text: string }           // keystrokes into the CURRENTLY FOCUSED element
  | { kind: "press"; keys: string }           // e.g. "Enter" | "Tab" | "Escape"
  | { kind: "nav";   url: string }            // page navigation (same-origin; see note)
  | { kind: "done";  }                        // agent believes task is complete (NOT success)
  | { kind: "abort"; reason: string }         // give up / stuck / cost ceiling
```

**Key semantics:**
- **`type` targets the focused element.** The agent must `click` a field first to focus it,
  then `type`. This mirrors real computer-use and keeps the space tiny — no need for the
  model to emit per-character coordinates. The harness maps `type` → `page.keyboard.type(text)`.
- **`click`/`nav`** map to `page.mouse.click(x,y)` / `page.goto(url)`.
- **`nav`** must be same-origin; build the URL with `new URL(path, basePreviewUrl)` — never
  string-concat — because the Solari `previewUrl` may already carry a query string (§7).
- **`done` is a claim, not a result.** The loop stops and the **verifier** decides true/false.
  `done` never short-circuits to success.
- **Coordinate stability:** the harness pins a fixed viewport (e.g. `1280×800`, no device
  scale factor), disables CSS animations/transitions, screenshots `clip = full viewport`,
  and keeps the app single-viewport / no overflow, so the model's `(x,y)` remains stable.

### Model call & credentials

- **Multimodal** (vision + text). Endpoint/key/model via **environment variables only** —
  never hardcoded, never written to a file:
  - `LLM_API_KEY` (scoped to the **agent** process)
  - `LLM_ENDPOINT` (OpenAI-compatible `https://…/chat/completions`)
  - `LLM_MODEL` (a vision-capable model id)
- Input per turn: `{ task, image: <base64 PNG>, history: Action[], step }`.
- Output: `{ action: Action, rationale?: string }` — via JSON tool-calling/structured output
  when the endpoint supports it, else a strict JSON envelope the harness parses
  (`{"kind":"click","x":123,"y":456}`), with a single one-shot repair on a parse failure.
- **Contamination guards:** the agent sees the task instruction + pixels only. It never sees
  the variant seed, the axis intensities, the `variants.json`, the expected DB serialization,
  or the verifier's checks. `LLM_API_KEY` is injected only into the agent (`loop.ts`) — the
  variant app, the verifier, and the orchestrator never import or receive it.

### Step cap & terminal conditions

- **Step cap:** `COLDSTART_MAX_STEPS` (default **30** turns). Exceeded → terminal outcome
  `step_cap`.
- **`done`** → stop loop → hand to verifier (outcome is whatever the verifier says).
- **`abort`** → terminal `aborted`; verifier skipped.
- **Automatic abort:** a step exceeding `COLDSTART_STEP_TIMEOUT_MS` (default 45s) or the
  run exceeding the session budget.
- **`stuck`:** ≥3 consecutive identical clicks with no new screenshot → deprecated to
  `stuck`.

**Failure taxonomy (draft for Step 04):** `ok` / `verifier_fail` (done but DB wrong) /
`stuck` / `step_cap` / `aborted`.

### Driver seam (from Step 00 — unchanged)

The harness talks to Solari **only** through the `SolariDriver` interface already shipped in
`src/solari/driver.ts` (`LiveSolari` / `MockSolari`) — `launchBrowser()`, `createSandbox()`,
`shutdown()`. Steps 03/05 additionally use the *returned* Sandbox/BrowserSession objects'
methods directly (`files`, `commands.run`, `previewUrl`, `snapshot`, `kill`, `page.screenshot`,
`page.mouse`, `page.keyboard`, `page.goto`). **No change to the driver signature** is needed.

---

## 4. VERIFIER CONTRACT — independent ground-truth check

The verifier decides **whether the task actually happened**, reading the SQLite record via the
**sandbox FILE/DB channel** — never the agent's narration, never the page DOM, never the
`done` claim.

### Return shape

```ts
interface VerifyResult {
  task_completed: boolean;            // THE signal the scorecard uses (fail-closed)
  field_errors:   FieldError[];       // [{field, expected, actual, severity}]
  checks_run:     CheckResult[];      // [{check, passed, detail}]
  evidence_hash:  string;             // sha256 over the raw artifact bytes read
}
type FieldError  = { field: string; expected: string; actual: string; severity: "critical"|"major"|"minor" };
type CheckResult = { check: string; passed: boolean; detail: string };
```

### How expected vs. actual is established

- **Expected** values are **recomputed from the run's seed** by the same pure function that
  produced the task spec (`expected = deriveTaskSpec(seed)`). The verifier does **not** read
  the HTML, does **not** trust any "correct answer" persisted by the app (the app could lie),
  and does **not** read the agent's narration. It recomputes `customer`, line items (desc/qty/
  unit price), `tax_rate_bps`, `invoice_date`, `due_date`, **and** recomputes the totals from
  raw line-item columns.
- **Actual** values are read from `/app/data/invoice.db` via the sandbox channel: a read-only
  `sqlite3` SELECT over `sandbox.commands.run("sqlite3", { args: […] })`, **or** the raw DB file
  bytes via `sandbox.files`. For offline/Mock, a stored fixture path. Because each variant fork
  boots a **fresh empty DB**, existence is unambiguous.
- `task_completed` = **every critical check passes**, and defaults to `false` on any error.

### Checks (critical set)

| # | Check | Pass condition |
| --- | --- | --- |
| C1 | **Existence** | `SELECT count(*) FROM invoices WHERE status='POSTED'` `== 1` |
| C2 | **Customer** | `customer` == expected `customer` |
| C3 | **Line items** | item count + each `(description, qty, unit_price_cents)` == expected, in order |
| C4 | **Tax rate** | `tax_rate_bps` == expected |
| C5 | **Dates** | `invoice_date` and `due_date` == expected |
| C6 | **Total consistency** | `subtotal_cents == Σ(qty×unit_price_cents)`, `tax_cents == round(subtotal×tax_rate_bps/10000)`, `total_cents == subtotal+tax` *(recomputed, never trusted)* |
| C7 | **Invoice no** | `invoice_no` present, non-empty, unique, matches `^INV-\d{4}-\d{4}$` |

A missing/extra row, a `DRAFT`-only row, a wrong field, or inconsistent totals → the
corresponding check fails with the expected/actual captured in `field_errors`.

### Negative tests (fail-closed) — ≥2 required, we lock 4

These are unit tests in Step 05 (`test/verifier.spec.ts`). In each, the agent "claims"
success and the verifier **must return `task_completed:false`**:

- **NEG-1 · empty DB:** agent signals `done`, but the DB has **zero** `POSTED` rows.
  → `task_completed:false`; C1 fails; `field_errors: []` (nothing to compare).
- **NEG-2 · wrong values:** a `POSTED` row exists but `customer` / `qty` / `unit_price` /
  `tax_rate_bps` ≠ expected (e.g. "ACME Co." vs "ACMECORP", qty 2 vs 3), or the stored total
  disagrees with the recomputed total. → `task_completed:false`; `field_errors` populated;
  C6 may also fail.
- **NEG-3 · never posted:** a `DRAFT` row exists (form filled, submit never fired / failed).
  → `task_completed:false` (no `POSTED` row).
- **NEG-4 · seeded mismatch / cross-run:** a row matches a **different** seed's expectation but
  not this one, or more than one `POSTED` row exists (double-submit / contamination).
  → `task_completed:false`.

**Fail-closed principle:** on *any* ambiguity — DB unreachable, artifact unreadable, parse
error, unsanitized query, zero rows, extra rows, missing file — the verifier returns `false`.
Only an unambiguous, fully-matching, internally-consistent `POSTED` invoice flips it `true`.

### Evidence binding & reproducibility

`evidence_hash = sha256(<raw artifact bytes read via the channel>)` is written into the run
record, so a later re-run over the same artifact reproduces the identical verdict and any
artifact swap is detectable. The verifier accepts **either** (a) a live sandbox handle (live
runs) **or** (b) a stored local `invoice.db` path (re-runs / Mock fixtures), satisfying the
Step 05 acceptance criterion "I can re-run the verifier against a stored DB file and reproduce
the verdict."

---

## 5. SCORECARD SCHEMA

JSON emitted by Step 06 (`src/scorecard/build.ts`) → `artifacts/scorecard.json`.

```jsonc
{
  "schema_version": "1.0",
  "generated_at": "2026-09-02T00:00:00Z",
  "task_app": "create-invoice",
  "config": { "max_steps": 30, "viewport": "1280x800", "n_runs_per_point": 3, "mode": "LIVE|MOCK" },

  "variant": {
    "variant_id": "inv__s0__P1:2__P2:1__P3:0__P4:0__P5:0",
    "seed": 0,
    "intensity_by_axis": { "P1_relabel": 2, "P2_structure": 1, "P3_field_order": 0, "P4_nav_order": 0, "P5_theme": 0 }
  },

  "runs": [
    {
      "run_id": "r_9b2f…",
      "variant_id": "inv__s0__…",
      "seed": 0,
      "intensity_by_axis": { "…": 0 },
      "agent": { "model": "<LLM_MODEL>", "steps_taken": 17, "max_steps": 30, "terminated_by": "done|abort|stuck|step_cap" },
      "outcome": {
        "status": "ok|verifier_fail|stuck|step_cap|aborted",
        "task_completed": false,
        "action_trace_path": "artifacts/runs/r_9b2f…/trace.json",
        "verifier": { "task_completed": false, "field_errors": [], "checks_run": [], "evidence_hash": "sha256:…" }
      },
      "session": {
        "replay_url": "https://replay.getsolari.com/…",
        "recording_id": "rec_…",
        "sandbox_id": "…",
        "snapshot_id": "…",
        "fixture_path": "fixtures/mock-sandbox-1/"   // MODE:MOCK only
      },
      "cost": {
        "credits": 0.42, "hours": 0.14,
        "sandbox_seconds": 500, "browser_seconds": 320,
        "model_tokens_in": 4500, "model_tokens_out": 800,
        "model_request_count": 17
      }
    }
  ],

  "success_by_variant": { "inv__s0__…": 0.67, "inv__s1__…": 1.0 },

  "success_by_axis": { "P1_relabel": 0.33, "P2_structure": 0.5, "P3_field_order": 0.75, "P4_nav_order": 0.8, "P5_theme": 1.0 },

  "generalization_curve": [
    { "axis": "P1_relabel", "intensity": 0, "success_rate": 1.0, "n_runs": 3 },
    { "axis": "P1_relabel", "intensity": 1, "success_rate": 0.67, "n_runs": 3 },
    { "axis": "P1_relabel", "intensity": 2, "success_rate": 0.33, "n_runs": 3 }
  ],

  "cost": {
    "total_credits": 12.4, "total_hours": 4.1,
    "by_variant": { "inv__s0__…": { "credits": 1.2, "runs": 3, "sandbox_seconds": 1500, "browser_seconds": 960 } },
    "by_axis": { "P1_relabel": { "credits": 4.0, "runs": 9 } }
  },

  "where_it_breaks": [
    { "axis": "P1_relabel", "intensity": 2, "variant_id": "inv__s9__…", "failure_mode": "verifier_fail: never clicked 'Finalize'" }
  ]
}
```

### Definitions

- **A variant is a SUCCESS iff `outcome.status ∈ {ok} AND verifier.task_completed === true`.**
  The agent's `done`/self-report is **never** the success signal.
- **`success_by_axis[axis]`** = successes / total runs across that axis (all intensities).
- **`generalization_curve[axis][intensity]`** = successes / runs at that exact (axis, intensity).
  **Intensity is an integer per axis (0..K_max)** — this is what makes the curve meaningful
  and the x-axis ordinal. Use ≥3 seeds per (axis, intensity) point (n≥3), serial within the
  Free-tier concurrency limit.
- **`session.replay_url`** from Solari session recording (`recording:true`) + ids so every
  scorecard claim is traceable to a real recording. In Mock mode, `fixture_path` stands in.
- **`cost`** per run variant captures Solari credits + hours (Solari bills per hour) and
  granular sandbox/browser seconds + model tokens, so the final accounting is complete. All
  resources are `kill()`ed and reflected in a cleanup log.

---

## 6. LANGUAGE & STRUCTURE — TypeScript, locked

### Decision

**TypeScript** for the entire harness *and* the variant app. Justification: it is consistent
with the shipped `src/solari/driver.ts` (Step 00) and the cookbook's TS examples; the two
SDKs first-class ship TS types; and the verifier/scorecard contracts (where type-safety
matters most — a wrong field name silently corrupts a scorecard) benefit directly from a
strict `tsc`. There is no strong reason for Python in the *harness* — the cookbook's Python
examples are guest/agent scripts, not the control plane.

### Root `package.json` + `tsconfig.json`: **YES — add now (minimal)**

Step 00 flagged the packaging seam (the driver only compiles in a throwaway env with the SDK
deps). Adding a minimal root manifest now unblocks Steps 02/03 so they can `npm install` +
`tsc` immediately. It stays minimal:

- `package.json`: `"private": true`, `"type": "module"`; `dependencies: { "@solarisdk/browser": "^0.1.1", "@solarisdk/sdk": "^0.1.2" }` (resolved `0.1.2` / `0.1.2` per Step 00); `devDependencies: { "typescript": "^5.7.2" /* resolved 5.9.3 */, "@types/node": "^22", "tsx": "^4.19.2", "vitest": "^2" }`; `scripts: { typecheck: "tsc -p tsconfig.json --noEmit", test: "vitest run", build: "tsc -p tsconfig.build.json" }`.
- `tsconfig.json`: `strict`, `module: NodeNext`, `moduleResolution: NodeNext`, `target: ES2022`, `noEmit: true`, `allowImportingTsExtensions: true` (repo convention — imports use `.ts` extensions), `types: ["node"]`. A separate `tsconfig.build.json` (override `noEmit`→`false`, `outDir dist`) is used only for the variant-app build; harness runs via `tsx`. `.gitignore` adds `*.db`, `dist/`, `artifacts/runs/`.

### Source layout (`src/`, relative to repo root)

```
solari-cookbook/
  package.json                 # NEW minimal root manifest (deps + scripts)
  tsconfig.json                # NEW strict NodeNext, noEmit, allowImportingTsExtensions
  tsconfig.build.json          # NEW: emit dist/ for the variant app only
  .env.example                 # extend: add LLM_API_KEY / LLM_ENDPOINT / LLM_MODEL (names only)
  src/
    solari/driver.ts           # EXISTING LiveSolari/MockSolari (Step 00) — the single seam
    solari/orchestrate.ts      # Step 03: sandbox serve + snapshot/fork + boot timing + cleanup
    variant-app/               # Step 02: the perturbable create-invoice app (node:http + node:sqlite)
      server.ts                #   routes + validation + post handler
      db.ts                    #   node:sqlite schema + ensureSchema + helpers (ground-truth store)
      render.ts                #   server-rendered HTML templates (inject P1–P5 axes)
      invoice.ts               #   domain: totals, invoice_no, validate inputs
    generate-variants/         # Step 02: seeded variant factory
      prng.ts                  #   mulberry32 + domain-separated sub-streams
      axes.ts                  #   the 5 axes (params, intensity→perturbation mapping)
      task-spec.ts             #   seed → natural-language instruction + expected values
      variants.ts              #   emit the variant matrix (>=10) as variants.json
      index.ts
    agent/                     # Step 04: vision-first loop
      action.ts                #   the closed Action union + reducer (click/type/press/nav/done/abort)
      model.ts                 #   multimodal caller (LLM_* env), JSON envelope, one-shot repair
      loop.ts                  #   screenshot → decide → execute → repeat (step cap, done/abort)
      trace.ts                 #   action trace JSON logging
    verify/                    # Step 05
      verifier.ts              #   independent ground-truth check (fail-closed)
      checks.ts                #   C1–C7 + total recomputation
    scorecard/                 # Step 06
      build.ts                 #   emit artifacts/scorecard.json
      curve.ts                 #   generalization curve points
      cost.ts                  #   credits/hours/tokens accounting
  test/                        # vitest unit tests (must pass in Mock mode)
    verifier.spec.ts           #   NEG-1..NEG-4 fail-closed tests
    axes.spec.ts               #   seed determinism (same seed → identical output)
    prng.spec.ts
    agent-loop.spec.ts         #   mock-agent plumbing (no model key needed)
  fixtures/                    # MockSolari recorded fixtures for offline dev
  artifacts/                   # run traces, screenshots, scorecard.json, curve
```

---

## 7. SANDBOX / SNAPSHOT STRATEGY (for Step 03)

### Serve the variant app inside a sandbox

1. Create a sandbox from the **base template** (`create({ template: "<base>", timeoutMs, metadata })`),
   `await sandbox.connect()`.
2. Copy the compiled app + manifest into `/app` (via `files.write`/`upload` or the git/template
   path), run `ensureSchema()` on first boot, then launch the server **in the background**:
   `sandbox.commands.run("sh", { args: ["-c", "cd /app && node dist/variant-app/server.js >/tmp/app.log 2>&1 &"] })`
   (must background it; `commands.run` waits for exit).
3. `const { url } = await sandbox.previewUrl(3000)` → base URL. **Build every path with
   `new URL(path, url)`** — the Solari preview URL may already carry a query string, so
   string-concat would corrupt it. Poll `/healthz` for readiness.

### Base snapshot (the bootstrap)

Prepare **one** pristine template/base sandbox: install Node 22, copy the compiled app, empty
SQLite schema, deps. `const baseSnapshotId = await sandbox.snapshot("coldstart-base")`, then
`promoteSnapshot(baseSnapshotId, "coldstart-base")` → a reusable template id. This is the
"pristine" environment: app present, DB **empty** (fresh seeds on each fork).

### Fork N variants fast

Each variant = a **fresh isolated sandbox forked from the base template**, ~1s boot. Exact
fork mechanism to be confirmed empirically at Step 03 (the SDK exposes `create({ template })`,
`sandbox.snapshot()`, `sandbox.revert(id)`, and `promoteSnapshot`). Locked approach: fork via
`create({ template: <coldstart-base-template-id>, metadata })`; each fork's `ensureSchema()`
runs at boot → a fresh empty DB, so it is a genuine unseen environment. (Fallback if
`create({template:snapshotId})` is rejected: promote the snapshot to a template, or use
`revert` for the sequential case.)

### Version / tag scheme (exact cleanup targeting)

Every Solari resource carries filterable **`metadata`** so cleanup kills exactly the right
things:

| Resource | `metadata` example |
| --- | --- |
| per-run sandbox | `{ app:"coldstart", run_id, variant_id, seed, src:"variant-fork", tag:"coldstart-run" }` |
| base snapshot/template | `{ app:"coldstart", kind:"base", tag:"coldstart-base" }` |

Cleanup:
```ts
for await (const s of solari.sandboxes.listAll({ metadata: { app:"coldstart", tag:"coldstart-run" } }))
  await s.kill()   // kill(), never close() — close() leaks the VM to idle timeout
// after all variants: deleteSnapshot(templateId) / delete template, then confirm count==0
```

### Timing & cost discipline

Measure boot ms per fork (`create` → first successful `/healthz`) into a timing table
(Step 03 deliverable; expect ~1s). Free plan = **1 concurrent sandbox, 1h max session**: run
variants **serially**, kill each sandbox immediately after verification, and keep each
sandbox's lifetime to task-time only. For a batch, reuse a single browser session across
variants and only fork sandboxes for distinct variants.

---

## 8. RISKS & OPEN QUESTIONS (with proposed resolution)

| # | Risk / question | Proposed resolution |
| --- | --- | --- |
| 1 | **Fork mechanism uncertainty.** Does `create` accept a snapshot id directly, or must we promote snapshot→template first? (SDK shows `create({template})`, `promoteSnapshot`, `revert`.) | Test at Step 03 both `create({template: snapshotId})` and `promoteSnapshot→create({template})`; lock whichever the API accepts; fall back to `revert` for the sequential path. No contract change. |
| 2 | **Node in the sandbox base.** `python3` is confirmed in `base`; Node 22 presence is unverified. | Base snapshot installs Node 22 (`apt-get`/nvm) if absent; if Node is truly impossible, serve the app with Python stdlib (`http.server` + `sqlite3`) while keeping the harness TS. Container-runtime detail, not a contract change. Low risk. |
| 3 | **Coordinate-click brittleness** on a live page (scroll/responsive shifts invalidate the model's `(x,y)`). | Pin a fixed viewport (`1280×800`, no device-scale), disable animations, screenshot `clip=full viewport`, keep the app single-viewport/no-overflow. Validate at Step 04 against the baseline; add a stuck heuristic if clicks map to no-op regions. |
| 4 | **Key scoping / contamination.** `LLM_API_KEY` leaking to the variant app or verifier, or the model seeing ground truth. | Key lives only in the agent process env, from `.env` via `process.env`; the variant app and verifier never import it; the task instruction is generated at the harness layer (never rendered into HTML, never exposed to the app); expected values are recomputed in the harness, never sent to the model. Reported + grepped in Step 07 hygiene. |
| 5 | **Cost envelope vs. n≥3 for a meaningful curve.** Free plan ≈ $3 credits, 1h session; 5 axes × up to 5 intensities × 3 seeds could exceed budget. | Budget at Step 06; run serially, reuse one browser session per batch, fork sandboxes only per distinct variant; prioritize P1 & P2 for the curve; run P5 as a cheap control; Mock-mode for plumbing, live only for the headline run. |

---

## Appendix A — The `SolariDriver` interface signature (locked, from Step 00)

```ts
export interface SolariDriver {
  launchBrowser(opts?: BrowserLaunchOptions): Promise<BrowserSession>
  createSandbox(opts?: SandboxCreateOptions): Promise<Sandbox>
  shutdown(): Promise<void>
}
// LiveSolari reads process.env.SOLARI_API_KEY; MockSolari is offline/log-mode. (see src/solari/driver.ts)
```

## Appendix B — Design acceptance self-check

| MASTER_PLAN Step 01 criterion | Where satisfied |
| --- | --- |
| Every axis is seeded-reproducible | §2 determinism rule (single PRNG, domain-separated sub-streams, `sameSeed→sameVariant`) |
| Action space forbids selectors | §3 doctrine — only screenshot/mouse/keyboard/goto; `locator()` never called |
| Verifier contract includes negative tests | §4 — NEG-1…NEG-4 (≥2 required), fail-closed |
| Scorecard has cost + replay fields | §5 — `session.replay_url` + `cost.{credits,hours,…}` |
| Language decision locked | §6 — TypeScript, with root `package.json`/`tsconfig` |

*ColdStart — DESIGN.md. No code, no secrets, no commits.*
