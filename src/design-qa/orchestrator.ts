/**
 * orchestrator.ts — Solari sandbox Design QA orchestrator.
 *
 * Serves as the execution bridge between Solari sandbox browser sessions,
 * deterministic computed CSS extraction, and the Slop-Catcher hybrid scoring engine.
 * Automatically persists design-qa-report.json in artifacts/runs/<run_id>/.
 */

import { mkdir, writeFile } from "node:fs/promises"
import { join, resolve } from "node:path"
import { evaluateDesignQuality, type SlopReport } from "./slop-catcher.ts"
import { calculateFinalSlopScore, type DesignMetrics } from "./scoring-engine.ts"

export type DesignQAStatus = "PASS" | "WARN" | "BLOCK"

/** Result payload emitted by the Design QA orchestrator for a Solari run. */
export interface DesignQAResult {
  runId: string
  slopScore: number
  status: DesignQAStatus
  flags: string[]
  recommendation?: string
  metrics?: DesignMetrics
  targetUrl?: string
  /**
   * Execution mode of this scan (audit B4 honesty labeling):
   * "MOCK" = mock/dry-run — MockVlmClient fixture + self-reported/fallback CSS
   * metrics; NOT a live VLM audit. "LIVE" = real sandbox screenshot + live VLM.
   */
  mode?: "MOCK" | "LIVE"
  /** Explicit provenance disclosure, e.g. for mock scans of external pages. */
  disclosure?: string
}

/** Mock fallback metrics used when computed CSS is omitted or unavailable. */
export const MOCK_FALLBACK_CSS_METRICS: { contrastRatio: number; spacingVariance: number } = {
  contrastRatio: 7.0, // High WCAG-compliant contrast by default
  spacingVariance: 0, // Clean on-grid spacing by default
}

/**
 * Determines the gatekeeper status based on the final hybrid slop score.
 * - < 30: PASS (acceptable quality, ready to proceed)
 * - 30..59: WARN (minor aesthetic/spacing flaws)
 * - >= 60: BLOCK (critical accessibility failures or severe AI slop)
 */
export function determineQAStatus(slopScore: number): DesignQAStatus {
  if (slopScore < 30) return "PASS"
  if (slopScore < 60) return "WARN"
  return "BLOCK"
}

/**
 * Normalizes or extracts deterministic design metrics from the computed CSS payload.
 */
function extractCssMetrics(computedCss?: any): { contrastRatio: number; spacingVariance: number } {
  if (!computedCss || typeof computedCss !== "object") {
    return { ...MOCK_FALLBACK_CSS_METRICS }
  }

  const contrastRatio =
    typeof computedCss.contrastRatio === "number" && !Number.isNaN(computedCss.contrastRatio)
      ? computedCss.contrastRatio
      : MOCK_FALLBACK_CSS_METRICS.contrastRatio

  const spacingVariance =
    typeof computedCss.spacingVariance === "number" && !Number.isNaN(computedCss.spacingVariance)
      ? computedCss.spacingVariance
      : MOCK_FALLBACK_CSS_METRICS.spacingVariance

  return { contrastRatio, spacingVariance }
}

/**
 * Evaluates sandbox run design quality by combining deterministic CSS checks
 * with subjective VLM visual analysis, and persists the result to
 * `artifacts/runs/<run_id>/design-qa-report.json`.
 *
 * @param runId Identifier for the Solari sandbox execution run.
 * @param screenshotBase64 Base64-encoded PNG/JPEG screenshot of the rendered app.
 * @param computedCss Optional computed CSS metrics or extraction payload.
 * @param options Optional output directory override.
 * @returns DesignQAResult containing runId, slopScore, status ('PASS' | 'WARN' | 'BLOCK'), and flags.
 */
export async function evaluateRunDesign(
  runId: string,
  screenshotBase64: string,
  computedCss?: any,
  options?: { outputDir?: string; targetUrl?: string; mode?: "MOCK" | "LIVE"; disclosure?: string }
): Promise<DesignQAResult> {
  const { contrastRatio, spacingVariance } = extractCssMetrics(computedCss)

  const deterministicFlags: string[] = []
  if (contrastRatio < 4.5) {
    deterministicFlags.push(`Low contrast ratio detected (${contrastRatio}:1 < 4.5:1 WCAG AA)`)
  }
  if (spacingVariance > 0) {
    deterministicFlags.push(`Off-grid spacing variance detected (${spacingVariance}px deviation)`)
  }

  // Multimodal visual inspection via VLM (runs offline deterministically with MockVlm)
  const vlmReport: SlopReport = await evaluateDesignQuality(screenshotBase64)

  const metrics: DesignMetrics = {
    contrastRatio,
    spacingVariance,
    vlmSlopScore: vlmReport.slopScore,
  }

  const finalScore = calculateFinalSlopScore(metrics)
  const status = determineQAStatus(finalScore)

  const allFlags = Array.from(new Set([...deterministicFlags, ...vlmReport.flags]))

  const result: DesignQAResult = {
    runId,
    slopScore: finalScore,
    status,
    flags: allFlags,
    recommendation: vlmReport.recommendation,
    metrics,
    ...(options?.targetUrl ? { targetUrl: options.targetUrl } : {}),
    ...(options?.mode ? { mode: options.mode } : {}),
    ...(options?.disclosure ? { disclosure: options.disclosure } : {}),
  }

  // 1. Artifact Persistence: save result as design-qa-report.json inside artifacts/runs/<run_id>/
  const targetDir = options?.outputDir ?? join(resolve("artifacts/runs"), runId)
  try {
    await mkdir(targetDir, { recursive: true })
    const reportPath = join(targetDir, "design-qa-report.json")
    await writeFile(reportPath, JSON.stringify(result, null, 2), "utf8")
  } catch (err) {
    console.warn(`[design-qa] Failed to persist report for ${runId}:`, err)
  }

  return result
}
