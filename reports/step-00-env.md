# Step 00 — env + live Solari validation — Report

- **Status:** DONE
- **Mode:** LIVE (real quickstarts run against the live Solari API)
- **Agent:** repo-surgeon (dependency/cleanup/config subagent)
- **Date:** 2026-09-02

## 1. What was done

Ran the two smallest complete Solari examples (`browser-quickstart-ts`,
`sandbox-quickstart-ts`) against the **live** API to validate the environment and
the SDKs end-to-end, then produced the environment matrix and a typed driver
skeleton that compiles against the real SDK type definitions.

Summary of live results:
- **Browser SDK** (`@solarisdk/browser`): launched a cloud browser, navigated to
  `https://example.com`, read title + h1, captured the session id, and **exited on
  its own** (exit code 0) — proving `browser.close()` + `solari.close()` released
  the loopback proxy so the process did not hang.
- **Sandbox SDK** (`@solarisdk/sdk`): created a microVM, ran `python3`, wrote a
  file, listed a dir, and **exited on its own** (exit code 0). The `finally`
  block called `sandbox.kill()`; a follow-up `sandboxes.list()` confirmed
  `running sandboxes: 0` and that the target id was gone.

No example source files were modified. `node_modules/` + `package-lock.json`
appeared in each example dir as a result of `npm install` (both gitignored).

## 2. Commands run

All commands were run from the repo root
`C:/Users/oneda/Projects/Research - General/coldstart/solari-cookbook` except the
example `cd`s. The key was loaded only via `set -a; . ../../.env; set +a`.

Browser example — install + run:
```bash
cd examples/browser-quickstart-ts
npm install
set -a; . ../../.env; set +a
npm start ; echo "EXIT_CODE=$?"
```

Sandbox example — install + run:
```bash
cd ../sandbox-quickstart-ts
npm install
set -a; . ../../.env; set +a
npm start ; echo "EXIT_CODE=$?"
```

Cleanup verification (temporary helper, removed afterward):
```bash
# _verify-cleanup.mts created in the sandbox example dir to list sandboxes,
# then deleted after use (never committed, not part of the deliverable).
set -a; . ../../.env; set +a
SANDBOX_ID_TO_CHECK="<sandbox id from run>" npx tsx _verify-cleanup.mts ; echo "EXIT=$?"
```

Skeleton compile check (throwaway env, removed after):
```bash
# temp dir: npm install typescript@5.7.2 @solarisdk/browser@0.1.2 @solarisdk/sdk@0.1.2 @types/node@22 tsx@4.23.13
./node_modules/.bin/tsc -p tsconfig.json    # strict, NodeNext, noEmit
./node_modules/.bin/tsx smoke.mts            # runtime smoke test of MockSolari
```

## 3. Deliverables

- `solari-cookbook/src/solari/driver.ts` — typed `SolariDriver` interface +
  `LiveSolari` (reads `process.env.SOLARI_API_KEY`) and `MockSolari` (offline,
  log-mode, deterministic fixture stubs). Marked **"STEP 00 SKELETON — fill in at
  Step 02/03"**. Compiles.
- `reports/step-00-env.md` — this report.
- `examples/browser-quickstart-ts/package-lock.json` + `node_modules/` — generated
  by `npm install` (gitignored; not a source change).
- `examples/sandbox-quickstart-ts/package-lock.json` + `node_modules/` — generated
  by `npm install` (gitignored; not a source change).

## 4. Evidence

Environment matrix (step 4 of the plan):

| Item | Value |
| --- | --- |
| OS | Microsoft Windows [Version 10.0.26200.9168] (MINGW64_NT-10.0-26200, Git Bash) |
| node | v22.23.1 |
| npm | 10.9.8 |
| @solarisdk/browser (resolved) | 0.1.2  *(package.json: `^0.1.1`)* |
| @solarisdk/sdk (resolved) | 0.1.2  *(package.json: `^0.1.2`)* |
| tsx (resolved) | 4.23.13 |
| typescript (resolved) | 5.9.3 |

Live browser run (real console output, key never printed):
```
> start
> tsx index.ts

title : Example Domain
h1    : Example Domain
session: ip-10-0-10-130:f8ee9b9a-23c0-41be-9f46-25afffb72b6a:cmtj5qdco00y2o6018m04ewvp:1788297866312.1hW5NqOuCvpd9xdkW_4kMg
EXIT_CODE=0
```

Live sandbox run (real console output, key never printed):
```
> start
> tsx index.ts

sandbox: ZGVza3RvcC1wb29sLWktMGZkOWVkN2RjMDNhNzlkYjI6dm1fMDAyMDI3OmNtdGo1cWRjbzAweTJvNjAxOG0wNGV3dnA6MTc4ODI5Nzg5MDg4MQ.cq3StAt1IDl-ICxpNYBHKd51PcR9gq2VnVHBUgw8FBs
exit: 0 stdout: 5050
file  : written from the SDK
ls    : .ICE-unix .X11-unix .XIM-unix .font-unix hello.txt systemd-private-3c4646555aa44386a23fd85cfc7cccbb-systemd-logind.service-ClJ4OU
EXIT_CODE=0
```

