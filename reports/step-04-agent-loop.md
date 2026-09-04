# Step 04 — Vision-first agent loop — Report

- **Status:** DONE (honest PARTIAL on the live baseline — see §4.2; the harness ran end-to-end, the baseline model did **not** complete the task)
- **Mode:** LIVE
- **Agent:** repo-surgeon (builder subagent)
- **Date:** 2026-09-02

## 1. What was done

Built the vision-first agent loop per DESIGN.md §3 (pixels in, coordinates out) and proved it runs **live** against the baseline variant (seed=0, the canonical un-perturbed `Create Invoice` app). Delivered:

- `src/agent/action.ts` — the closed `Action` union + the single reducer to the browser (`click→mouse.click`, `type→keyboard.type`, `press→keyboard.press`, `nav→goto`, `done`/`abort`). Only `mouse.click` / `keyboard.type` / `keyboard.press` / `goto` are ever called — **no `locator()`, no `innerText`, no `$eval`, no accessibility tree, no bounding boxes** anywhere. `nav` preserves the Solari `?pt_token=` via `new URL(path, base)` + query-string carry-over (DESIGN §3/§7 — never string-concat).
- `src/agent/model.ts` — multimodal caller reading `LLM_API_KEY` / `LLM_ENDPOINT` / `LLM_MODEL` from **`process.env` only**. Sends `{task, image(base64 PNG), history:Action[], step}`; parses `{action, rationale?}` from the OpenAI-compatible response with **robust JSON extraction** (first `{…}` block) and a **one-shot repair** re-ask on a parse failure. Never sends the seed / axis intensities / expected DB values / verifier checks.
- `src/agent/loop.ts` — screenshot → model → action → execute → repeat, with a hard step cap (`COLDSTART_MAX_STEPS`, default 30), terminal conditions (`done`/`abort`/`step_cap`), and a `stuck` heuristic (≥3 consecutive identical clicks with no screenshot change). Dependency-injected `PageHandle` + `ModelCaller` so it is unit-testable with NO network and NO key.
- `src/agent/trace.ts` — writes `artifacts/runs/<run_id>/trace.json` (task, per-step actions, ok/error, rationale, the screenshot that drove each decision) + per-step PNG screenshots as evidence.
- `src/agent/screenshot.ts` — full-viewport PNG capture (fixed 1280×800, no device scale) + base64 encode.
- `src/agent/index.ts` — the live baseline runner (reuses orchestrator Step 03: `createBaseSandbox` → `launchServer` → `getPreviewUrl` → `waitForHealthz`; launches the browser via `LiveSolari.launchBrowser`; kills everything in `finally`).
- `test/agent-loop.spec.ts` — MOCK-mode plumbing test (stub model + `MockPage` + `MockSolari`): proves the loop logic without network.

## 2. Commands run

```bash
# typecheck the harness
npx tsc -p tsconfig.json --noEmit          # exit 0

# mock plumbing test (no network / no model key)
npx vitest run                             # 3 files, 24 tests pass (9 in agent-loop.spec.ts)

# rebuild the variant app for the sandbox
npm run build                              # exit 0

# calibration — ask the model for its first action on the baseline screenshot
COLDSTART_MAX_STEPS=24 npx tsx src/agent/index.ts        # live run (see artifacts/step-04-live.log)
```

## 3. Deliverables

- `src/agent/action.ts` — closed `Action` union + reducer (vision-first, DOM-free).
- `src/agent/model.ts` — multimodal caller, robust JSON extraction + one-shot repair, key scoped to `process.env`.
- `src/agent/loop.ts` — the loop (step cap, done/abort/stuck, injected page+model).
- `src/agent/trace.ts` — action-trace JSON writer.
- `src/agent/screenshot.ts` — full-viewport PNG capture.
- `src/agent/index.ts` — live baseline runner (reuses Step 03 orchestrate).
- `test/agent-loop.spec.ts` — MOCK plumbing test (9 tests).
- `artifacts/runs/r_mtjgq7rq_s0/trace.json` — the live baseline action trace (evidence artifact).
- `artifacts/runs/r_mtjgq7rq_s0/step-01.png … step-24.png`, `final.png` — the screenshot that drove each step + the final state.
- `artifacts/step-04-live.log` — verbatim live run output (redacted URLs + cleanup log).

