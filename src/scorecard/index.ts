/**
 * index.ts — ColdStart STEP 06 LIVE runner: the cost-bounded generalization
 * scorecard evaluation. CLI: `tsx src/scorecard/index.ts` (env sourced in-shell,
 * e.g. `set -a; . ./.env; set +a`).
 *
 * Runs EXACTLY the 5-variant run set (n=1 each), reusing ONE browser session
 * across all variants and creating/killing each variant's sandbox SERIALLY
 * (Free plan = 1 concurrent). After each variant it captures the invoice DB via
 * the sandbox FILE channel, writes it to the run dir, and runs
 * `verifyAgainstPath({seed, dbPath})` for ground truth — never trusting the
 * agent's narration or the `done` claim. Every sandbox is `kill()`ed immediately
 * after its variant; everything is killed at the end and zero live resources are
 * asserted (DESIGN §7, MASTER_PLAN Step 06 acceptance: cleanup total).
 *
 * COST BOUND: do NOT exceed the 5 variants. GPT-5.6-luna is expensive.
 *
 * SECURITY: SOLARI_API_KEY / LLM_API_KEY are read from process.env ONLY,
 * sourced from gitignored `.env`. They are never logged or written. Preview URLs
 * are redacted in every printed line and in the artifacts.
 */

import { readFileSync, writeFileSync, mkdirSync } from "node:fs"
import { resolve, dirname, join } from "node:path"
import { fileURLToPath } from "node:url"
import { SolariClient, type Sandbox } from "@solarisdk/sdk"
import { createDriver } from "../solari/driver.ts"
import { forkVariant, cleanup, buildUrl, type Fork } from "../solari/orchestrate.ts"
import { deriveTaskSpec } from "../generate-variants/task-spec.ts"
import { runAgentLoop } from "../agent/loop.ts"
import { createModelCaller, type ModelCaller, type ModelTurnInput, type ModelDecision } from "../agent/model.ts"
import { DEFAULT_VIEWPORT } from "../agent/screenshot.ts"
import { verifyAgainstPath, DEFAULT_DB_PATH } from "../verify/verifier.ts"
import { buildScorecard, writeScorecard, isSuccess, type RunRecord, type AxisKey } from "./build.ts"
import { estimateImageTokens, estimateTextTokensPerCall, estimateOutTokensPerCall } from "./cost.ts"
import { renderCurvePng } from "./curve.ts"

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

/** The exact cost-bounded run set (seed, n=1 each). DO NOT EXPAND. */
const RUN_SET = [0, 17, 9, 21, 3]
const MAX_STEPS = Number(process.env.COLDSTART_MAX_STEPS ?? 40)
const REAP_WAIT_MS = 6000 // free-plan host-slot reap between sandboxes

const ARTIFACT_ROOT = resolve("artifacts")
const SCORECARD_PATH = join(ARTIFACT_ROOT, "scorecard.json")
const CURVE_PATH = join(ARTIFACT_ROOT, "curve.png")
const BREAKS_PATH = join(ARTIFACT_ROOT, "where-it-breaks.md")

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

function requireEnv(name: string): string {
  const v = process.env[name]
  if (!v || v.length === 0) throw new Error(`${name} is not set — source .env in-shell first`)
  return v
}
function log(msg: string): void {
  console.log(`[scorecard] ${msg}`)
}
const now = (): number => performance.now()
const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms))
function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

interface VariantProfile {
  variant_id: string
  seed: number
  intensity_by_axis: Record<AxisKey, number>
  task_instruction: string
}

function loadVariants(): VariantProfile[] {
  const raw = JSON.parse(readFileSync(resolve("variants.json"), "utf8")) as {
    variants: Array<{ variant_id: string; seed: number; intensity_by_axis: Record<AxisKey, number>; task_spec: { instruction: string } }>
  }
  return raw.variants.map((v) => ({
    variant_id: v.variant_id,
    seed: v.seed,
    intensity_by_axis: v.intensity_by_axis,
    task_instruction: v.task_spec.instruction,
  }))
}

