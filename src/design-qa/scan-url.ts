/**
 * scan-url.ts — Standalone URL scanner for Slop-Catcher.
 *
 * Scans external web pages and live URLs for AI slop and UI/UX design flaws.
 * In production, this boots a Solari microVM, navigates to the URL, captures
 * a screenshot, and extracts computed CSS.
 * Provides a mock/dry-run mode for deterministic offline scanning and CI.
 */

import { evaluateRunDesign, type DesignQAResult } from "./orchestrator.ts"

/**
 * Honesty disclosure (audit B4): every scan performed by this module is a
 * MOCK / dry-run. It never boots a Solari microVM, never takes a real
 * screenshot, and always scores with MockVlmClient fixture output. For
 * localhost targets the "detected" contrast/spacing metrics come from the app
 * self-reporting its own /design-metrics.json (a circular measurement), and for
 * external URLs they come from fixed mock-fallback constants. The committed
 * getsolari.com scan artifact (artifacts/runs/scan_mtkwzs8r_https___getsolari_com/)
 * is 100% fixture data from this mock fallback — it is NOT a real audit of the
 * sponsor's site and must never be cited as one.
 */
export const SCAN_MOCK_DISCLOSURE =
  "MOCK / dry-run scan: no microVM was booted and no live VLM call was made — " +
  "this is NOT a live VLM audit of the target page."

export interface ScanUrlOptions {
  /** Simulated network/VM delay in ms (default: 1000). */
  delayMs?: number
  /** Custom mock computed CSS payload (optional). */
  computedCss?: any
  /** Custom base64 screenshot (optional). */
  screenshotBase64?: string
  /** Custom runId prefix or identifier (optional). */
  runId?: string
}

// 1x1 transparent PNG fallback screenshot
const DEFAULT_MOCK_SCREENSHOT_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

function isLocalUrl(urlStr: string): boolean {
  try {
    const u = new URL(urlStr)
    return (
      u.hostname === "localhost" ||
      u.hostname === "127.0.0.1" ||
      u.hostname === "::1" ||
      u.hostname === "0.0.0.0" ||
      u.hostname.endsWith(".localhost")
    )
  } catch {
    return false
  }
}

/**
 * Scans an external URL for design flaws and AI slop using the Slop-Catcher engine.
 *
 * In mock/dry-run mode, simulates booting a Solari microVM, navigating to the URL,
 * taking a screenshot, and extracting computed CSS, then passes the data to
 * evaluateRunDesign. In local mode (e.g. localhost/127.0.0.1), fetches /design-metrics.json
 * for the deterministic layer instead of using the mock fallback.
 *
 * @param targetUrl Web address to audit (e.g., "https://example.com" or "http://localhost:3000/").
 * @param options Optional configuration for delays, mock overrides, or run IDs.
 * @returns Parsed DesignQAResult containing slopScore, status, flags, and recommendation.
 */
export async function scanExternalPage(
  targetUrl: string,
  options?: ScanUrlOptions
): Promise<DesignQAResult> {
  const delay = options?.delayMs ?? 1000

  // Audit B4: unambiguous mock labeling in CLI/console output.
  console.log(`[MOCK / DRY-RUN] No microVM is booted — simulating navigation to ${targetUrl}`)

  if (delay > 0) {
    await new Promise((resolve) => setTimeout(resolve, delay))
  }

  // Generate safe run ID based on URL and timestamp
  const sanitized = targetUrl.replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 32)
  const runId = options?.runId ?? `scan_${Date.now().toString(36)}_${sanitized}`

  const screenshot = options?.screenshotBase64 ?? DEFAULT_MOCK_SCREENSHOT_BASE64
  let computedCss = options?.computedCss

  if (!computedCss && isLocalUrl(targetUrl)) {
    try {
      const u = new URL(targetUrl)
      const metricsUrl = new URL(`/design-metrics.json${u.search}`, u.origin)
      const res = await fetch(metricsUrl)
      if (res.ok) {
        computedCss = await res.json()
      }
    } catch {
      // Fall through to default mock fallback
    }
  }

  if (!computedCss) {
    computedCss = {
      contrastRatio: 7.2,
      spacingVariance: 0,
    }
  }

  return evaluateRunDesign(runId, screenshot, computedCss, {
    targetUrl,
    mode: "MOCK",
    disclosure: SCAN_MOCK_DISCLOSURE,
  })
}

