# Step 07 — Submission packaging (README + demo + hygiene) — Report

- **Status:** DONE
- **Mode:** N/A (packaging only — **no live Solari/LLM runs**; demo built from existing captured frames)
- **Agent:** repo-surgeon (docs + hygiene subagent)
- **Date:** 2026-09-02

## 1. What was done

Packaged the ColdStart submission into a readable, honest, self-contained form. No live
Solari/LLM call was made (cost control) — everything was built from **existing captured
artifacts** (Step 06 scorecard + per-run evidence + captured step screenshots).

1. **Rewrote `README.md`** (repo root) from the generic fork cookbook README into the
   ColdStart submission README: title, the **why** (Pinetree's "intelligence isn't the
   bottleneck, execution is" / *Hallucinate Westworld* zero-shot-generalization thesis),
   **what it does**, the 5 perturbation axes table, an architecture diagram, the
   vision-first doctrine + fail-closed verifier, the **results summary** (success-by-axis
   + per-variant table + headline finding), a **model note**, **cost**, **how to run**
   (npm install → `.env` with `SOLARI_API_KEY` + `LLM_*` → `gen:variants` → `typecheck` →
   `test` → `build` → baseline run → scorecard), **limitations**, and the demo pointer.
2. **Built the demo asset** `artifacts/demo.gif` — a 16-frame animated walkthrough of the
   **successful** run `r_mtjqchve_s17` (P1:4 relabel + P3:3 field-density variant),
   stitched from the agent's captured per-step screenshots (`step-01.png…step-16.png`,
   with `final.png` == `step-16.png`, the "Recorded" confirmation frame). Used `ffmpeg`
   (available); GIF is 960×600, 16s @ 1 fps, 63 KB, infinite loop.
3. **Hygiene pass**: refreshed `.env.example` (all 4 vars, names only), removed a throwaway
   script (`scripts/screenshot-variants.mjs`), cleaned local dev `data/*.db`
   (`invoice.db`, `p1.db`, `p2.db`) + the now-empty `data/` dir, confirmed `.gitignore`,
   ran `npm run typecheck` (0 errors) and `npm test` (37 passed), and grepped tracked +
   deliverable text for secrets (none).

## 2. Commands run

```bash
cd "C:/Users/oneda/Projects/Research - General/coldstart/solari-cookbook"

# typecheck + tests (offline, no keys)
npm run typecheck        # tsc -p tsconfig.json --noEmit  -> EXIT 0
npm test                 # vitest run -> 37 passed (4 files)

# demo GIF from the successful run's captured frames
cd artifacts/runs/r_mtjqchve_s17
ffmpeg -y -framerate 1 -i step-%02d.png -vf "scale=960:600" -plays 0 -loop 0 ../../demo.gif
# -> artifacts/demo.gif (16 frames, 960x600, 16.00s @ 1 fps, 63 KB, GIF89a)

# hygiene: remove throwaway script + local dev DBs
rm -f scripts/screenshot-variants.mjs
rm -f data/invoice.db data/p1.db data/p2.db   # then rmdir data (now empty)

# secret grep (no real keys)
grep -rInE "slr_live_[A-Za-z0-9]{6,}|sk-[A-Za-z0-9]{16,}|Bearer [A-Za-z0-9._-]{12,}" \
  README.md .env.example DESIGN.md package.json scripts/ variants.json   # -> none
```

## 3. Deliverables

- `README.md` (repo root) — the rewritten ColdStart submission README.
- `artifacts/demo.gif` — 16-frame animated demo of the successful `r_mtjqchve_s17` run.
- `.env.example` — all 4 env var names only (`SOLARI_API_KEY`, `LLM_API_KEY`,
  `LLM_ENDPOINT`, `LLM_MODEL`), no values.
- `scripts/` — now only `run-step-03.sh`, `run-step-06.sh` (throwaway `screenshot-variants.mjs`
  removed).
- `reports/step-07-packaging.md` — this report.

## 4. Evidence

- **README headline finding accurate to the evidence** → README "Results (Step 06)" table mirrors
  `artifacts/scorecard.json` `runs[]` (seeds 0/17/9/21/3, statuses ok/ok/step_cap/step_cap/aborted,
  task_completed true/true/false/false/false) and `success_by_axis` (P1 0.33 / P2 0.00 / P3 0.25 /
  P4 0.00 / P5 0.00). Verifier details (7/7 checks, evidence_hash, totals) from
  `artifacts/scorecard.json` and `artifacts/runs/r_mtjqchve_s17/trace.json`.
- **Demo matches a real run** → `artifacts/demo.gif` is built **from the actual per-step PNGs** of
  the successful run `artifacts/runs/r_mtjqchve_s17/step-01.png…step-16.png`; `trace.json` (same
  run) records the exact action per step (e.g. step 15 `click (308,674)` "submit with Confirm",
  step 16 `done` "confirmation page shows invoice INV-2026-0001 … POSTED status"). `final.png`
  md5 == `step-16.png` md5 (`a0192290…`), so the GIF ends on the "Recorded" confirmation frame.
