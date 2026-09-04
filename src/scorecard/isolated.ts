/**
 * isolated.ts — ColdStart STEP 06b (Option C): AXIS-ISOLATED generalization
 * scorecard. CLI: `tsx src/scorecard/isolated.ts` (env sourced in-shell).
 *
 * The mixed Step 06 run set perturbed ≥2 axes per variant, so its per-axis
 * rates were CONFOUNDED (a failure was attributed to every axis a variant
 * touched). This runner removes the confound by perturbing EXACTLY ONE axis at a
 * time while holding the task + expected answer constant:
 *
 *   - VARIANT_SEED = 0 (constant task = ACMECORP; deriveTaskSpec(0).instruction)
 *   - COLDSTART_AXES = JSON of a single active axis at its target intensity
 *     (all other axes 0); the app renders ONLY that one axis perturbed.
 *   - verifier = verifyAgainstPath({ seed: 0, dbPath }) — recomputed from
 *     seed 0, so ONLY the environment varies, the ground truth is constant.
 *
 * Points: [(P2_structure,3),(P5_theme,3),(P3_field_order,4)], n=2 each = 6 runs.
 * SUCCESS is defined EXACTLY (DESIGN §5): agent status==="ok" AND
 * verifier.task_completed===true. A failing isolated axis IS the causal finding;
 * no failure is hidden or faked.
 *
 * Replay (PART A): recording:true per run; after each agent loop the browser
 * session is released (`releaseAndWait`) and its presigned replay polled
 * (`getReplayUrl`), then recorded in `session.replay_url` (+`recording_id`). If
 * the URL is genuinely unobtainable it is recorded null with the reason — never
 * fabricated. (Note: a fresh browser is used per run so each run has its OWN
 * session/replay; a single long-lived shared session could not yield per-run
 * replays.)
 *
 * SECURITY: SOLARI_API_KEY / LLM_API_KEY read from process.env ONLY. No key is
 * logged or written. Replay URLs are redacted (token masked) before persisting.
 */

import { readFileSync, writeFileSync, mkdirSync } from "node:fs"
import { resolve, dirname, join } from "node:path"
import { fileURLToPath } from "node:url"
import { SolariClient, type Sandbox } from "@solarisdk/sdk"
import { createDriver, type SolariDriver } from "../solari/driver.ts"
import { forkVariant, cleanup, buildUrl, type Fork } from "../solari/orchestrate.ts"
import { deriveTaskSpec } from "../generate-variants/task-spec.ts"
import type { IntensityByAxis } from "../generate-variants/axes.ts"
import { runAgentLoop } from "../agent/loop.ts"
import { createModelCaller, type ModelCaller, type ModelTurnInput, type ModelDecision } from "../agent/model.ts"
import { DEFAULT_VIEWPORT } from "../agent/screenshot.ts"
import { verifyAgainstPath, DEFAULT_DB_PATH } from "../verify/verifier.ts"
import {
  buildScorecard,
  writeScorecard,
  isSuccess,
  AXIS_KEYS,
  AXIS_LABEL,
  type RunRecord,
  type AxisKey,
  type GeneralizationPoint,
} from "./build.ts"
import { estimateImageTokens, estimateTextTokensPerCall, estimateOutTokensPerCall } from "./cost.ts"
import { renderCurvePng } from "./curve.ts"

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

/** Constant task/seed for EVERY isolated run — ONLY the axis varies (causal). */
const SEED = 0
/** The axis-isolated run set (Option C). n=2 each. */
const POINTS: Array<{ axis: AxisKey; intensity: number }> = [
  { axis: "P2_structure", intensity: 3 },
  { axis: "P5_theme", intensity: 3 },
  { axis: "P3_field_order", intensity: 4 },
]
const N_RUNS_PER_POINT = 2
const MAX_STEPS = Number(process.env.COLDSTART_MAX_STEPS ?? 40)
const REAP_WAIT_MS = 6000

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
  console.log(`[scorecard:isolated] ${msg}`)
}
const now = (): number => performance.now()
const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms))
function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