/** A ModelCaller that counts every decide() turn (LLM calls, ESTIMATE of HTTP calls). */
function makeCountedModel(base: ModelCaller, counter: { calls: number }): ModelCaller {
  return {
    async decide(input: ModelTurnInput): Promise<ModelDecision> {
      counter.calls += 1
      return base.decide(input)
    },
  }
}

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  const apiKey = requireEnv("SOLARI_API_KEY")
  const modelLabel = requireEnv("LLM_MODEL")

  const client = new SolariClient({ apiKey })
  const driver = createDriver("live")
  const profiles = loadVariants()
  const runSet = RUN_SET.map((seed) => {
    const p = profiles.find((v) => v.seed === seed)
    if (!p) throw new Error(`variant seed ${seed} not present in variants.json`)
    return p
  })

  const runs: RunRecord[] = []
  const allSandboxes: Sandbox[] = []

  type BrowserSessionType = Awaited<ReturnType<typeof driver.launchBrowser>>
  let browser: BrowserSessionType | null = null
  let page: Awaited<ReturnType<BrowserSessionType["newPage"]>> | null = null

  log(`browser launch (recording=true, viewport ${DEFAULT_VIEWPORT.width}x${DEFAULT_VIEWPORT.height})`)
  const b = await driver.launchBrowser({ recording: true })
  browser = b
  try {
    page = await b.newPage()
    await page.setViewportSize({ width: DEFAULT_VIEWPORT.width, height: DEFAULT_VIEWPORT.height })
    await page.emulateMedia({ reducedMotion: "reduce" })
  } catch (e) {
    // Browser up-front failure is fatal — nothing can run without a browser.
    b.close().catch(() => undefined)
    await driver.shutdown().catch(() => undefined)
    throw new Error(`browser launch failed: ${errText(e)}`)
  }
  const recordingId = browser ? (browser as unknown as { id: string }).id : null

  try {
  for (const profile of runSet) {
    const seed = profile.seed
    const runId = `r_${Date.now().toString(36)}_s${seed}`
    const runDir = join(ARTIFACT_ROOT, "runs", runId)
    mkdirSync(runDir, { recursive: true })

    log(`\n=== VARIANT seed=${seed} (${profile.variant_id}) run_id=${runId} ===`)

    const counter = { calls: 0 }
    const tSandboxStart = now()
    let fork: Fork | null = null
    let loopErr: string | undefined
    let loop: Awaited<ReturnType<typeof runAgentLoop>> | null = null
    let verifier: RunRecord["outcome"]["verifier"] | null = null
    let browserSeconds = 0
    let fallbackSteps = 0

    // ---- provision + serve the variant sandbox (VARIANT_SEED=seed) ----
    try {
      fork = await forkVariant(client, undefined, seed, profile.variant_id)
      allSandboxes.push(fork.sandbox)
      log(`sandbox ${fork.sandbox.sandboxId} [${fork.bootMode}] booted ${fork.bootMs.toFixed(0)}ms; healthz=${fork.healthz.ok}; invoices=${fork.invoiceCount}`)
      log(`preview (redacted): ${fork.preview.baseDisplay}`)
      if (!fork.healthz.ok) throw new Error(`variant app failed to become healthy (status ${fork.healthz.status})`)

      // ---- drive the shared browser to this variant's /new entry ----
      await page!.goto(buildUrl(fork.preview.base, "/new"))

      // ---- run the vision-first agent loop ----
      const taskInstruction = deriveTaskSpec(seed).instruction // never sends `expected` to the model
      const tLoopStart = now()
      try {
        loop = await runAgentLoop({
          page: page!,
          model: makeCountedModel(createModelCaller(), counter),
          baseUrl: fork.preview.base, // keeps ?pt_token= (buildUrl is internal to nav handling)
          task: taskInstruction,
          runDir,
          runId,
          seed,
          variantId: profile.variant_id,
          maxSteps: MAX_STEPS,
          viewport: DEFAULT_VIEWPORT,
          modelLabel,
        })
      } catch (e) {
        loopErr = errText(e)
        log(`agent loop infra error: ${loopErr}`)
        // The loop writes the trace BEFORE it re-throws; recover the true step count.
        try {
          const t = JSON.parse(readFileSync(join(runDir, "trace.json"), "utf8")) as { steps_taken?: number }
          if (typeof t.steps_taken === "number") fallbackSteps = t.steps_taken
        } catch {
          /* no trace written */
        }
      }
      browserSeconds = (now() - tLoopStart) / 1000

      // ---- capture the invoice DB via the sandbox FILE channel ----
      let dbBytes: Uint8Array | null = null
      try {
        dbBytes = await fork.sandbox.files.read(DEFAULT_DB_PATH)
        const dbPath = join(runDir, "invoice.db")
        writeFileSync(dbPath, dbBytes)
        verifier = await verifyAgainstPath({ seed, dbPath })
        log(`verifier: task_completed=${verifier.task_completed} field_errors=${verifier.field_errors.length} checks=${verifier.checks_run.length} hash=${verifier.evidence_hash.slice(0, 12)}`)
      } catch (e) {
        log(`DB capture / verify failed: ${errText(e)}`)
      }
    } catch (e) {
      loopErr = loopErr ?? errText(e)
      log(`variant setup failed: ${loopErr}`)
    } finally {
      // ---- kill the sandbox immediately after its variant (never close()) ----
      if (fork) {
        try {
          await fork.sandbox.kill()
          log(`sandbox ${fork.sandbox.sandboxId} killed`)
        } catch (e) {
          log(`sandbox kill error: ${errText(e)}`)
        }
      }
      // reap wait so the free-plan host slot frees before the next variant
      if (runSet.indexOf(profile) < runSet.length - 1) {
        log(`reap-wait ${REAP_WAIT_MS}ms`)
        await sleep(REAP_WAIT_MS)
      }
    }

    // ---- derive honest outcome status ----
    const terminatedBy = loop ? loop.terminatedBy : "abort"
    let status: RunRecord["agent"]["status"]
    if (!loop) {
      status = "aborted"
    } else if (loop.status === "done") {
      status = verifier?.task_completed ? "ok" : "verifier_fail"
    } else {
      status = loop.status // stuck | step_cap | aborted
    }

    const taskCompleted = status === "ok"
    const failClosedVerifier: RunRecord["outcome"]["verifier"] = verifier ?? {
      task_completed: false,
      field_errors: [],
      checks_run: [{ check: "C1", passed: false, detail: "no artifact captured (variant/sandbox error)" }],
      evidence_hash: "",
    }

    const imgTokens = estimateImageTokens()
    const textTokens = estimateTextTokensPerCall()
    const outTokens = estimateOutTokensPerCall()
    const llmCalls = counter.calls

    const run: RunRecord = {
      run_id: runId,
      variant_id: profile.variant_id,
      seed,
      intensity_by_axis: profile.intensity_by_axis,
      agent: {
        model: modelLabel,
        steps_taken: loop?.stepsTaken ?? fallbackSteps,
        max_steps: MAX_STEPS,
        terminated_by: terminatedBy,
        status,
        error: loopErr ?? null,
      },
      outcome: {
        status,
        task_completed: taskCompleted,
        action_trace_path: join(runDir, "trace.json"),
        verifier: failClosedVerifier,
      },
      session: {
        replay_url: null,
        recording_id: recordingId ?? null,
        sandbox_id: fork?.sandbox.sandboxId ?? null,
        snapshot_id: null,
        fixture_path: null,
      },
      cost: {
        credits: null,
        hours: (browserSeconds + sandboxSecondsFrom(fork, tSandboxStart)) / 3600,
        sandbox_seconds: sandboxSecondsFrom(fork, tSandboxStart),
        browser_seconds: browserSeconds,
        model_tokens_in: llmCalls * (imgTokens + textTokens),
        model_tokens_out: llmCalls * outTokens,
        model_request_count: llmCalls,
        llm_calls: llmCalls,
      },
    }
    runs.push(run)

    log(`RESULT seed=${seed}: status=${status} terminatedBy=${terminatedBy} task_completed=${taskCompleted} steps=${loop?.stepsTaken ?? 0}/${MAX_STEPS} llm_calls=${llmCalls} sandbox=${run.cost.sandbox_seconds.toFixed(0)}s browser=${browserSeconds.toFixed(0)}s`)
    log(`SUCCESS=${isSuccess(run) ? "YES" : "NO"}`)

    // persist the per-run record for auditability
    mkdirSync(runDir, { recursive: true })
    writeFileSync(join(runDir, "run.json"), JSON.stringify({ ...run, session: { ...run.session, replay_url: null } }, null, 2))
  }

  // ---- aggregate + emit artifacts ----
  log("\n=== AGGREGATE + EMIT ===")
  const scorecard = buildScorecard({
    runs,
    config: { max_steps: MAX_STEPS, viewport: `${DEFAULT_VIEWPORT.width}x${DEFAULT_VIEWPORT.height}`, n_runs_per_point: 1, mode: "LIVE" },
  })
  await writeScorecard(SCORECARD_PATH, scorecard)
  log(`scorecard -> ${SCORECARD_PATH}`)
  await renderCurvePng(runs, CURVE_PATH)
  log(`curve -> ${CURVE_PATH}`)
  writeBreaks(BREAKS_PATH, scorecard)
  log(`breaks -> ${BREAKS_PATH}`)
  } finally {
    // ---- final cleanup (ALWAYS runs, even on error) ----
    log("\n=== FINAL CLEANUP ===")
    if (page) await page.close().catch(() => undefined)
    if (browser) await browser.close().catch(() => undefined)
    await driver.shutdown().catch(() => undefined)
    const cleanupResult = await cleanup(client, { sandboxes: allSandboxes })
    log(`CLEANUP ATTESTATION: killed=${cleanupResult.killed.length} liveAfter=${cleanupResult.liveAfter.length}`)
    log(cleanupResult.liveAfter.length === 0 ? "CLEANUP: ZERO live resources" : `CLEANUP WARNING: ${cleanupResult.liveAfter.length} remaining`)
  }
}

