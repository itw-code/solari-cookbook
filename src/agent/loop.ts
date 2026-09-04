/**
 * loop.ts — the vision-first agent loop (DESIGN.md §3).
 *
 * The loop: current screenshot → model → action → execute → repeat, with a hard
 * step cap, terminal conditions (`done`/`abort`), and a `stuck` heuristic
 * (≥3 consecutive identical clicks producing no new screenshot). Fixed viewport
 * (default 1280×800), animations disabled by the caller.
 *
 * The loop is dependency-injected: it takes a `PageHandle` (the screenshot +
 * mouse + keyboard + goto subset of the browser page) and a `ModelCaller`. The
 * LIVE runner wires a real Playwright/Solari page + the LLM_* model; tests wire
 * a MockPage + a scripted stub model. This keeps the loop testable with NO
 * network and NO model key.
 *
 * On `done` the loop STOPS and records the trace — the verifier (Step 05, NOT
 * built here) later decides true/false. `done` never means success.
 */
import { createHash } from "node:crypto"
import { executeAction, type Action, type BrowserPage } from "./action.ts"
import type { ModelCaller } from "./model.ts"
import { captureScreenshot, type ScreenshotPage, type Viewport, DEFAULT_VIEWPORT } from "./screenshot.ts"
import { writeActionTrace, type ActionTrace } from "./trace.ts"

/** The subset of the browser page the loop needs (screenshot + mouse/keyboard/goto + title). */
export interface PageHandle extends BrowserPage, ScreenshotPage {
  title(): Promise<string>
}

export interface LoopOptions {
  page: PageHandle
  model: ModelCaller
  /** Solari preview base URL (may carry the ?pt_token= query string). */
  baseUrl: string
  /** Seed-derived natural-language task instruction. */
  task: string
  /** Output dir (artifacts/runs/<run_id>) — the trace + per-step screenshots land here. */
  runDir: string
  runId: string
  seed?: number
  variantId?: string
  maxSteps?: number
  viewport?: Viewport
  /** Label for the LLM (reported in the trace; never a secret). */
  modelLabel?: string
}

export interface StepRecord {
  step: number
  action: Action
  ok: boolean
  error?: string
  rationale?: string
  /** Path to the pre-action screenshot (relative to runDir) that drove this decision. */
  screenshot: string
}

export type LoopStatus = "done" | "aborted" | "stuck" | "step_cap"

export interface LoopResult {
  runId: string
  task: string
  status: LoopStatus
  terminatedBy: LoopStatus
  stepsTaken: number
  maxSteps: number
  actions: StepRecord[]
  /** The section of the trace that carries the model/history frame. */
  finalTitle: string | null
  finalScreenshot: string | null
  error?: string
}

/** Env override for the step cap (default 30 per DESIGN.md §3). */
export function getMaxStepsFromEnv(fallback = 30): number {
  const raw = process.env.COLDSTART_MAX_STEPS
  if (!raw) return fallback
  const n = Number.parseInt(raw, 10)
  return Number.isFinite(n) && n > 0 ? n : fallback
}

function sha1(buf: Buffer): string {
  return createHash("sha1").update(buf).digest("hex")
}

async function saveScreenshot(runDir: string, name: string, bytes: Buffer): Promise<string> {
  const { writeFile, mkdir } = await import("node:fs/promises")
  await mkdir(runDir, { recursive: true })
  await writeFile(`${runDir}/${name}`, bytes)
  return name
}

/**
 * Run the loop to a terminal condition. Returns the result AND writes the action
 * trace + per-step screenshots to `runDir`. Never throws on a terminal outcome;
 * throws only on a hard infrastructure failure (page/model unreachable).
 */