Cleanup attestation (sandbox destroyed by `kill()`; verified via `sandboxes.list()`):
```
running sandboxes: 0
target sandbox still running? false
EXIT=0
```

Skeleton verification:
- `tsc -p tsconfig.json` → `TSC_EXIT=0` (strict, NodeNext, noEmit) — compiles
  cleanly against the real `@solarisdk/browser` + `@solarisdk/sdk` type defs.
- `tsx smoke.mts` → `[MockSolari] launchBrowser/createSandbox/shutdown`, returned
  `mock-browser-session-slot-1` / `mock-sandbox-0001`, `MockSolari runtime OK`,
  `SMOKE_EXIT=0`.

Note: the `session:` id and `sandbox:` id above are ephemeral runtime **resource**
identifiers (not secrets) recorded per the task. Both resources were released /
destroyed after the runs (browser session released by `browser.close()`; sandbox
killed and confirmed absent via list).

## 5. Deviations from plan

- **Temporary verification helper.** To positively attest sandbox cleanup I created
  a one-off `_verify-cleanup.mts` inside `sandbox-quickstart-ts` (the SDK exposes
  `sandboxes.list()`), ran it, then **deleted it**. It was never committed and is
  not a deliverable. No example source file was changed.
- **Browser cleanup has no direct cross-check.** The browser SDK exposes no
  `sessions.list()`; browser-session cleanup is evidenced by (a) `browser.close()`
  + `solari.close()` in the example's `finally`, and (b) the process exiting on its
  own (which fails to happen if the loopback proxy handle leaks — the documented
  hang case). No idempotent list check was possible for the browser side.
- **No root package.json / tsconfig.** The cookbook repo is a flat set of examples
  with no unifying package manifest, so the skeleton was typechecked against the real
  SDK types in a throwaway environment (installed `typescript`, both SDK packages,
  `@types/node`, `tsx`, then removed). The project will need a real
  `tsconfig` + `@types/node` + the two SDK packages wired in at Step 02/03.
- `npm install` added `node_modules/` + `package-lock.json` to the example dirs —
  expected side effect, both gitignored.

## 6. Self-check vs acceptance criteria

| Criterion | Met? | Evidence |
| --- | --- | --- |
| (a) Live run evidence present | yes | §4 — real title/h1/session, sandbox id/exit/stdout/ls console output; `Mode: LIVE` |
| (b) No hang (process exited on its own) | yes | Both runs returned `EXIT_CODE=0` (browser + sandbox); no timeout, no hanging |
| (c) Cleanup verified (kill()/close()) | yes | Sandbox: `running sandboxes: 0`, target absent after `kill()`; Browser: exited cleanly with `close()` in `finally` (no leaked proxy handle) |
| (d) No secrets in repo or report | yes | `.env` git-ignored & untracked (`git check-ignore .env` → ignored); key never printed/logged/echoed; report contains no key |
| (e) Mode stated truthfully | yes | `Mode: LIVE` — real quickstarts ran against api.getsolari.com with a real key (sourced from `.env`) |

## 7. Open questions / risks

- **Packaging seam.** The typed driver needs a real `tsconfig` + `@types/node` +
  the two SDK packages installed in a shared package. Decide at Step 02/03 whether
  to introduce a root `package.json`/`tsconfig` for `src/` or keep `src/`
  standalone. Until then the skeleton only compiles in an env with those deps.
- **Sandbox/session ids in the report** are runtime resource ids (not secrets) and
  were destroyed post-run. Orphaned ids are harmless but were already released.
- **Browser cleanup is inferred, not list-verified** — see deviation. If exact
  session-release confirmation is needed in a later step, add an explicit
  `sessions.releaseAndWait(sessionId)` after `browser.close()`.
- The 3 `node.exe` processes observed at the end are the pi coding harness itself,
  **not** leftover quickstart/Solari processes. No Solari server/VM remained.

## 8. Secrets & cleanup attestation

- [x] No API keys/secrets in the repo or this report. `SOLARI_API_KEY` was only
      sourced via `set -a; . ../../.env; set +a`; never echoed, never on any
      command line that was printed, never written to a file.
- [x] All Solari resources killed / VMs terminated:
  - Sandbox: `sandbox.kill()` ran (finally); `sandboxes.list()` returned
    `running sandboxes: 0` and target id absent.
  - Browser: `browser.close()` (releases session) + `solari.close()` (closes
    loopback proxy) ran (finally); the script exited on its own with code 0.
- [x] No example source files modified; no commit / push / git config change made.
- [x] Temporary helper `_verify-cleanup.mts` deleted; throwaway typecheck + smoke
      env deleted.
