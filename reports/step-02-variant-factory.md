# Step 02 — variant factory — Report

- **Status:** DONE
- **Mode:** LOCAL (no Solari API/resources used this step; app runs on plain Node)
- **Agent:** repo-surgeon (builder) for the code; **report authored by orchestrator** (the build subagent hit a Windows process-cleanup issue and did not emit the report; the orchestrator re-verified every fact below independently and wrote this report from verified evidence).
- **Date:** 2026-09-02

> **Routing note (honesty):** the subagent completed all code deliverables (manifest,
> variant app, generator, tests, screenshots) but its final action was a note about
> killing stray Node processes, and it produced **no** report. The orchestrator re-ran
> the acceptance checks on real artifacts and documented the results here. Every claim
> below is orchestrator-verified, not asserted.

## 1. What was done

Built the **perturbable Create-Invoice task app** and the **seeded variant generator**
per `DESIGN.md` §1/§2/§6:

- **Root manifest:** `package.json`, `tsconfig.json` (strict, NodeNext, noEmit), `tsconfig.build.json`.
- **Task app** (`src/variant-app/`): Node `node:http` + `node:sqlite`, zero runtime deps.
  Routes `/`, `/new`, POST `/invoices`, `/invoices/:id`, `/healthz`; `DB_PATH` env override
  so it runs locally (default `/app/data/invoice.db` for the sandbox); `VARIANT_SEED` drives
  the active perturbation at the app layer, so `sameSeed -> sameVariant` holds end to end.
- **Variant generator** (`src/generate-variants/`): `prng.ts` (mulberry32 + domain-separated
  sub-streams), `axes.ts` (P1 relabel…P5 theme, integer intensity, deriveConfig), `task-spec.ts`
  (seed → task instruction + expected values), `variants.ts`/`index.ts` (emit the matrix).
- **Screenshot harness** (`scripts/screenshot-variants.mjs`) — used a local headless browser
  to render 3 variants.
- **Unit tests** (`test/`): `prng.spec.ts` + `axes.spec.ts`.

## 2. Commands run (orchestrator re-ran)

```bash
npm install                                   # root
npm run typecheck                             # tsc -p tsconfig.json --noEmit
npm test                                      # vitest run (15 tests)
VARIANTS_OUT=/tmp/dm_a.json npx tsx src/generate-variants/index.ts
VARIANTS_OUT=/tmp/dm_b.json npx tsx src/generate-variants/index.ts   # full-matrix determinism
# seed=42 twice for per-seed determinism
DB_PATH=data/audit-invoice.db PORT=3999 VARIANT_SEED=0 node dist/variant-app/server.js &
curl -s http://localhost:3999/healthz
curl -s -o /dev/null -w "HTTP %{http_code}" -X POST http://localhost:3999/invoices \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data "customer=ACMECORP&invoice_date=2026-10-01&due_date=2026-10-31&tax_rate=8&description=Consulting&qty=3&unit_price=120.00"
# node:sqlite read of the stored row + recompute
```

## 3. Deliverables

- `package.json`, `tsconfig.json`, `tsconfig.build.json` — minimal root manifest (deps +
  `typecheck`/`test`/`build`/`gen:variants` scripts).
- `src/variant-app/{server,db,invoice,render}.ts` — the perturbable Create-Invoice app.
- `src/generate-variants/{prng,axes,task-spec,variants,index}.ts` — the seeded variant factory.
- `variants.json` — the variant matrix (**14 variants**, schema 1.0, baseline seed=0).
- `scripts/screenshot-variants.mjs` — local headless screenshot harness.
- `test/{prng,axes}.spec.ts` — determinism unit tests.
- `artifacts/step-02/{baseline-s0,p1-relabel-s17,p2-structure-s7}.png` — 3 distinct variants.

## 4. Evidence

- **Determinism:** full matrix generated twice → `identical bytes`; seed=42 twice →
  `identical bytes`. (Orchestrator `diff -q` → no difference.)
- **Local run / task completion:**
  - `GET /healthz` → `ok`.
  - `POST /invoices` → `HTTP 302` (redirect to `/invoices/1`).
  - Confirmation page `<title>` → `Invoice Created`.
  - Stored row: `status=POSTED`, `customer=ACMECORP`, `tax_rate_bps=800`, `subtotal=36000`,
    `tax=2880`, `total=38880`; item `{description:"Consulting", qty:3, unit_price_cents:12000,
    line_total_cents:36000}`.
  - **Recompute check:** `3×12000=36000`, `round(36000×800/10000)=2880`, `36000+2880=38880`
    → `matches stored: true`. Ground truth is independently verifiable.
- **Tests:** `npm test` → `2 files passed, 15 tests passed` (prng 5, axes 10).
- **Typecheck:** `npm run typecheck` → exit 0, no errors.
- **Screenshots (3, visibly distinct):** baseline = light theme "Create Invoice" / "Submit";
  p1 = relabeled "New Bill"/"Confirm" with VAT dropdown + reordered fields + optional PO/Reference;
  p2+p5 = dark theme, sidebar nav, **wizard "Create Invoice · Step 1 of 2" / "Next"**.

## 5. Deviations from plan

1. **Report authored by orchestrator** (see routing note) — the subagent delivered the code
   but not the report. Facts were re-verified on real artifacts.
2. **Screenshots via local headless browser, not Solari.** Step 02 has no Solari dependency;
   the app runs on plain Node, so a local headless browser rendered the 3 variants. Real
   rendered-in-Solari screenshots belong to Step 03/06 (when the app is served from a Solari
   sandbox and a Solari cloud browser screenshots it). No contract change.
3. **`data/*.db` + `dist/` + `artifacts/runs/` gitignored** (added). `artifacts/step-02/` PNGs
   are tracked. Reasoning: DB artifacts and build output are machine-local; evidence screenshots
   are the submission artifact.

## 6. Self-check vs acceptance criteria

| Criterion (MASTER_PLAN §4 Step 02) | Met? | Evidence |
| --- | --- | --- |
| (a) Re-run generator twice on one seed → identical output | yes | full matrix + seed=42 both byte-identical (`diff -q` clean) |
| (b) App starts locally and completes task via curl | yes | POST→302, confirmation "Invoice Created", POSTED row present |
| (c) 3 variant screenshots exist and visibly differ | yes | `artifacts/step-02/*.png` — clearly distinct (labels/layout/theme/wizard) |
| (d) Ground-truth record is a DB file I can read directly | yes | `data/*.db` readable via `node:sqlite`; totals recompute → `true` |

## 7. Open questions / risks

- **Fork mechanism + Node-in-sandbox** (from DESIGN.md §8) still to be confirmed at Step 03
  (live Solari orchestration). No contract change required — fallbacks documented.
- **Coordinate stability** will be validated at Step 04 (fixed viewport + no-overflow design).
- The samples screenshotted hit P1/P3 (p1-relabel) and P2/P5 (p2-structure); the full 14-variant
  matrix covers all 5 axes across intensities. Full per-axis inference happens at Step 06.

## 8. Secrets & cleanup attestation

- [x] No API keys/secrets in repo or this report. The `.env` (with `SOLARI_API_KEY`) is
      git-ignored & untracked; no key value referenced anywhere in this step's output.
- [x] No Solari resources used (Mode: LOCAL). Nothing to kill on the Solari side.
- [x] Local server (`:3999`) killed after the POST proof; temporary `data/audit-invoice.db`
      and `/tmp` determinism files removed.
- [x] No commit/push. `git status` shows new untracked files only.
