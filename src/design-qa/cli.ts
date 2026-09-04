/**
 * cli.ts — Standalone runner for the Slop-Catcher Design QA module.
 *
 * Runs a single mock evaluation against the s0 baseline seed and prints the
 * result to the console.
 * Usage: npm run qa:slop
 */

import { evaluateRunDesign } from "./orchestrator.ts"

async function main(): Promise<void> {
  const runId = "r_baseline_s0"
  // 1x1 transparent mock PNG screenshot
  const mockScreenshotBase64 =
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

  console.log(`[design-qa] Evaluating run: ${runId} (baseline seed 0)...`)
  const result = await evaluateRunDesign(runId, mockScreenshotBase64, {
    contrastRatio: 7.2,
    spacingVariance: 0,
  })

  console.log("=".repeat(60))
  console.log("DESIGN QA EVALUATION RESULT")
  console.log("=".repeat(60))
  console.log(`Run ID         : ${result.runId}`)
  console.log(`Slop Score     : ${result.slopScore}/100`)
  console.log(`Status         : ${result.status}`)
  console.log(`Flags          : ${result.flags.length > 0 ? result.flags.join(", ") : "(none)"}`)
  if (result.recommendation) {
    console.log(`Recommendation : ${result.recommendation}`)
  }
  console.log("=".repeat(60))
}

main().catch((err) => {
  console.error("[design-qa] Evaluation failed:", err)
  process.exit(1)
})