export async function runAgentLoop(opts: LoopOptions): Promise<LoopResult> {
  const maxSteps = opts.maxSteps ?? getMaxStepsFromEnv(30)
  const viewport = opts.viewport ?? DEFAULT_VIEWPORT
  const base = opts.baseUrl
  const { page, model, task, runId, runDir } = opts

  const actions: StepRecord[] = []
  let prevAction: Action | null = null
  let lastClick: { x: number; y: number } | null = null
  let stuckCount = 0
  let prevShotChanged = false // whether the PREVIOUS executed action changed the page
  let currentShot = await captureScreenshot(page, viewport)
  let status: LoopStatus = "step_cap"
  let finalTitle: string | null = null
  let finalScreenshot: string | null = null

  try {
    for (let step = 1; step <= maxSteps; step++) {
      const fp = sha1(currentShot)

      // --- stuck heuristic (checked on the shot from the previous action) ---
      if (prevAction) {
        const repeatedClick =
          prevAction.kind === "click" && lastClick !== null && prevAction.x === lastClick.x && prevAction.y === lastClick.y
        if (repeatedClick && !prevShotChanged) stuckCount++
        else stuckCount = 0
        if (stuckCount >= 3) {
          status = "stuck"
          break
        }
      }
      lastClick = prevAction?.kind === "click" ? { x: prevAction.x, y: prevAction.y } : null

      // --- evidence: persist the pre-action screenshot that drives this decision ---
      const shotName = `step-${String(step).padStart(2, "0")}.png`
      await saveScreenshot(runDir, shotName, currentShot)

      // --- decide ---
      const decision = await model.decide({
        task,
        imageBase64: currentShot.toString("base64"),
        history: actions.map((a) => a.action),
        step,
        maxSteps,
      })
      const action = decision.action

      // --- execute ---
      let ok = true
      let error: string | undefined
      try {
        await executeAction(page, action, base)
      } catch (e) {
        ok = false
        error = e instanceof Error ? e.message : String(e)
      }

      actions.push({
        step,
        action,
        ok,
        error,
        rationale: decision.rationale,
        screenshot: shotName,
      })

      // --- measure whether the action changed the page (for stuck/done) ---
      const nextShot = await captureScreenshot(page, viewport)
      prevShotChanged = sha1(nextShot) !== fp
      currentShot = nextShot

      // --- terminal conditions ---
      if (action.kind === "done") {
        status = "done"
        break
      }
      if (action.kind === "abort") {
        status = "aborted"
        break
      }
      prevAction = action
    }

    // Final title + final screenshot evidence.
    try {
      finalTitle = await page.title()
    } catch {
      finalTitle = null
    }
    const finalName = `final.png`
    await saveScreenshot(runDir, finalName, currentShot)
    finalScreenshot = finalName
  } catch (e) {
    status = "aborted"
    // Still record whatever we have so the trace is honest evidence.
    const err = e instanceof Error ? e.message : String(e)
    emitTrace(opts, maxSteps, viewport, actions, status, finalTitle, finalScreenshot, err).catch(() => undefined)
    throw new Error(`agent loop failed: ${err}`)
  }

  const trace = await emitTrace(opts, maxSteps, viewport, actions, status, finalTitle, finalScreenshot, undefined)
  void trace
  return {
    runId,
    task,
    status,
    terminatedBy: status,
    stepsTaken: actions.length,
    maxSteps,
    actions,
    finalTitle,
    finalScreenshot,
  }
}

async function emitTrace(
  opts: LoopOptions,
  maxSteps: number,
  viewport: Viewport,
  actions: StepRecord[],
  status: LoopStatus,
  finalTitle: string | null,
  finalScreenshot: string | null,
  error: string | undefined,
): Promise<ActionTrace> {
  const trace: ActionTrace = {
    run_id: opts.runId,
    seed: opts.seed ?? null,
    variant_id: opts.variantId ?? null,
    task: opts.task,
    status,
    terminated_by: status,
    steps_taken: actions.length,
    max_steps: maxSteps,
    model: opts.modelLabel ?? null,
    base_url: redactUrl(opts.baseUrl),
    viewport: `${viewport.width}x${viewport.height}`,
    final_title: finalTitle,
    final_screenshot: finalScreenshot ?? null,
    actions,
    error: error ?? null,
    generated_at: new Date().toISOString(),
  }
  await writeActionTrace(opts.runDir, trace)
  return trace
}

/** Redact a Solari preview URL (mask any long query-param value, e.g. the gateway token). */
function redactUrl(url: string): string {
  try {
    const u = new URL(url)
    const mask = (v: string): string => (/[A-Za-z0-9_-]{8,}/.test(v) ? "*".repeat(Math.min(12, v.length)) : v)
    u.search = u.search
      ? "?" +
        [...u.searchParams.entries()].map(([k, v]) => `${k}=${mask(v)}`).join("&")
      : ""
    return `${u.protocol}//${u.host}${u.pathname}${u.search}`
  } catch {
    return "<unparseable-url>"
  }
}