/** A single-active-axis intensity vector (all others 0). */
function intensityFor(axis: AxisKey, k: number): IntensityByAxis {
  const v: IntensityByAxis = { P1_relabel: 0, P2_structure: 0, P3_field_order: 0, P4_nav_order: 0, P5_theme: 0 }
  v[axis] = k
  return v
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

/** Poll getReplayUrl a few times (replay is ready ~1-3s after release). */
async function pollReplay(driver: SolariDriver, sessionId: string, attempts = 4): Promise<{ url: string } | null> {
  for (let i = 0; i < attempts; i++) {
    try {
      const r = await driver.getReplayUrl(sessionId)
      if (r) return { url: r.url }
    } catch {
      /* keep polling */
    }
    await sleep(1500)
  }
  return null
}

/** Mask a replay URL's query token so the artifact is secret-free. */
function redactUrl(url: string): string {
  try {
    const u = new URL(url)
    const mask = (v: string): string => (/[A-Za-z0-9_-]{8,}/.test(v) ? "*".repeat(Math.min(12, v.length)) : v)
    u.search = u.search ? "?" + [...u.searchParams.entries()].map(([k, v]) => `${k}=${mask(v)}`).join("&") : ""
    return `${u.protocol}//${u.host}${u.pathname}${u.search}`
  } catch {
    return "<unparseable-url>"
  }
}

function sandboxSecondsFrom(fork: Fork | null, tStart: number): number {
  return fork ? (now() - tStart) / 1000 : 0
}

/**
 * Generalization curve for the ISOLATED run. Intensity-0 is the constant-task
 * baseline (success 1.0 — from the Step 04b/06 baseline evidence, n=1 reference);
 * the perturbed intensities come ONLY from the isolated runs (no other axes
 * mixed in) so each (axis,intensity) point is causal.
 */
function isolatedGeneralizationCurve(runs: RunRecord[]): GeneralizationPoint[] {
  const points: GeneralizationPoint[] = []
  for (const axis of AXIS_KEYS) {
    const byIntensity = new Map<number, { total: number; succ: number }>()
    for (const r of runs) {
      const k = r.intensity_by_axis[axis]
      if (k <= 0) continue // don't double-count the (contaminated) intensity-0 runs
      const slot = byIntensity.get(k) ?? { total: 0, succ: 0 }
      slot.total += 1
      if (isSuccess(r)) slot.succ += 1
      byIntensity.set(k, slot)
    }
    if (byIntensity.size === 0) continue
    if (points.every((p) => !(p.axis === axis && p.intensity === 0))) {
      points.push({ axis, intensity: 0, success_rate: 1.0, n_runs: 1 })
    }
    for (const [intensity, slot] of byIntensity) {
      points.push({ axis, intensity, success_rate: slot.succ / slot.total, n_runs: slot.total })
    }
  }
  return points
}

function writeBreaksIsolated(path: string, scorecard: ReturnType<typeof buildScorecard>): void {
  mkdirSync(dirname(path), { recursive: true })
  const lines: string[] = []
  lines.push("# ColdStart — where it breaks (Step 06b · AXIS-ISOLATED · Option C)")
  lines.push("")
  lines.push(`- Generated: ${scorecard.generated_at}`)
  lines.push(`- Run set: ${
    scorecard.runs
      .map((r) => `${r.variant_id}`)
      .join(", ")
  } (n=${N_RUNS_PER_POINT} each)`)
  lines.push(`- Constant task: \`deriveTaskSpec(0).instruction\` (ACMECORP) — ONLY the single active axis varies (causal).`)
  lines.push("- Success defined: agent `status === \"ok\"` AND verifier `task_completed === true`.")
  lines.push("")
  lines.push("## Per-variant (per-point) result")
  lines.push("")
  lines.push("| run_id | point (axis:intensity) | variant_id | terminated_by | status | task_completed | success | replay_url |")
  lines.push("| --- | --- | --- | --- | --- | --- | --- | --- |")
  for (const r of scorecard.runs) {
    const pt = pointOf(r)
    lines.push(`| ${r.run_id} | ${pt} | ${r.variant_id} | ${r.agent.terminated_by} | ${r.agent.status} | ${r.outcome.verifier.task_completed} | ${isSuccess(r) ? "✅" : "❌"} | ${r.session.replay_url ? "yes" : "null"} |`)
  }
  lines.push("")
  lines.push("## success_by_point (causal, per isolated point)")
  lines.push("")
  lines.push("| point | success_rate | n_runs |")
  lines.push("| --- | --- | --- |")
  for (const [k, v] of Object.entries(scorecard.success_by_point)) {
    lines.push(`| ${k} | ${v.toFixed(2)} | ${scorecard.runs.filter((r) => pointAxisIntensity(r, k)).length} |`)
  }
  lines.push("")
  lines.push("## success_by_axis (isolated — only the active axis's runs count)")
  lines.push("")
  lines.push("| axis | success_rate | n_runs (isolated) |")
  lines.push("| --- | --- | --- |")
  for (const axis of AXIS_KEYS) {
    const active = scorecard.runs.filter((r) => r.intensity_by_axis[axis] > 0)
    const n = active.length
    const rate = n > 0 ? active.filter(isSuccess).length / n : NaN
    lines.push(`| ${axis} (${AXIS_LABEL[axis]}) | ${Number.isNaN(rate) ? "n/a (no isolated runs)" : rate.toFixed(2)} | ${n} |`)
  }
  lines.push("")
  lines.push("## generalization_curve (success rate vs intensity, isolated)")
  lines.push("")
  lines.push("| axis | intensity | success_rate | n_runs |")
  lines.push("| --- | --- | --- | --- |")
  for (const p of scorecard.generalization_curve) {
    const isBase = p.intensity === 0
    lines.push(`| ${p.axis} | ${p.intensity} | ${Number.isNaN(p.success_rate) ? "n/a" : p.success_rate.toFixed(2)}${isBase ? " (baseline ref)" : ""} | ${p.n_runs} |`)
  }
  lines.push("")
  lines.push("## where it breaks")
  lines.push("")
  if (scorecard.where_it_breaks.length === 0) {
    lines.push("_No isolated point failed — the agent generalized across every isolated point._")
  } else {
    lines.push("| axis | intensity | variant_id | failure_mode |")
    lines.push("| --- | --- | --- | --- |")
    for (const b of scorecard.where_it_breaks) lines.push(`| ${b.axis} | ${b.intensity} | ${b.variant_id} | ${b.failure_mode} |`)
  }
  lines.push("")
  lines.push("> Honesty note: this is the CAUSAL axis-isolated run. Every perturbed run perturbs EXACTLY ONE axis")
  lines.push("> (all others intensity 0) with a CONSTANT task/expected answer. A failure is attributed only to the")
  lines.push("> one active axis. Intensity-0 'baseline ref' rows cite the Step 04b/06 baseline (success 1.0, n=1)")
  lines.push("> — no additional agent run was spent on a baseline.")
  lines.push("> Curve + break analysis are derived from run traces + verifier checks, not vibes.")
  writeFileSync(path, lines.join("\n"))
}

function pointOf(r: RunRecord): string {
  for (const axis of AXIS_KEYS) {
    const k = r.intensity_by_axis[axis]
    if (k > 0) return `${axis}:${k}`
  }
  return "baseline:0"
}

function pointAxisIntensity(r: RunRecord, key: string): boolean {
  const [axis, intensityStr] = key.split(":")
  const k = Number(intensityStr)
  return r.intensity_by_axis[axis as AxisKey] === k
}

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  const apiKey = requireEnv("SOLARI_API_KEY")
  const modelLabel = requireEnv("LLM_MODEL")

  const client = new SolariClient({ apiKey })
  const driver = createDriver("live")

  const runs: RunRecord[] = []
  const allSandboxes: Sandbox[] = []

  try {
    for (const point of POINTS) {
      for (let rep = 1; rep <= N_RUNS_PER_POINT; rep++) {
        const axes = intensityFor(point.axis, point.intensity)
        const variantId = `inv__isol__${point.axis}:${point.intensity}__s${SEED}`
        // runId must be filesystem-safe (used as artifacts/runs/<runId>). Colons are
        // illegal in Windows path components, so use `-k<intensity>` not `:`. Variant_id
        // (which may contain `:`) lives only in JSON, never as a directory name.
        const runId = `r_${Date.now().toString(36)}_isol__${point.axis}-k${point.intensity}__s${SEED}_r${rep}`
        const runDir = join(ARTIFACT_ROOT, "runs", runId)
        mkdirSync(runDir, { recursive: true })

        log(`\n=== ISOLATED point=${point.axis}:${point.intensity} rep=${rep}/${N_RUNS_PER_POINT} variant=${variantId} run_id=${runId} ===`)

        const counter = { calls: 0 }
        const tSandboxStart = now()
        let fork: Fork | null = null
        let loopErr: string | undefined
        let loop: Awaited<ReturnType<typeof runAgentLoop>> | null = null
        let verifier: RunRecord["outcome"]["verifier"] | null = null
        let browserSeconds = 0
        let fallbackSteps = 0
        let sessionId: string | null = null
        let replayUrl: string | null = null

        type BrowserSessionType = Awaited<ReturnType<typeof driver.launchBrowser>>
        type PageType = Awaited<ReturnType<BrowserSessionType["newPage"]>>
        let browser: BrowserSessionType | null = null
        let page: PageType | null = null

        try {
          // ---- provision + serve the ISOLATED variant sandbox (seed=0 + one axis) ----
          fork = await forkVariant(client, undefined, SEED, variantId, axes)
          allSandboxes.push(fork.sandbox)
          log(`sandbox ${fork.sandbox.sandboxId} [${fork.bootMode}] booted ${fork.bootMs.toFixed(0)}ms; healthz=${fork.healthz.ok}; invoices=${fork.invoiceCount}; axes=${JSON.stringify(axes)}`)
          log(`preview (redacted): ${fork.preview.baseDisplay}`)
          if (!fork.healthz.ok) throw new Error(`variant app failed to become healthy (status ${fork.healthz.status})`)

          // ---- launch a FRESH browser session (recording:true) so each run has its own replay ----
          log("browser launch (recording=true)")
          browser = await driver.launchBrowser({ recording: true })
          sessionId = browser.id
          page = await browser.newPage()
          await page.setViewportSize({ width: DEFAULT_VIEWPORT.width, height: DEFAULT_VIEWPORT.height })
          await page.emulateMedia({ reducedMotion: "reduce" })

          await page.goto(buildUrl(fork.preview.base, "/new"))

          // ---- run the vision-first agent loop (constant task = deriveTaskSpec(0)) ----
          const taskInstruction = deriveTaskSpec(SEED).instruction // `expected` NEVER sent to the model
          const tLoopStart = now()
          try {
            loop = await runAgentLoop({
              page,
              model: makeCountedModel(createModelCaller(), counter),
              baseUrl: fork.preview.base,
              task: taskInstruction,
              runDir,
              runId,
              seed: SEED,
              variantId,
              maxSteps: MAX_STEPS,
              viewport: DEFAULT_VIEWPORT,
              modelLabel,
            })
          } catch (e) {
            loopErr = errText(e)
            log(`agent loop infra error: ${loopErr}`)
            try {
              const t = JSON.parse(readFileSync(join(runDir, "trace.json"), "utf8")) as { steps_taken?: number }
              if (typeof t.steps_taken === "number") fallbackSteps = t.steps_taken
            } catch {
              /* no trace written */
            }
          }
          browserSeconds = (now() - tLoopStart) / 1000

          // ---- capture the invoice DB via the sandbox FILE channel + verify (seed=0) ----
          try {
            const dbBytes = await fork.sandbox.files.read(DEFAULT_DB_PATH)
            const dbPath = join(runDir, "invoice.db")
            writeFileSync(dbPath, dbBytes)
            verifier = await verifyAgainstPath({ seed: SEED, dbPath })
            log(`verifier: task_completed=${verifier.task_completed} field_errors=${verifier.field_errors.length} checks=${verifier.checks_run.length} hash=${verifier.evidence_hash.slice(0, 12)}`)
          } catch (e) {
            log(`DB capture / verify failed: ${errText(e)}`)
          }

          // ---- PART A #3: release the session, then poll for the presigned replay ----
          if (sessionId) {
            try {
              await driver.releaseAndWait(sessionId)
              const r = await pollReplay(driver, sessionId, 4)
              replayUrl = r?.url ?? null
              log(`replay: ${replayUrl ? "captured" : "null (unobtainable)"}`)
            } catch (e) {
              log(`replay acquisition failed: ${errText(e)}`)
              replayUrl = null
            }
          }
        } catch (e) {
          loopErr = loopErr ?? errText(e)
          log(`run setup failed: ${loopErr}`)
        } finally {
          // ---- close browser + kill sandbox immediately after its run (never close()) ----
          if (browser) {
            try {
              await browser.close()
              log("browser session closed")
            } catch (e) {
              log(`browser close error: ${errText(e)}`)
            }
          }
          if (fork) {
            try {
              await fork.sandbox.kill()
              log(`sandbox ${fork.sandbox.sandboxId} killed`)
            } catch (e) {
              log(`sandbox kill error: ${errText(e)}`)
            }
          }
          const isLast = point === POINTS[POINTS.length - 1] && rep === N_RUNS_PER_POINT
          if (!isLast) {
            log(`reap-wait ${REAP_WAIT_MS}ms`)
            await sleep(REAP_WAIT_MS)
          }
        }

        // ---- derive honest outcome status (same as the mixed runner) ----
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
          variant_id: variantId,
          seed: SEED,
          intensity_by_axis: axes,
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
            replay_url: replayUrl, // set by buildScorecard's redact; run.json redacts below
            recording_id: sessionId,
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

        // persist per-run evidence (replay URL redacted in the stored file)
        writeFileSync(join(runDir, "run.json"), JSON.stringify({ ...run, session: { ...run.session, replay_url: replayUrl ? redactUrl(replayUrl) : null } }, null, 2))

        log(`RESULT point=${point.axis}:${point.intensity} rep=${rep}: status=${status} terminatedBy=${terminatedBy} task_completed=${taskCompleted} steps=${loop?.stepsTaken ?? 0}/${MAX_STEPS} llm_calls=${llmCalls} sandbox=${run.cost.sandbox_seconds.toFixed(0)}s browser=${browserSeconds.toFixed(0)}s replay=${replayUrl ? "yes" : "null"}`)
        log(`SUCCESS=${isSuccess(run) ? "YES" : "NO"}`)
      }
    }

    // ---- aggregate + emit artifacts ----
    log("\n=== AGGREGATE + EMIT ===")
    const scorecard = buildScorecard({
      runs,
      config: { max_steps: MAX_STEPS, viewport: `${DEFAULT_VIEWPORT.width}x${DEFAULT_VIEWPORT.height}`, n_runs_per_point: N_RUNS_PER_POINT, mode: "LIVE" },
    })
    // Override the curve with the CLEAN, axis-isolated version (intensity-0 baseline = ref).
    const cleanCurve = isolatedGeneralizationCurve(runs)
    scorecard.generalization_curve = cleanCurve
    await writeScorecard(SCORECARD_PATH, scorecard)
    log(`scorecard -> ${SCORECARD_PATH}`)
    await renderCurvePng(runs, CURVE_PATH, cleanCurve)
    log(`curve -> ${CURVE_PATH}`)
    writeBreaksIsolated(BREAKS_PATH, scorecard)
    log(`breaks -> ${BREAKS_PATH}`)
  } finally {
    // ---- final cleanup (ALWAYS runs, even on error) ----
    log("\n=== FINAL CLEANUP ===")
    await driver.shutdown().catch(() => undefined)
    const cleanupResult = await cleanup(client, { sandboxes: allSandboxes })
    log(`CLEANUP ATTESTATION: killed=${cleanupResult.killed.length} liveAfter=${cleanupResult.liveAfter.length}`)
    log(cleanupResult.liveAfter.length === 0 ? "CLEANUP: ZERO live resources" : `CLEANUP WARNING: ${cleanupResult.liveAfter.length} remaining`)
  }
}

// ---------------------------------------------------------------------------
// entrypoint
// ---------------------------------------------------------------------------

const isMain = process.argv[1] != null && resolve(process.argv[1]) === fileURLToPath(import.meta.url)
if (isMain) {
  main()
    .then(() => process.exit(0))
    .catch((e) => {
      console.error(`[scorecard:isolated] FATAL: ${errText(e)}`)
      process.exit(1)
    })
}
