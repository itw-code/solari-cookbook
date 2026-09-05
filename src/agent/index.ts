/**
 * index.ts — ColdStart STEP 04 LIVE baseline run (seed=0).
 *
 * Reuses orchestrate.ts (Step 03): createBaseSandbox (upload compiled app +
 * ensure Node 22) → launchServer → getPreviewUrl (keep the ?pt_token=) →
 * waitForHealthz. Launches ONE Solari browser via LiveSolari.launchBrowser,
 * runs the vision-first loop against `new URL('/new', previewUrl)`, records the
 * action trace + final page title, then kills the sandbox, closes the browser +
 * solari client, and asserts ZERO live resources.
 *
 * SECURITY: SOLARI_API_KEY / LLM_API_KEY are read from process.env ONLY (sourced
 * from `.env` in-shell). They are never logged, never written to a file, and
 * never sent to the variant app or the model beyond the OpenAI auth header.
 * Preview URLs are redacted in every printed output and in the trace.
 */
import { SolariClient } from "@solarisdk/sdk"
import { createDriver } from "../solari/driver.ts"
import {
  createBaseSandbox,
  launchServer,
  getPreviewUrl,
  waitForHealthz,
  cleanup,
  buildUrl,
  countInvoices,
} from "../solari/orchestrate.ts"
import { deriveTaskSpec } from "../generate-variants/task-spec.ts"
import { verifyAgainstSandbox } from "../verify/verifier.ts"
import { runAgentLoop, getMaxStepsFromEnv } from "./loop.ts"
import { createModelCaller } from "./model.ts"
import { DEFAULT_VIEWPORT } from "./screenshot.ts"

const SEED = 0
const PORT = Number(process.env.COLDSTART_APP_PORT ?? 3000)
const VARIANT_ID = `inv__s${SEED}__P1:0__P2:0__P3:0__P4:0__P5:0`
const MAX_STEPS = getMaxStepsFromEnv(26)

function requireEnv(name: string): string {
  const v = process.env[name]
  if (!v || v.length === 0) throw new Error(`${name} is not set — source .env in-shell first`)
  return v
}

function log(msg: string): void {
  console.log(`[step-04] ${msg}`)
}