// compute sandbox seconds (0 if the fork failed to create)
function sandboxSecondsFrom(fork: Fork | null, tStart: number): number {
  return fork ? (performance.now() - tStart) / 1000 : 0
}

function writeBreaks(path: string, scorecard: ReturnType<typeof buildScorecard>): void {
  mkdirSync(dirname(path), { recursive: true })
  const lines: string[] = []
  lines.push("# ColdStart — where it breaks (Step 06)")
  lines.push("")
  lines.push(`- Generated: ${scorecard.generated_at}`)
  lines.push(`- Run set: ${scorecard.runs.map((r) => `s${r.seed}`).join(", ")} (n=1 each)`)
  lines.push(`- Success defined: agent \`status === "ok"\` AND verifier \`task_completed === true\`.`)
  lines.push("")
  lines.push("## Per-variant result")
  lines.push("")
  lines.push("| run_id | seed | variant_id | terminated_by | status | task_completed | success |")
  lines.push("| --- | --- | --- | --- | --- | --- | --- |")
  for (const r of scorecard.runs) {
    lines.push(`| ${r.run_id} | ${r.seed} | ${r.variant_id} | ${r.agent.terminated_by} | ${r.agent.status} | ${r.outcome.verifier.task_completed} | ${isSuccess(r) ? "✅" : "❌"} |`)
  }
  lines.push("")
  lines.push("## success_by_axis")
  lines.push("")
  lines.push("| axis | success_rate | n_runs (intensity>0) |")
  lines.push("| --- | --- | --- |")
  for (const [axis, rate] of Object.entries(scorecard.success_by_axis)) {
    const n = scorecard.runs.filter((r) => r.intensity_by_axis[axis as AxisKey] > 0).length
    lines.push(`| ${axis} | ${Number.isNaN(rate) ? "n/a" : rate.toFixed(2)} | ${n} |`)
  }
  lines.push("")
  lines.push("## generalization_curve (success rate vs intensity)")
  lines.push("")
  lines.push("| axis | intensity | success_rate | n_runs |")
  lines.push("| --- | --- | --- | --- |")
  const byAxis = new Map<string, Array<typeof scorecard.generalization_curve[number]>>()
  for (const p of scorecard.generalization_curve) {
    const arr = byAxis.get(p.axis) ?? []
    arr.push(p)
    byAxis.set(p.axis, arr)
  }
  for (const [axis, pts] of byAxis) {
    for (const p of pts) lines.push(`| ${axis} | ${p.intensity} | ${Number.isNaN(p.success_rate) ? "n/a" : p.success_rate.toFixed(2)} | ${p.n_runs} |`)
  }
  lines.push("")
  lines.push("## where it breaks")
  lines.push("")
  if (scorecard.where_it_breaks.length === 0) {
    lines.push("_No variant failed — the agent generalized across the entire (small) run set._")
  } else {
    lines.push("| axis | intensity | variant_id | failure_mode |")
    lines.push("| --- | --- | --- | --- |")
    for (const b of scorecard.where_it_breaks) {
      lines.push(`| ${b.axis} | ${b.intensity} | ${b.variant_id} | ${b.failure_mode} |`)
    }
  }
  lines.push("")
  lines.push("> Honesty note: perturbed variants perturb MULTIPLE axes at once, so a failure")
  lines.push("> is attributed to every axis the variant touched (intensity>0). n=1 per point.")
  lines.push("> Curve + break analysis are derived from run traces + verifier checks, not vibes.")
  writeFileSync(path, lines.join("\n"))
}

// ---------------------------------------------------------------------------
// entrypoint
// ---------------------------------------------------------------------------

const isMain = process.argv[1] != null && resolve(process.argv[1]) === fileURLToPath(import.meta.url)
if (isMain) {
  main()
    .then(() => process.exit(0))
    .catch((e) => {
      console.error(`[scorecard] FATAL: ${errText(e)}`)
      process.exit(1)
    })
}
