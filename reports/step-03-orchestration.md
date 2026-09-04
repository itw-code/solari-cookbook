# Step 03 — Solari sandbox orchestration — Report

- **Status:** DONE (live). Two DESIGN §8 risks empirically resolved; full live proof ran. Snapshots are *intermittently* unreliable on this environment, so the final proof used a fallback fork path — see §5 & §7.
- **Mode:** LIVE (real `api.getsolari.com`, real key from `.env`, real credits)
- **Agent:** repo-surgeon / builder subagent (assigned via pi)
- **Date:** 2026-09-02

## 1. What was done

Wired the Solari sandbox orchestration layer for ColdStart, per DESIGN.md §7 and MASTER_PLAN §4 Step 03:

- Built `src/solari/orchestrate.ts`: typed library + CLI (`tsx src/solari/orchestrate.ts`) implementing
  `createBaseSandbox`, `prepareApp`-equivalents (`uploadCompiledApp`+`launchServer`), `getPreviewUrl`,
  `snapshotBase`, `forkVariant`, and `cleanup`, plus a live proof driver.
- Empirically resolved **DESIGN §8 risk #1 (fork API)** and **risk #2 (Node in base template)**.
- Ran one **live end-to-end proof** (final clean run → `artifacts/step-03-live.log`) and one **isolated fork-API probe**.

The variant app (`src/variant-app/`, `node:http` + `node:sqlite`) was built to `dist/` first (`npm run build`),
then uploaded into each sandbox at `/app/dist` and served on `:3000` (backgrounded via `sh -c "… nohup node … &"`,
because `commands.run` waits for exit).

## 2. Commands run

```bash
cd "C:/Users/oneda/Projects/Research - General/coldstart/solari-cookbook"
npm run build                       # tsc -p tsconfig.build.json  -> dist/variant-app/server.js
npm run typecheck                   # tsc -p tsconfig.json --noEmit

# LIVE proof (sources .env in-shell; the key is never echoed). Output tee'd to artifacts/step-03-live.log.
bash scripts/run-step-03.sh | tee artifacts/step-03-live.log

# Isolated fork-API probe (temp script, described in §4) — tested create({template:snapshotId}),
# promoteSnapshot->create({template}), and create({fromSnapshot}).
# Verification: confirmed 0 live sandboxes / snapshots / custom templates after cleanup.
```

## 3. Deliverables

- `src/solari/orchestrate.ts` — the orchestration module + CLI (runs live proof via `tsx`).
- `scripts/run-step-03.sh` — re-runnable live-proof wrapper (sources `.env` in-shell, never echoes the key).
- `artifacts/step-03-live.log` — verbatim live proof output (timing table, preview URLs, fork API finding, cleanup log).

## 4. Evidence

All live. Preview URLs below are **redacted** (`pt_token=****`) — the token is a session capability, not the API key.

### 4.1 DESIGN §8 risk #1 — fork API verdict (KEY FINDING)

**Verdict: `create({template: snapshotId})` is REJECTED; the working fork path is `promoteSnapshot → create({template})`.**

- **Negative control** (isolated live probe; exact gateway error):
  `create({ template: "snap_dl4boxxz0kry" })` →
  `[status=400] template: unknown template "snap_dl4boxxz0kry" — built-in sandbox templates are base; custom templates are tpl_… ids`.
  => a `snap_…` id is **not** a valid `template`; `create({template:snapshotId})` does not work.
- **Positive control**: `promoteSnapshot(snapId, "coldstart-base")` → `tpl_2d7e6d13006f4b80`, then
  `create({ template: tpl_… })` returned a live sandbox (verified: a forked variant served `/healthz` 200 with 0 invoices).
- **Bonus**: `create({ fromSnapshot: snapId })` is also **accepted** by the API (an alternative to promote) — noted for Step 05/06, but DESIGN §7's `promoteSnapshot → create({template})` is the locked approach and it works.

### 4.2 DESIGN §8 risk #2 — Node in base template (KEY FINDING)

- The built-in `base` sandbox template has **no Node 22** by default (it does have `python3` — observed `Python 3.11.2`).
- The module installs Node 22.23.1 via the official tarball (`curl … node-v22.23.1-linux-x64.tar.xz | tar -xJ` to `/usr/local`),
  which succeeded: `node --version -> v22.23.1`, `node:sqlite supported: true`.
- => risk #2 resolved: `base` = `python3` only; Node 22 must be provisioned (the module does it; the base snapshot is the place to bake it in).
- Only `base` is a *sandbox* template — `code`/`office`/`workstation`/`default` are **desktop** kinds (verified via `templates.list()`).

### 4.3 preview URL query-string caution (verified)

- `previewUrl(3000)` returns a URL that **carries a query string**: `https://<host>/?pt_token=<token>` (`hasQueryString=true`).
- `buildUrl(base, "/healthz")` correctly preserves it → `https://<host>/healthz?pt_token=<token>`.
- Fetching through that URL: **base `/healthz` → HTTP 200 `ok`** (log line 49). A bare `new URL(path, base)` would drop the token
  (the earlier 401 was caused by fetching a *redacted* URL — a bug fixed in the final module; the token must be kept for the actual fetch).

### 4.4 Timing table (from `artifacts/step-03-live.log`)

| Phase | Time |
| --- | --- |
| base create (built-in `base` → connect) | 1329 ms |
| base prepare (upload compiled app) | 4477 ms |