async function main(): Promise<void> {
  const apiKey = requireEnv("SOLARI_API_KEY")
  const isIpc = process.env.AGENT_MODE === "ipc" || process.env.AGENT_MODE === "antigravity"
  const modelLabel = isIpc ? (process.env.LLM_MODEL || "antigravity-vision") : requireEnv("LLM_MODEL")

  const client = new SolariClient({ apiKey })
  const driver = createDriver("live") // LiveSolari (browser)
  const runId = `r_${Date.now().toString(36)}_s${SEED}`
  const runDir = `artifacts/runs/${runId}`

  let browser: Awaited<ReturnType<typeof driver.launchBrowser>> | null = null
  let baseSandbox: Awaited<ReturnType<typeof createBaseSandbox>> | null = null

  const taskSpec = deriveTaskSpec(SEED) // instruction only; the `expected` object is NEVER sent to the model

  try {
    // 1. Browser session (ONE browser).
    log(`browser launch (viewport ${DEFAULT_VIEWPORT.width}x${DEFAULT_VIEWPORT.height})`)
    browser = await driver.launchBrowser()
    const page = await browser.newPage() // Playwright Page (structurally satisfies PageHandle)
    await page.setViewportSize({ width: DEFAULT_VIEWPORT.width, height: DEFAULT_VIEWPORT.height })
    await page.emulateMedia({ reducedMotion: "reduce" })

    // 2. Sandbox + app serve (upload compiled app, launch server, poll /healthz).
    log("create base sandbox (seed=0) + upload compiled app + ensure Node 22")
    baseSandbox = await createBaseSandbox(client)
    await launchServer(baseSandbox.sandbox)
    const preview = await getPreviewUrl(baseSandbox.sandbox, PORT)
    const healthz = await waitForHealthz(preview.healthz)
    log(`preview (redacted): ${preview.baseDisplay}`)
    log(`/healthz -> status ${healthz.status} ok=${healthz.ok}`)
    if (!healthz.ok) throw new Error(`variant app failed to become healthy (status ${healthz.status})`)

    // 3. Drive to the /new entry page.
    const entryUrl = buildUrl(preview.base, "/new")
    log("navigate to /new entry (token preserved)")
    await page.goto(entryUrl)

    // 4. Run the vision-first loop (baseline, seed=0).
    log(`run agent loop: task seed=${SEED}, max_steps=${MAX_STEPS}`)
    const result = await runAgentLoop({
      page,
      model: createModelCaller(),
      baseUrl: preview.base,
      task: taskSpec.instruction,
      runDir,
      runId,
      seed: SEED,
      variantId: VARIANT_ID,
      maxSteps: MAX_STEPS,
      modelLabel,
      viewport: DEFAULT_VIEWPORT,
    })

    // 5. Final page title + invoice row count (sanity, NOT the Step 05 verifier).
    let finalTitle: string | null = null
    try {
      finalTitle = await page.title()
    } catch {
      finalTitle = null
    }
    const invoiceCount = await countInvoices(baseSandbox.sandbox)

    // Fail-closed verification
    let verifierCompleted = false
    let verifierChecks = 0
    let verifierErrors = 0
    let evidenceHash = ""
    try {
      const vRes = await verifyAgainstSandbox({ seed: SEED, sandbox: baseSandbox.sandbox })
      verifierCompleted = vRes.task_completed
      verifierChecks = vRes.checks_run.length
      verifierErrors = vRes.field_errors.length
      evidenceHash = vRes.evidence_hash
    } catch (ve) {
      log(`verifier error: ${ve instanceof Error ? ve.message : String(ve)}`)
    }

    log("=" .repeat(64))
    log("STEP 04 LIVE BASELINE RESULT (seed=0)")
    log(`  status           : ${result.status}`)
    log(`  steps taken      : ${result.stepsTaken}/${result.maxSteps}`)
    log(`  final page title : ${finalTitle ?? "(unavailable)"}`)
    log(`  invoice rows     : ${invoiceCount}`)
    log(`  verifier         : ${verifierCompleted ? "PASS ✅" : "FAIL ❌"} (${verifierChecks} checks, ${verifierErrors} errors, hash: ${evidenceHash})`)
    log(`  terminated by    : ${result.terminatedBy}`)
    if (result.actions.length > 0) {
      const last = result.actions[result.actions.length - 1]!
      log(`  last action      : ${JSON.stringify(last.action)}${last.error ? ` (error: ${last.error})` : ""}`)
    }
    log(`  trace            : ${runDir}/trace.json`)
    log("=" .repeat(64))
  } finally {
    // 6. Cleanup — every resource killed / closed; assert zero live.
    log("cleanup: kill sandbox, close browser + solari client")
    if (baseSandbox) {
      try {
        await baseSandbox.sandbox.kill()
        log("sandbox killed")
      } catch (e) {
        log(`sandbox kill error: ${e instanceof Error ? e.message : String(e)}`)
      }
    }
    if (browser) {
      try {
        await browser.close()
        log("browser session closed")
      } catch (e) {
        log(`browser close error: ${e instanceof Error ? e.message : String(e)}`)
      }
    }
    try {
      await driver.shutdown() // closes LiveSolari's loopback proxy (prevents hang)
      log("solari client closed")
    } catch (e) {
      log(`solari shutdown error: ${e instanceof Error ? e.message : String(e)}`)
    }
    const result = await cleanup(client, { sandboxes: baseSandbox ? [baseSandbox.sandbox] : [] })
    log(`CLEANUP ATTESTATION: live ColdStart resources after cleanup = ${result.liveAfter.length}`)
    log(result.liveAfter.length === 0 ? "CLEANUP: ZERO live resources" : `CLEANUP WARNING: ${result.liveAfter.length} remaining`)
  }
}

main()
  .then(() => process.exit(0))
  .catch((e) => {
    console.error(`[step-04] FATAL: ${e instanceof Error ? e.message : String(e)}`)
    process.exit(1)
  })
