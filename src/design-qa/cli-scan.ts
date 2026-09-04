/**
 * cli-scan.ts — Standalone URL scanning CLI for Slop-Catcher.
 *
 * Usage:
 *   npm run scan:url -- https://example.com
 *   npm run scan:url
 */

import { fileURLToPath } from "node:url"
import { resolve } from "node:path"
import { scanExternalPage, SCAN_MOCK_DISCLOSURE } from "./scan-url.ts"

function parseTargetUrl(argv: string[]): string {
  // Filter out npm argument separators like "--"
  const urlArg = argv.find((arg) => arg !== "--" && !arg.startsWith("-") && arg.trim().length > 0)
  return urlArg ? urlArg.trim() : "https://getsolari.com"
}

/**
 * Scan a URL and print an audit report.
 *
 * Honesty (audit B4): the entire scan path is a MOCK / dry-run — no microVM is
 * booted, no screenshot is taken, and the VLM score is a MockVlmClient fixture
 * (for localhost targets the metrics are self-reported by the scanned app via
 * /design-metrics.json; for external URLs they are fixed mock-fallback
 * constants). The output below labels every run accordingly and never presents
 * a scan as a live audit.
 */
export async function main(argv: string[] = process.argv.slice(2)): Promise<void> {
  const targetUrl = parseTargetUrl(argv)

  console.log("=".repeat(60))
  console.log("SLOP-CATCHER EXTERNAL PAGE SCANNER")
  console.log("=".repeat(60))
  console.log("MODE: MOCK / DRY-RUN — NOT a live audit (no microVM booted; VLM score is a mock fixture)")
  console.log(`(${SCAN_MOCK_DISCLOSURE})`)
  console.log(`Target URL : ${targetUrl}`)
  console.log("-".repeat(60))

  const result = await scanExternalPage(targetUrl)

  console.log("-".repeat(60))
  console.log("SCAN AUDIT REPORT (MOCK / DRY-RUN — NOT a live audit)")
  console.log("-".repeat(60))
  console.log(`Target URL       : ${targetUrl}`)
  console.log(`Mode             : MOCK (VLM score = mock VLM fixture; metrics = self-reported/fallback)`)
  console.log(`Final Slop Score : ${result.slopScore}/100`)
  console.log(`Status           : ${result.status}`)
  console.log(
    `Flags Detected   : ${result.flags.length > 0 ? result.flags.join(", ") : "None (Clean Design)"}`
  )
  if (result.recommendation) {
    console.log(`Recommendation   : ${result.recommendation}`)
  }
  if (result.metrics) {
    console.log(
      `Measured Metrics : Contrast ${result.metrics.contrastRatio}:1 | Spacing Variance ${result.metrics.spacingVariance}px | VLM Score ${result.metrics.vlmSlopScore}`
    )
  }
  console.log("=".repeat(60))
}

const isDirectRun =
  process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)

if (isDirectRun) {
  main().catch((err) => {
    console.error("[scan-url] Scan failed:", err)
    process.exit(1)
  })
}