> Note: the Node 22 install (`node --version -> v22.23.1`) happens during base setup between the create and prepare
> phases; it is a one-time per-sandbox cost not separately metered in this table.
| snapshot + promote (`coldstart-base`) | 13649 ms — **FAILED (409 Not snapshottable)**, best-effort |
| fork seed=11 (create → /healthz) — **direct** | 10583 ms (create 9089 ms / serve 1494 ms) |
| fork seed=42 (create → /healthz) — **direct** | 10381 ms (create 8876 ms / serve 1505 ms) |

Both forks served `/healthz` **200 `ok`** through their own preview URL and reported **`invoices=0`** (empty DB — a fresh
environment; the app's `ensureSchema()` runs at boot). The snapshot+template fork path was separately demonstrated in a
prior live run: `snapshot=snap_dl4bs8xd4bcs → template=tpl_ce68bb1b99c44bb5`, and a template fork booted
seed=11 with `/healthz` 200 / `invoices=0`.

## 5. Deviations from plan

1. **Snapshot endpoint is unreliable.** `sandbox.snapshot()` intermittently returns `409 Not snapshottable` even on a
   pristine, idle sandbox (observed 7 of 8 attempts this session; one previously succeeded). The module therefore treats
   snapshot+promote as **best-effort**: on failure it records the exact error and **falls back to direct provisioning**
   (create a fresh sandbox from the built-in `base` template, install Node, upload the app, boot). The final clean proof used
   this `direct` fork path (hence `[direct]` in the timing table). The `snapshot → tpl_ … → create({template})` path *is*
   proven to work (see §4.1/§4.4) but is flaky live.
2. **The ~1s fork claim is NOT met** on the free plan. Measured fork boot is ~10.4s, dominated by the gateway
   `create()` provisioning/queueing (~8.9s) rather than the app serve (~1.5s). This is a free-plan capacity/scheduling
   effect (also seen as intermittent `503 No sandbox host available` on back-to-back creates). DESIGN §7's ~1s refers to
   the restored-snapshot serve; on this plan the gatekeeper is the create queue.
3. **Driver seam.** DESIGN §3 routes all Solari access through `src/solari/driver.ts`, but that seam only wraps
   `launchBrowser/createSandbox/shutdown`. Step 03 needs `sandboxes.listAll/kill/deleteSnapshot/promoteSnapshot` and the
   per-sandbox `commands/files/previewUrl/snapshot` handles, which DESIGN §7 explicitly says steps 03/05 use directly.
   `orchestrate.ts` therefore constructs `SolariClient` directly (as the cookbook examples do); the driver seam is retained
   for the browser path in Step 04. No contract change.
4. **1-concurrency respected.** Free plan = 1 concurrent sandbox; the proof kills each sandbox before creating the next,
   with a 6s reap-wait, and retries transient `503` creates and `409` snapshots.

## 6. Self-check vs acceptance criteria

| Criterion (MASTER_PLAN Step 03) | Met? | Evidence |
| --- | --- | --- |
| Real preview URLs returned | yes | base `…/…?pt_token=…`, forks `…` (§4.4; log lines 49–54) |
| Preview URLs cleaned up | yes | cleanup log: killed 3 sandboxes, 0 live resources after |
| Boot times recorded (vs ~1s claim) | yes, but 10.4s not ~1s | timing table §4.4 (create~8.9s + serve~1.5s) — honest deviation |
| Fork variants serve `/healthz` | yes | seed=11 & seed=42 both status 200 `ok` through preview |
| Fresh variant starts with EMPTY DB (no invoice) | yes | both forks report `invoices=0` (via guest python3 `sqlite3`) |
| Every run ends with zero live resources | yes | `CLEANUP DONE: 0 live; ✓ ZERO live resources` (log 69–70, 111–112) + independent re-verify |
| No secrets anywhere | yes | grep for `slr_live_`/`SOLARI_API_KEY=` in repo (excl. `.env`) → only the `…` placeholders in examples; `.env` untouched |

## 7. Open questions / risks (for the orchestrator)

- **Snapshot reliability is the main risk.** `POST /sandboxes/:id/snapshots` intermittently 409s `Not snapshottable`. Likely a
  free-plan/gateway limitation (the brief `Guest: only base is a sandbox template; snapshots are a paid/heavier feature`).
  If Step 05/06 want fast snapshot-based forking, this needs either a paid plan or a routing change (e.g. always
  direct-provision, accepting ~10s forks). The `create({fromSnapshot})` alternative also needs a snapshot to exist.
- **Capacity / 1-concurrency.** Back-to-back sandbox creates intermittently return `503 No sandbox host available`. Mitigated
  here with retry+backoff and a reap-wait, but for a large variant matrix Steps 06 will need generous serialization + retries.
- **~1s fork claim.** Not achievable on the free plan under the above; recommend the master plan's Step 06 budget to reflect
  ~10s per variant (create-bound), not 1s.
- The `base` template does **not** ship Node 22 — every sandbox must install it (~one-time per base, or per direct fork).
  Baking Node into a committed base template would save cost but is currently blocked by the unreliable snapshot endpoint.

## 8. Secrets & cleanup attestation

- [x] No API keys/secrets in the repo or this report. The only `slr_live_…` strings are the documented `…` placeholders in
  example `.env`/`README` files. `SOLARI_API_KEY` was sourced only in-shell (`set -a; . ./.env; set +a`) and read from
  `process.env` inside `orchestrate.ts`; never logged, never written to a file.
- [x] All Solari resources killed / VMs terminated. Cleanup proof (`artifacts/step-03-live.log`): `killed sandbox ids: 3`,
  `deleted snapshot: (none)`, `deleted template: (none)`, `live ColdStart resources after: 0`, `✓ ZERO live resources`.
  Independent post-run re-verify: **0** live `app:"coldstart"` sandboxes, **0** snapshots, **0** custom templates.
