# Step 05 — Ground-truth Verifier — Report

- **Status:** DONE
- **Mode:** OFFLINE / MOCK (no live Solari run)
- **Agent:** repo-surgeon (dependency & configuration specialist)
- **Date:** 2026-09-02

## 1. What was done

Built the **independent ground-truth verifier** per `DESIGN.md §4` (Step 05 of
the ColdStart master plan) — the single component that decides whether the agent
*actually* created the invoice, reading the variant app's SQLite ground-truth
record via the **DB/files channel** (never the agent's narration, never the page
DOM, never the `done` claim).

Two input modes are implemented:

- **`verifyAgainstPath({ seed, dbPath })`** — opens a local `invoice.db` directly
  (offline; used by unit tests and re-runs). Deterministic.
- **`verifyAgainstSandbox({ seed, sandbox, dbPath? })`** — reads the live artifact
  bytes from a Solari sandbox's **FILE channel** (`sandbox.files.read`). Compiled
  and type-correct; not exercised live this step (proven offline via a mock
  sandbox handle in tests).

The verifier **recomputes expected values from the seed** via the pure
`deriveTaskSpec(seed)` function and **never** reads the HTML, the app's stored
"answer", or the agent's narration. It runs C1–C7 and returns the DESIGN §4
`VerifyResult` shape. **Fail-closed:** `task_completed` defaults false; on any
ambiguity it stays false.

## 2. Commands run

```bash
npm run typecheck        # tsc -p tsconfig.json --noEmit  -> 0 errors
npm run build            # tsc -p tsconfig.build.json       -> dist/ emitted (incl. dist/sqlite.js)
npm test                 # vitest run                       -> 37 passed (4 files)
npx vitest run test/verifier.spec.ts --reporter=verbose    # 13 passed
```

## 3. Deliverables

- `src/verify/verifier.ts` — the verifier: two input modes, sha256 evidence
  binding, fail-closed core (`verifyFromBytes` → `deriveTaskSpec(seed).expected`
  → `runChecks` → `task_completed = every check passed`), artifact parsing +
  well-formed/unsanitized guards.
- `src/verify/checks.ts` — the pure C1–C7 checks + normalized `ActualSnapshot`
  types + `FieldError`/`CheckResult`. Reuses `computeTotals` from
  `src/variant-app/invoice.ts` so money math has a single source of truth.
- `test/verifier.spec.ts` — 13 tests (NEG-1..NEG-6 fail-closed + NEG-4a/b +
  positive + re-run determinism + mock-sandbox path). Fixtures built
  **programmatically** with `node:sqlite` (same schema as the app).
- `src/sqlite.ts` **(added)** — a `createRequire("node:sqlite")` accessor.
  `node:sqlite` is an experimental builtin missing from Node's
  `builtinModules`, so Vite/Vitest cannot statically externalize it (it strips
  `node:` and fails to resolve a bare `sqlite` package). Loading via
  `createRequire` avoids Vite's static import analysis while using the **same**
  real Node `DatabaseSync`. Both `src/variant-app/db.ts` and
  `src/verify/verifier.ts` import `DatabaseSync` from here.

## 4. Evidence

- Verifier contract implemented → `src/verify/verifier.ts` (VerifyResult,
  FieldError, CheckResult, C1–C7).
- All 13 verifier tests pass → `npx vitest run test/verifier.spec.ts --reporter=verbose`
  (each NEG-x asserts `task_completed === false`).
- Positive test (seed=0) asserts toplevel recomputed totals `subtotal=36000
  tax=2880 total=38880` matched by the stored row → `task_completed === true`.
- Reproducibility → "re-running the verifier on the same stored DB reproduces the
  verdict + hash" asserts `r1 === r2` (identical `evidence_hash` + verdict).
- Sandbox path → "reads the artifact via the sandbox files channel and reproduces
  the path verdict + hash" asserts `verifyAgainstSandbox` hash/checks equal the
  `verifyAgainstPath` result for the same bytes.
