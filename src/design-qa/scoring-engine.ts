/**
 * scoring-engine.ts — Hybrid determination logic for the Slop-Catcher module.
 *
 * Combines deterministic CSS inspection (WCAG contrast ratios and 4px/8px grid
 * spacing variance) with subjective Vision-Language Model (VLM) aesthetic scores.
 *
 * Weighting formula:
 *   Final Score = (Deterministic Penalties * 0.6) + (vlmSlopScore * 0.4)
 * Clamped between 0 (flawless) and 100 (extreme slop / inaccessible).
 */

/** Metrics collected from deterministic CSS analysis and VLM visual inspection. */
export interface DesignMetrics {
  /** Measured color contrast ratio (e.g., 4.5 is WCAG AA threshold for normal text). */
  contrastRatio: number
  /** Spacing variance indicating off-grid margins/padding (e.g. not multiples of 4px). */
  spacingVariance: number
  /** Subjective aesthetic/slop score from the VLM (0-100). */
  vlmSlopScore: number
}

/** Configurable parameters for the hybrid scoring determination. */
export interface ScoringOptions {
  /** Minimum acceptable contrast ratio (default: 4.5, WCAG AA). */
  minContrastRatio?: number
  /** Threshold above which spacing variance triggers a penalty (default: 0). */
  spacingVarianceThreshold?: number
  /** Hard penalty applied when contrast ratio is below minimum (default: 40). */
  contrastPenalty?: number
  /** Penalty applied when spacing variance exceeds threshold (default: 20). */
  spacingPenalty?: number
  /** Weight applied to deterministic penalties (default: 0.6). */
  deterministicWeight?: number
  /** Weight applied to subjective VLM slop score (default: 0.4). */
  vlmWeight?: number
}

/** Detailed score breakdown for observability and telemetry reporting. */
export interface SlopScoreBreakdown {
  contrastRatio: number
  spacingVariance: number
  vlmSlopScore: number
  contrastPenalty: number
  spacingPenalty: number
  totalDeterministicPenalties: number
  weightedDeterministicScore: number
  weightedVlmScore: number
  rawScore: number
  finalScore: number
}

export const DEFAULT_MIN_CONTRAST_RATIO = 4.5
export const DEFAULT_CONTRAST_PENALTY = 40
export const DEFAULT_SPACING_VARIANCE_THRESHOLD = 0
export const DEFAULT_SPACING_PENALTY = 20
export const DEFAULT_DETERMINISTIC_WEIGHT = 0.6
export const DEFAULT_VLM_WEIGHT = 0.4

/**
 * Computes a comprehensive breakdown of deterministic penalties and VLM weighting.
 */
export function evaluateScoreBreakdown(
  metrics: DesignMetrics,
  options: ScoringOptions = {}
): SlopScoreBreakdown {
  const minContrast = options.minContrastRatio ?? DEFAULT_MIN_CONTRAST_RATIO
  const contrastPenaltyPoints = options.contrastPenalty ?? DEFAULT_CONTRAST_PENALTY
  const spacingThreshold = options.spacingVarianceThreshold ?? DEFAULT_SPACING_VARIANCE_THRESHOLD
  const spacingPenaltyPoints = options.spacingPenalty ?? DEFAULT_SPACING_PENALTY
  const deterministicWeight = options.deterministicWeight ?? DEFAULT_DETERMINISTIC_WEIGHT
  const vlmWeight = options.vlmWeight ?? DEFAULT_VLM_WEIGHT

  // 1. Contrast ratio check: below 4.5 incurs hard penalty of 40 points
  const contrastPenalty = metrics.contrastRatio < minContrast ? contrastPenaltyPoints : 0

  // 2. Spacing variance check: off-grid variance incurs penalty of 20 points
  const spacingPenalty = metrics.spacingVariance > spacingThreshold ? spacingPenaltyPoints : 0

  const totalDeterministicPenalties = contrastPenalty + spacingPenalty

  // Clamp input VLM score to 0..100 before weighting
  const normalizedVlmScore = Math.max(0, Math.min(100, metrics.vlmSlopScore))

  // 3. Weighted hybrid formula: (Deterministic Penalties * 0.6) + (vlmSlopScore * 0.4)
  const weightedDeterministicScore = totalDeterministicPenalties * deterministicWeight
  const weightedVlmScore = normalizedVlmScore * vlmWeight
  const rawScore = weightedDeterministicScore + weightedVlmScore

  // 4. Final score clamped between 0 and 100, rounded to 2 decimal places
  const finalScore = Math.max(0, Math.min(100, Math.round(rawScore * 100) / 100))

  return {
    contrastRatio: metrics.contrastRatio,
    spacingVariance: metrics.spacingVariance,
    vlmSlopScore: metrics.vlmSlopScore,
    contrastPenalty,
    spacingPenalty,
    totalDeterministicPenalties,
    weightedDeterministicScore,
    weightedVlmScore,
    rawScore,
    finalScore,
  }
}

/**
 * Calculates the final hybrid slop score combining deterministic CSS checks and VLM analysis.
 *
 * Rules:
 * - If contrastRatio < 4.5: add hard penalty of 40 points.
 * - If spacingVariance is high (> 0): add penalty of 20 points.
 * - Final score = (Deterministic Penalties * 0.6) + (vlmSlopScore * 0.4).
 * - Returned score is clamped between 0 and 100.
 *
 * @param metrics Design metrics containing contrastRatio, spacingVariance, and vlmSlopScore.
 * @param options Optional custom weights or penalty thresholds.
 * @returns Final slop score between 0 and 100.
 */
export function calculateFinalSlopScore(
  metrics: DesignMetrics,
  options?: ScoringOptions
): number {
  return evaluateScoreBreakdown(metrics, options).finalScore
}