## 4. Evidence

### 4.1 Mock plumbing test (MODE: MOCK) — PASSES

`test/agent-loop.spec.ts` (9 tests) drives a scripted stub model + `MockPage` through the loop and asserts the loop logic (`done`/`abort`/`stuck`/`step_cap`) and trace emission:

- Baseline scripted sequence → `status 'done'`, `stepsTaken == 16`, final title `"Invoice Created"`, model received strictly increasing `step` and growing `history`, `trace.json` written with `terminated_by:'done'`, `base_url` redacts the gateway token, per-step screenshots exist.
- `abort` → stops with `status 'aborted'`.
- 3 identical clicks with no page change → `status 'stuck'`.
- never-terminating model + `maxSteps=5` → `status 'step_cap'`, `stepsTaken==5`.
- `MockSolari.createSandbox()` + `shutdown()` resolve cleanly.
- `model.ts` robust-JSON: parses bare envelope, recovers JSON inside prose/code fences, coerces numbers, rejects unknown kinds / non-objects.

Result: `3 files, 24 tests passed`, typecheck `exit 0`.

### 4.2 Live baseline run (seed=0, MODE: LIVE) — HONEST PARTIAL

Command: `set -a; . ./.env; set +a; COLDSTART_MAX_STEPS=24 npx tsx src/agent/index.ts` (see `artifacts/step-04-live.log`).

Outcome (verbatim from the log):

```
status           : step_cap
steps taken      : 24/24
final page title : Create Invoice
invoice rows     : 0 (sanity only; verifier is Step 05)
terminated by    : step_cap
last action      : {"kind":"click","x":277,"y":289}
```