- Build emits `dist/sqlite.js`; compiled `dist/variant-app/db.js` opens a memory
  DB and creates `INV-2026-0001` POSTED with the seed-0 totals → smoke test OK.

## 5. Deviations from plan

1. **Added `src/sqlite.ts` loader** (not in the Step 01 source layout). Reason:
   `node:sqlite` is missing from Node's `builtinModules`, so Vitest/Vite fails to
   externalize a static `import ... from "node:sqlite"` and every verifier test
   died with `Failed to load url sqlite`. A Vite `ssr.external` /
   `server.deps.external` / `resolveId`-plugin approach was tried but Vite still
   strips the `node:` prefix. The `createRequire` loader is the one change that
   makes the verifier run offline; it uses the identical real `DatabaseSync` and
   is therefore behavior-neutral. `src/variant-app/db.ts` now imports
   `DatabaseSync` from it (confirmed the compiled app still creates invoices).
2. **No `vitest.config.ts` was kept** — the loader alone resolves the issue, and
   the original repo had no Vitest config. (A temporary config was used to debug
   and then removed; no stray files remain.)
3. Implemented all four DESIGN-negative tests plus two extra fail-closed edges
   (missing file, corrupt artifact) and a sandbox-channel mock test — a strict
   superset of the required ≥4.
4. **`.gitignore`: no change needed.** `*.db`, `dist/`, `artifacts/runs/` were
   already ignored by a prior step (confirmed the diff is pre-existing). Test
   fixtures are created under the OS temp dir and removed in `afterEach`.

## 6. Self-check vs acceptance criteria

| Criterion | Met? | Evidence |
| --- | --- | --- |
| Negative tests fail-closed | yes | NEG-1..NEG-6 + NEG-4a/4b all return `task_completed:false` (13/13 verifier tests pass) |
| Verifier never trusts agent output | yes | `verifyFromBytes` recomputes `expected = deriveTaskSpec(seed).expected`; reads only the DB bytes (path mode: file; sandbox mode: `sandbox.files.read`) — never narration/DOM |
| Re-running against a stored DB reproduces the verdict | yes | "re-running the verifier on the same stored DB reproduces the verdict + hash" → `r1 === r2` (same hash + verdict) |
| Typecheck + tests green | yes | `npm run typecheck` 0 errors; `npm test` 37 passed (4 files); `npm run build` passes |
| No secrets | yes | verifier reads only the artifact; no key read/import. `SECURITY` note in both verifier + loader. No `SOLARI_API_KEY`/`LLM_*` referenced |

## 7. Open questions / risks

- **`node:sqlite` + Vitest** continues to be the single environment-specific
  quirk. The `createRequire` loader is a clean workaround, but it depends on
  Node's ESM `import.meta.url`/`createRequire` across both `tsx` (harness) and the
  compiled dist (sandbox). Smoke-tested on the dist build; if the sandbox Node
  runtime differs, re-check. Low risk.
- The sandbox path is *not* exercised live this step. It reads the DB via
  `sandbox.files.read` and re-parses a temp copy. If a live sandbox's DB is
  mid-write when read, bytes could be in WAL state (SQLite default journal is
  `delete` here, so a cleanly-closed DB is a single file — expected in practice
  because the app closes writes per request).
- `task_completed` is decided by `checks.every(passed)` (all of C1–C7). This is
  stricter than "every critical check passes" and is the intended fail-closed
  posture. No field_errors are emitted when there is no unique POSTED row to diff
  (nothing to compare) — matching DESIGN NEG-1 (`field_errors: []`).

## 8. Secrets & cleanup attestation

- [x] No API keys/secrets in repo or this report. No `.env` read beyond the
  pre-existing project; verifier and loader import/read no credentials.
- [x] No Solari resources created or left running (OFFLINE step; no live runs,
  no sandboxes, no browser sessions). The only filesystem writes are OS-temp
  SQLite fixtures created and removed by the tests.
