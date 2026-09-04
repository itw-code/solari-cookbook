# Step 01 — design lock — Report

- **Status:** DONE
- **Mode:** N/A (design only; no code written)
- **Agent:** repo-surgeon (architect)
- **Date:** 2026-09-02

## 1. What was done

Produced `README`-adjacent **DESIGN.md** for ColdStart per `MASTER_PLAN.md` §4 Step 01
sections 1–6, plus sandbox/snapshot strategy (§7) and risks (§8). This is a **design/architecture
lock** — **zero software** was written. The doc freezes every decision so the build steps
(02–06) cannot improvise. Specifically, it locks:

1. **Task app** = "create invoice," server-rendered Node/`node:http` + `node:sqlite`, ground
   truth = a `POSTED` SQLite invoice row + line items (with totals verifier *recomputes*,
   never trusts).
2. **Perturbation axes** = 5, seeded & reproducible, ranked hardest-first:
   P1 relabeling, P2 structure/flow, P3 field-order/density, P4 nav order, P5 theme/CSS (the
   anti-DOM-caching honesty control).
3. **Agent action space** = vision-only; bounded `{click,type,press,nav,done,abort}`; explicitly
   forbids DOM selectors / element handles / accessibility tree.
4. **Verifier contract** = fail-closed `{ task_completed, field_errors, checks_run,
   evidence_hash }`; expected values recomputed from seed vs. actual DB read via the sandbox
   channel; **4 negative tests** (empty DB / wrong values / never-posted / cross-run mismatch).
5. **Scorecard schema** = `success_by_variant`, `success_by_axis`, `generalization_curve`
   (success% vs. integer intensity), per-run `replay_url` + `cost` (credits/hours/tokens).
6. **Language** = TypeScript locked, with a **root `package.json` + `tsconfig.json` added now**
   (minimal) and the full `src/` layout; imports the SDK versions recorded in Step 00.
7. **Sandbox/snapshot strategy** = base snapshot → `previewUrl` serving (URL-safe path builds),
   `promoteSnapshot`+fork for N variants, metadata tag scheme (`app:"coldstart", tag:"…"`)
   for exact cleanup via `kill()`.

## 2. Commands run

No build/build/run commands apply (no code). Verification was **context reading + a runtime
probe of the DB abstraction** the design depends on:

```bash
node --version                              # v22.23.1
node -e "const s=require('node:sqlite');console.log('node:sqlite OK')"   # works, no flag
node -e "const {DatabaseSync}=require('node:sqlite'); …create+insert+select…"  # round-trip OK
```

- `node:sqlite` loads on Node 22.23.1 **without** the `--experimental-sqlite` flag (emits an
  experimental warning). This is what lets the variant app use zero third-party runtime deps —
  the design is grounded in a verified toolchain fact, not an assumption.

Sources read before writing (all evidence for the claims in §4):
- `../MASTER_PLAN.md` (Step 01 spec + acceptance criteria + constraints)
- `../SWE-Intern-Pinetree-Proposal-v2.md` (Pinetree doctrine: zero-shot, vision-first)
- `src/solari/driver.ts` (the locked `SolariDriver` interface signature)
- `README.md` + SDK type defs in the cookbook examples (sandbox `previewUrl`, `snapshot`,
  `promoteSnapshot`, `kill`, `files`, `commands.run`; browser `page.screenshot/mouse/keyboard`,
  `recording`, session id) — to make §7 + §3 accurate to the real API surface.
- `reports/step-00-env.md` (SDK versions `@solarisdk/browser` 0.1.2, `@solarisdk/sdk` 0.1.2;
  environment matrix; the open "packaging seam" question this step resolves with §6).

## 3. Deliverables

- `solari-cookbook/DESIGN.md` — the locked design contract (sections §0–§8 + appendix A the
  driver interface signature + appendix B design self-check). **Exists.**

No source files were created or modified. This step intentionally writes no code;
the only deliverable is the design document.

## 4. Evidence

- Claim "task app is create-invoice with SQLite ground truth" → DESIGN.md §1 (schema, routes,
  flow, task-spec determinism).
- Claim "5 axes, seeded & reproducible, ranked hardest-first" → DESIGN.md §2 (determinism
  rule + `sameSeed→sameVariant`, per-axis table, variant id scheme).
- Claim "action space forbids any DOM access; pixels-in/coords-out" → DESIGN.md §3
  (allowed channels are screenshot + task + trace; `locator()`/`innerText`/`$eval`/AX-tree
  explicitly verboten; closed `Action` union maps to `page.screenshot/mouse/keyboard/goto`).