- **The task did NOT complete.** Final title is `"Create Invoice"` (the form page), not `"Invoice Created"` (confirmation). `invoice rows = 0` — **no POSTED row was created** (confirmed via the sandbox DB channel). `final.png` shows the form completely empty (every field blank).
- **WHERE it failed:** the model **click-locked on the Customer field**. All 24 actions are `kind:"click"` at ~`(x≈277, y∈[261,305])` — a tight band on the Customer input. It **never emitted a single `type` action**, so no text was ever entered. The rationales repeatedly claim "…then I will type ACMECORP" but the emitted action stays `click`. Full trace: `artifacts/runs/r_mtjgq7rq_s0/trace.json`.
- **Why not `stuck`:** the clicks are not byte-identical (vary by a few px) and clicking an input field changes the focus ring (so the screenshot isn't byte-identical), so the literal DESIGN §3 stuck rule (`identical clicks` + `no new screenshot`) does not fire. The honest terminal is `step_cap`.
- **Interpretation:** this is a **model behavior** limitation (opencode-go-messages-minimax-m3), not a harness defect. The screenshot→action→execute→trace→cleanup harness worked flawlessly the whole way; the baseline model simply does not follow its own "click then type" plan — it keeps re-clicking the same field. This is exactly the kind of honest generalization data ColdStart is designed to capture. `type`/`press`/`nav` were exercised only in the mock test (the live model never requested them), so live `keyboard.type`/`press` wiring is untested by this run.

### 4.3 Cleanup log (zero live resources)

From `artifacts/step-04-live.log`:

```
cleanup: kill sandbox, close browser + solari client
sandbox killed
browser session closed
solari client closed
CLEANUP ATTESTATION: live ColdStart resources after cleanup = 0
CLEANUP: ZERO live resources
```

Independently re-verified with a separate SDK probe after the run:
`coldstart-tagged sandboxes = 0` and `ALL live sandboxes on this account = 0`. There is no live browser session left (the loopback proxy was shut down via `driver.shutdown()`, which prevents the known "process hangs" gotcha; `browser.close()` released the session).

## 5. Deviations from plan

- **Entry path:** the loop starts at `new URL('/new', previewUrl)` (the form), not `'/'`. Chosen to keep the single live run focused and cost-bounded (the doctrine is vision-first; starting at the form is a harness entry decision, not a DOM shortcut). The agent still had to fill every field, submit, and reach the confirmation page.
- **`COLDSTART_MAX_STEPS=24`** (slightly above the "e.g. 20" suggestion) to give the baseline a fair shot within a hard cost cap; still a low, bounded budget.
- **`nav` reducer** uses a query-string-preserving builder (`new URL(path, base)` + carry-over) rather than a bare `new URL(path, base).href`, because the Solari `previewUrl` carries a `?pt_token=` that a bare `new URL` would silently drop (DESIGN §7 — verified `hasQueryString=true` this run). This is a required correctness detail, not a doctrine change.
- **Screenshots per step** are persisted to `artifacts/runs/<run_id>/` as direct evidence that each decision came from pixels (stronger than DESIGN §3's minimum "trace only").

## 6. Self-check vs acceptance criteria

| Criterion | Met? | Evidence |
| --- | --- | --- |
| (a) Traces are screenshot→action, no DOM access anywhere | **yes** | The agent module calls only `mouse.click`/`keyboard.type`/`keyboard.press`/`goto` (action.ts) + `screenshot`/`title` (loop.ts). No `locator()`/`innerText`/`$eval`/accessibility/bounding-boxes. Each step links to a saved screenshot: `trace.json → actions[].screenshot → step-NN.png`. |
| (b) Baseline task completes OR honestly classified | **yes** | Honest PARTIAL: `step_cap`, final title `"Create Invoice"`, `invoice rows=0`, form empty. Failure mode documented (§4.2). No success faked. |
| (c) LLM key scoped to the loop only | **yes** | `LLM_API_KEY` is read only in `model.ts` via `process.env` (sourced `.env` in-shell) and used only in the OpenAI auth header. It is never written to any file, never logged, never passed to the variant app / verifier / browser. `grep` found no key in `src/agent`, `test`, or the artifacts. |
| (d) Zero live resources at end | **yes** | Cleanup log (§4.3): sandbox killed, browser closed, client closed, `live ColdStart resources after = 0`. Independent re-probe: `ALL live sandboxes on this account = 0`. |
| (e) No secrets | **yes** | `grep` for `slr_live_` / `sk-…` / `LLM_API_KEY=` literal / `Bearer …` over `src/agent`, `test/agent-loop.spec.ts`, `trace.json`, `step-04-live.log` → only a deliberate **fake** test token (`pt_token=abcdef123456` in the mock fixture) which the test asserts is redacted in the trace. Trace `base_url` is masked (`?pt_token=************`). |

## 7. Open questions / risks

- **Baseline model capability:** `opencode-go-messages-minimax-m3` (LLM_MODEL) click-locks on the first field and never emits `type`. For the Step 06 scorecard to produce a meaningful signal, the model choice matters — a stronger computer-use/agent model, or a prompt that forces strict `click`→`type` alternation (e.g. mirroring a "must alternate" grammar), may be needed. This is a model/prompt risk, not a harness risk.
- **Stuck heuristic coverage:** the literal DESIGN §3 rule (`identical clicks` + `identical screenshot`) misses near-identical region loops that nevertheless change focus-ring pixels. Consider a future tolerance+cue heuristic (e.g. consecutive clicks in the same small region with no new text/history signal) — but this should be weighed against over-terminating legitimate sequences. Left faithful to the design for now.
- **Live `type`/`press`/`nav` untested:** the live model never requested them, so those paths are proven only in mock. A follow-up could force a `type` (e.g. a scripted live probe) to confirm Playwright `keyboard.*` against the Solari page.
- **`done` is a claim, not success:** Step 04 stops and records on `done`. The verifier (Step 05) must run to convert a `done` claim into a success verdict. Not built here per scope.
- **Snapshot/fork not exercised:** Step 04 used `createBaseSandbox` + serve directly (no `forkVariant`/template), which is the correct minimal path for a single-run baseline. Matrix forking is Step 06.

## 8. Secrets & cleanup attestation

- [x] No API keys/secrets in the repo or this report. `SOLARI_API_KEY` and `LLM_API_KEY` were sourced only in-shell (`set -a; . ./.env; set +a`) and read from `process.env` at runtime; never logged, never written to a file. The `artifacts/step-04-live.log` and `trace.json` contain redacted preview URLs (`?pt_token=************`).
- [x] All Solari resources killed / VMs terminated. Cleanup proof (§4.3): sandbox `kill()`ed, browser session `close()`d, `LiveSolari.shutdown()` called (closes the loopback proxy so the process doesn't hang). Independent re-probe confirms **0 live sandboxes on the account**. Browser client closed.