- **Repo clean / no secrets** → `grep` over tracked files (via `git ls-files`), `.env.example`,
  `README.md`, `DESIGN.md`, `package.json`, `scripts/`, `src/`, `test/`, `variants.json`, and
  `artifacts/*.{md,json,log}` for `slr_live_`/`sk-`/`Bearer` → **no real key found** (only Solari
  resource/session ids in `scorecard.json`, which are not credentials; preview URLs are redacted
  to `?pt_token=************` in logs/traces).
- **Typecheck/test** → `npm run typecheck` exit 0; `npm test` 37/37 passed (4 files: prng 5,
  axes 10, verifier 13, agent-loop 9).
- **Temp/dead files** → `find` for `_*.mts`/`_*.mjs`/`*.bak`/`*.orig`/`*.tmp`/`*~` (excluding
  node_modules/examples/.git) → none. `git status` untracked list is solely intended deliverables
  (+ pre-existing `.gitignore`/`README` modifications). `artifacts/runs/` left as-is (gitignored);
  `artifacts/repeat/` kept (evidence).

## 5. Deviations from plan

1. **Demo is a GIF, not a screen recording.** MASTER_PLAN Step 07 allows a 60–90s live screen
   recording; **no live agent was run** (cost control), so the demo is a GIF assembled from the
   already-captured per-step screenshots of a successful run — the sanctioned fallback
   ("annotated trace" style). It is honest: it shows pixels, not a re-run.
2. **README narrative reflects the honest post-hoc finding** (relabeling is robust, structure/
   theme break it) rather than the pre-run "expected hardest" prior; this is exactly what the
   evidence shows and is the truthful submission.
3. **`screenshot-variants.mjs` removed.** It was a one-time Step-02 visual-diff generator,
   unreferenced anywhere, and depended on `playwright-core`, which is **not** a declared
   dependency. It is a throwaway, not the deliverable; the generated `artifacts/step-02/`
   screenshots remain as evidence.
4. **Local `data/*.db` removed.** These were Step-02 local dev databases (gitignored); the ground
   truth that matters is captured per run under `artifacts/runs/*/invoice.db`.

## 6. Self-check vs acceptance criteria

| Criterion (MASTER_PLAN Step 07) | Met? | Evidence |
| --- | --- | --- |
| README is accurate to the evidence in prior reports | yes | §4: results table/axes/verifier numbers copied from `artifacts/scorecard.json`; model note matches Step 04 (only GPT-5.6-luna completed); limitations honestly surfaced (n=1, confound, s3 infra-abort, replay/credits null) |
| Demo matches a real run | yes | §4: `artifacts/demo.gif` built from `runs/r_mtjqchve_s17/step-*.png`; `trace.json` + `final.png==step-16.png` corroborate |
| Repo clean (grep for secrets) | yes | §4: no `slr_live_`/`sk-`/`Bearer` in tracked or deliverable text; keys read from gitignored `.env` only |
| Tests pass | yes | `npm test` 37/37 built; `npm run typecheck` exit 0 |

## 7. Open questions / risks

- **`artifacts/runs/` is gitignored**, so the per-run evidence is not committed. If the reviewer
  wants the traces/screenshots in-repo, either lift the gitignore rule or link to the scorecard's
  `action_trace_path`. The scorecard + `where-it-breaks.md` + `curve.png` + README are committed.
- **`artifacts/repeat/` (Step 04b logs) is committed** (not gitignored) — intentional evidence,
  but confirm that's acceptable for the submission size.
- **Model names in the README** (`opencode-go-responses-gpt-5-6-luna`) are provider-specific but
  not secrets; fine to retain for reproducibility.
- **Recommendation (not done here):** the scorecard is n=1 + confounded. A follow-up axis-isolated
  matrix (P2:3 alone, P5:3 alone, P3:4 alone, n≥3) would turn the headline finding from
  "indicative" into "causal".

## 8. Secrets & cleanup attestation

- [x] No API keys/secrets in the repo or this report. Keys are read from gitignored `.env` via
      `process.env`, sourced in-shell; never logged/written/echoed. `grep` over tracked + deliverable
      text for `slr_live_`, `sk-`, `Bearer` → **no real key**; only `SOLARI_API_KEY`/`LLM_*` **names**
      appear (in `.env.example`), and preview URLs are redacted in logs/traces.
- [x] Temp/dead files removed: `scripts/screenshot-variants.mjs` (throwaway, unreferenced);
      `data/invoice.db`, `data/p1.db`, `data/p2.db` + empty `data/` dir.
- [x] No live Solari/LLM resources were created this step (no live run). `artifacts/runs/` evidence is
      from the Step 06 run, which already attested `killed=5 liveAfter=0` → `CLEANUP: ZERO live resources`.
- [x] `artifacts/repeat/` and `artifacts/runs/` left in place (evidence; runs remain gitignored).
- [x] `.env` (real) not modified; not committed.