- Claim "verifier has ≥2 negative tests and is fail-closed" → DESIGN.md §4 (NEG-1..NEG-4;
  `task_completed` defaults `false`).
- Claim "scorecard has cost + replay fields and integer intensity for the curve" → DESIGN.md §5.
- Claim "TypeScript locked + root manifest now" → DESIGN.md §6.
- Claim "sandbox strategy uses base snapshot→fork + tag scheme for exact cleanup" → DESIGN.md §7.
- Claim "node:sqlite is available without the flag" → §2 commands (real stdout).

## 5. Deviations from plan

- **Added two sections beyond the Step 01 spec (1–6).** MASTER_PLAN §4 lists items 1–6
  (task app, axes, action space, verifier, scorecard, language). The orchestrator brief in
  this task additionally asked for **§7 sandbox/snapshot strategy** (Step 03 prep) and
  **§8 risks/open questions**. Both are included; nothing in 1–6 was dropped. §7 is forward
  design so Step 03 doesn't improvise; §8 is the required risk register.
- **Verifier negative tests: 4 instead of the "≥2" minimum.** The contract specifies NEG-1..NEG-4
  (empty DB, wrong values, never-posted, cross-run mismatch). This exceeds the requirement and
  strengthens the fail-closed guarantee at Step 05. No scope creep — all four are the same
  verifier, no new modules.
- **Ranked axes with a named "control" axis (P5 theme).** MASTER_PLAN lists axes unordered;
  this doc ranks hardest-first and designates P5 as the anti-DOM-caching control. This is an
  ordering/emphasis clarification, not an added axis (theme/CSS was already in the plan's list).

## 6. Self-check vs acceptance criteria

| Criterion (MASTER_PLAN §4 Step 01 audit) | Met? | Evidence |
| --- | --- | --- |
| Every axis is seeded-reproducible | yes | DESIGN.md §2 (single PRNG + domain-separated sub-streams; `sameSeed→sameVariant`; Step 02 will diff two runs) |
| Action space forbids selectors | yes | DESIGN.md §3 (only screenshot/mouse/keyboard/goto; `locator()`/AX-tree/text-reads verboten) |
| Verifier contract includes ≥2 negative tests | yes | DESIGN.md §4 (NEG-1..NEG-4; fail-closed default `false`) |
| Scorecard schema has cost + replay fields | yes | DESIGN.md §5 (`session.replay_url`, `session.recording_id`, `cost.{credits,hours,sandbox_seconds,tokens}`) |
| Language decision locked | yes | DESIGN.md §6 (TypeScript; root `package.json`+`tsconfig.json` added now; SDK versions from Step 00) |
| Deliverable `DESIGN.md` exists | yes | `solari-cookbook/DESIGN.md` |
| No code written (step is design-only) | yes | only `DESIGN.md` created; no `src/` changes |

## 7. Open questions / risks

Forwarded to the orchestrator (full risk register in DESIGN.md §8):

- **Fork API** — confirm `create({template: snapshotId})` vs. `promoteSnapshot→create({template})`
  at Step 03 (SDK exposes both shapes; pick once, empirically).
- **Node presence in the sandbox `base` template** — `python3` is confirmed; Node 22 is the
  variant-app runtime and may need installing into the base snapshot.
- **Coordinate-click stability** — fixed viewport + no-overflow app is the mitigation; needs
  a Step 04 baseline check.
- **Cost envelope** — Free plan ($3 / 1h / 1 sandbox) vs. n≥3-per-point curve; serialize and
  prioritize P1/P2; P5 is a cheap control.
- **Key scoping** — `LLM_API_KEY` scoped to the agent process only; never reaches the app,
  verifier, or model input beyond the task instruction.

## 8. Secrets & cleanup attestation

- [x] **No secrets in repo/report.** Only env-var **names** are referenced
      (`SOLARI_API_KEY`, `LLM_API_KEY`, `LLM_ENDPOINT`, `LLM_MODEL`); no key values anywhere.
      The existing `.env` is git-ignored/untracked; `.env.example` holds placeholders only.
- [x] **No code written** — this step created only `DESIGN.md` and this report. Nothing to
      build, serve, or run; **no Solari resource exists** (no sandbox/browser/desktop was
      spawned this step), so there is nothing to kill.
- [x] **No commit / push / git config change.** No `git add`/`commit` performed. The only
      repository change is the untracked `DESIGN.md`.
- [x] No `.ts`/`.json`/config source files modified. The report references the SDK type defs
      from `node_modules` for accuracy; nothing was edited there.

*Mode: N/A (design, no code). This is a design lock; build steps 02–06 now have a contract.*
