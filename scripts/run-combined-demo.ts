/**
 * run-combined-demo.ts — Unified demo target evaluation runner.
 *
 * Runs BOTH ColdStart (the CUA generalization loop) and Slop-Catcher (Design QA)
 * in one combined demo run against the designed demo target site:
 *
 * 1. Boots `src/demo-site/server.ts` on an ephemeral local port.
 * 2. Runs `scanExternalPage` against:
 *      - http://localhost:<port>/        (Clean variant -> PASS, 0 variance)
 *      - http://localhost:<port>/?slop=1 (Slop variant  -> WARN/BLOCK, high variance & low contrast)
 *    In local mode, the scanner fetches `/design-metrics.json` for deterministic CSS checks.
 * 3. Runs ColdStart agent loop against the clean landing page in MOCK mode by default
 *    (or LIVE if SOLARI_API_KEY and model keys are present).
 * 4. Runs fail-closed `verifyDemoSignup` directly against the SQLite database.
 * 5. Persists `artifacts/combined-demo-report.json`.
 * 6. Prints console table: Target | Slop Score | Design Status | Task Completed | Verifier.
 */

import { mkdirSync, writeFileSync } from "node:fs"
import { join, resolve } from "node:path"
import { startDemoServer, type DemoServerInstance } from "../src/demo-site/server.js"
import { verifyDemoSignup, type DemoVerifierResult } from "../src/demo-site/verifier.js"
import { scanExternalPage } from "../src/design-qa/scan-url.js"
import type { DesignQAResult } from "../src/design-qa/orchestrator.js"
import { runAgentLoop, type PageHandle, type LoopResult } from "../src/agent/loop.js"
import type { Action } from "../src/agent/action.js"
import type { ModelCaller, ModelDecision, ModelTurnInput } from "../src/agent/model.js"

// ---------------------------------------------------------------------------
// Mock PageHandle for offline deterministic execution of early access form
// ---------------------------------------------------------------------------
class DemoMockPage implements PageHandle {
  private activeField: "name" | "email" | null = null
  private formData = { name: "", email: "" }
  private pageTitle = "Request Early Access"

  constructor(private readonly baseUrl: string) {}

  readonly mouse = {
    click: async (_x: number, y: number): Promise<void> => {
      if (y < 200) {
        this.activeField = "name"
      } else if (y < 260) {
        this.activeField = "email"
      } else {
        // Submit button clicked: POST signup to the demo server
        this.activeField = null
        try {
          const res = await fetch(`${this.baseUrl}/signup`, {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
            body: new URLSearchParams(this.formData).toString(),
          })
          if (res.ok) {
            this.pageTitle = "Access Requested"
          }
        } catch (e) {
          console.error("[DemoMockPage] Submit error:", e)
        }
      }
    },
  }

  readonly keyboard = {
    type: async (text: string): Promise<void> => {
      if (this.activeField === "name") {
        this.formData.name = (this.formData.name ? `${this.formData.name} ` : "") + text
      } else if (this.activeField === "email") {
        this.formData.email = text
      }
    },
    press: async (keys: string): Promise<void> => {
      if (keys === "Tab") {
        this.activeField = this.activeField === "name" ? "email" : null
      } else if (keys === "Enter") {
        await this.mouse.click(200, 300)
      }
    },
  }

  async goto(_url: string): Promise<void> {
    // Already on the page
  }

  async screenshot(): Promise<Buffer> {
    // Deterministic 1x1 transparent PNG fallback screenshot
    return Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
      "base64",
    )
  }

  async title(): Promise<string> {
    return this.pageTitle
  }

  async evaluate<A, R>(_fn: (arg: A) => R, _arg: A): Promise<R> {
    return null as unknown as R
  }
}

// ---------------------------------------------------------------------------
// Scripted model for offline ColdStart demo loop
// ---------------------------------------------------------------------------
class DemoScriptedModel implements ModelCaller {
  private step = 0
  private actions: Action[]

  constructor(name: string, email: string) {
    this.actions = [
      { kind: "click", x: 200, y: 150 }, // Focus name input
      { kind: "type", text: name },       // Fill name
      { kind: "click", x: 200, y: 220 }, // Focus email input
      { kind: "type", text: email },      // Fill email
      { kind: "click", x: 200, y: 300 }, // Click submit
      { kind: "done" },                   // Report complete
    ]
  }

  async decide(input: ModelTurnInput): Promise<ModelDecision> {
    const action = this.actions[this.step] ?? { kind: "done" }
    this.step++
    return {
      action,
      rationale: `Demo Step ${input.step}: ${action.kind}`,
    }
  }
}

import { fileURLToPath } from "node:url"

export async function runCombinedDemo(): Promise<any> {
  console.log("\n" + "=".repeat(78))
  console.log(" COLDSTART + SLOP-CATCHER COMBINED DEMO EVALUATION")
  console.log(" Offline demo: scripted action sequence against a mock page — verifies plumbing, not model capability.")
  console.log("=".repeat(78) + "\n")

  // 1. Boot Demo Site on ephemeral port
  console.log("[1/4] Booting Demo Target Site on ephemeral local port...")
  const demo: DemoServerInstance = await startDemoServer({ port: 0 })
  console.log(`      Demo site listening at ${demo.baseUrl}`)

  const cleanUrl = `${demo.baseUrl}/`
  const slopUrl = `${demo.baseUrl}/?slop=1`

  let cleanScanReport: DesignQAResult
  let slopScanReport: DesignQAResult
  let agentResult: LoopResult
  let verifierResult: DemoVerifierResult

  const runId = `demo_${Date.now().toString(36)}`
  const runDir = resolve(`artifacts/runs/${runId}`)

  try {
    // 2. Scan Clean Variant with Slop-Catcher
    console.log(`\n[2/4] Running Slop-Catcher Design QA scans...`)
    console.log(`      Scanning clean variant: ${cleanUrl}`)
    cleanScanReport = await scanExternalPage(cleanUrl, { delayMs: 0 })
    console.log(`      -> Clean Slop Score: ${cleanScanReport.slopScore} (${cleanScanReport.status})`)

    // Scan Slop Variant with Slop-Catcher
    console.log(`      Scanning intentional slop variant: ${slopUrl}`)
    slopScanReport = await scanExternalPage(slopUrl, { delayMs: 0 })
    console.log(`      -> Slop Variant Slop Score: ${slopScanReport.slopScore} (${slopScanReport.status})`)
    if (slopScanReport.flags.length > 0) {
      console.log(`         Flags: ${slopScanReport.flags.join("; ")}`)
    }

    // 3. Run ColdStart Agent Loop against the clean variant
    const targetName = "ColdStart Agent"
    const targetEmail = "agent@demo.solari"
    const task = `Open early access page at ${cleanUrl}, enter name "${targetName}" and email "${targetEmail}", submit the form, and report done.`
    const windowStart = Date.now()

    console.log(`\n[3/4] Running ColdStart Agent Loop against clean variant (MOCK mode)...`)
    const page = new DemoMockPage(demo.baseUrl)
    const model = new DemoScriptedModel(targetName, targetEmail)

    agentResult = await runAgentLoop({
      page,
      model,
      baseUrl: cleanUrl,
      task,
      runDir,
      runId,
      maxSteps: 10,
    })

    console.log(`      Agent finished: status=${agentResult.status}, steps=${agentResult.stepsTaken}`)

    // 4. Run fail-closed Ground-Truth Verifier against SQLite database
    console.log(`\n[4/4] Running fail-closed Demo Verifier against SQLite ground truth...`)
    verifierResult = verifyDemoSignup({
      expectedEmail: targetEmail,
      db: demo.db,
      windowStart,
    })
    console.log(`      Verifier completed: task_completed=${verifierResult.task_completed}`)
    console.log(`      - D1 (row exists)      : ${verifierResult.checks.D1.passed ? "PASS" : "FAIL"}`)
    console.log(`      - D2 (email matches)   : ${verifierResult.checks.D2.passed ? "PASS" : "FAIL"}`)
    console.log(`      - D3 (window validity) : ${verifierResult.checks.D3.passed ? "PASS" : "FAIL"}`)

    // 5. Persist combined report
    const artifactsDir = resolve("artifacts")
    mkdirSync(artifactsDir, { recursive: true })
    const reportPath = join(artifactsDir, "combined-demo-report.json")

    const report = {
      generated_at: new Date().toISOString(),
      run_id: runId,
      // Honesty (audit B3/W11): this demo's agent is DemoScriptedModel driving
      // DemoMockPage — a hardcoded 6-action sequence, NOT a live model. The
      // report is explicitly marked scripted so the renderer shows the offline
      // disclosure instead of attributing a model name to this run.
      scripted: true,
      targets: {
        clean_url: cleanUrl,
        slop_url: slopUrl,
      },
      slop_catcher_reports: {
        clean: cleanScanReport,
        slop: slopScanReport,
      },
      coldstart_agent_result: {
        task: agentResult.task,
        status: agentResult.status,
        steps_taken: agentResult.stepsTaken,
        final_title: agentResult.finalTitle,
        actions: agentResult.actions.map((a) => ({
          step: a.step,
          action: a.action,
          ok: a.ok,
          rationale: a.rationale,
        })),
      },
      ground_truth_verifier: verifierResult,
    }

    writeFileSync(reportPath, JSON.stringify(report, null, 2), "utf8")
    console.log(`\nReport written to: ${reportPath}`)

    // 6. Print Console Table
    console.log("\n" + "=".repeat(78))
    console.log(" COMBINED DEMO SUMMARY")
    console.log("=".repeat(78))

    const summaryTable = [
      {
        Target: "Clean Landing Page (GET /)",
        "Slop Score": cleanScanReport.slopScore,
        "Design Status": cleanScanReport.status,
        "Task Completed": agentResult.status === "done" ? "YES" : "NO",
        Verifier: verifierResult.task_completed ? "PASS (D1, D2, D3)" : "FAIL",
      },
      {
        Target: "Slop Landing Page (GET /?slop=1)",
        "Slop Score": slopScanReport.slopScore,
        "Design Status": slopScanReport.status,
        "Task Completed": "N/A",
        Verifier: "N/A",
      },
    ]

    console.table(summaryTable)
    console.log("=".repeat(78) + "\n")

    return report
  } finally {
    await demo.close()
  }
}

const isDirectRun =
  process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url))

if (isDirectRun) {
  runCombinedDemo().catch((err) => {
    console.error("[run-combined-demo] Fatal error:", err)
    process.exit(1)
  })
}

