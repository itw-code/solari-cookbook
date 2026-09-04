/**
 * slop-scoring.test.ts — Unit tests for the hybrid Slop-Catcher determination logic.
 */
import { describe, it, expect } from "vitest"
import {
  calculateFinalSlopScore,
  evaluateScoreBreakdown,
  type DesignMetrics,
} from "../src/design-qa/scoring-engine.ts"

describe("Slop-Catcher Hybrid Determination Logic", () => {
  it("Test 1 (Control): returns low score (< 10) for perfect metrics", () => {
    const controlMetrics: DesignMetrics = {
      contrastRatio: 7.0,
      spacingVariance: 0,
      vlmSlopScore: 5,
    }

    const finalScore = calculateFinalSlopScore(controlMetrics)

    // Penalties: contrast = 0, spacing = 0 -> total = 0
    // (0 * 0.6) + (5 * 0.4) = 2
    expect(finalScore).toBe(2)
    expect(finalScore).toBeLessThan(10)
  })

  it("Test 2 (Slop Injection): returns high score (> 70) for terrible metrics", () => {
    const slopMetrics: DesignMetrics = {
      contrastRatio: 2.0,
      spacingVariance: 15,
      vlmSlopScore: 90,
    }

    const finalScore = calculateFinalSlopScore(slopMetrics)

    // Penalties: contrast = 40, spacing = 20 -> total = 60
    // (60 * 0.6) + (90 * 0.4) = 36 + 36 = 72
    expect(finalScore).toBe(72)
    expect(finalScore).toBeGreaterThan(70)
  })

  it("Test 3 (Valid Dark Theme): returns low score (< 20) without false-positive on valid themes", () => {
    const darkThemeMetrics: DesignMetrics = {
      contrastRatio: 8.0,
      spacingVariance: 0,
      vlmSlopScore: 15,
    }

    const finalScore = calculateFinalSlopScore(darkThemeMetrics)

    // Penalties: contrast = 0, spacing = 0 -> total = 0
    // (0 * 0.6) + (15 * 0.4) = 6
    expect(finalScore).toBe(6)
    expect(finalScore).toBeLessThan(20)
  })

  it("triggers contrast penalty of 40 when contrast ratio is strictly below 4.5", () => {
    const belowThreshold: DesignMetrics = {
      contrastRatio: 4.49,
      spacingVariance: 0,
      vlmSlopScore: 0,
    }
    // (40 * 0.6) + (0 * 0.4) = 24
    expect(calculateFinalSlopScore(belowThreshold)).toBe(24)

    const atThreshold: DesignMetrics = {
      contrastRatio: 4.5,
      spacingVariance: 0,
      vlmSlopScore: 0,
    }
    // (0 * 0.6) + (0 * 0.4) = 0
    expect(calculateFinalSlopScore(atThreshold)).toBe(0)
  })

  it("triggers spacing variance penalty of 20 when spacing variance is greater than 0", () => {
    const withSpacingVariance: DesignMetrics = {
      contrastRatio: 5.0,
      spacingVariance: 2,
      vlmSlopScore: 0,
    }
    // (20 * 0.6) + (0 * 0.4) = 12
    expect(calculateFinalSlopScore(withSpacingVariance)).toBe(12)
  })

  it("clamps final score between 0 and 100", () => {
    const overHundred: DesignMetrics = {
      contrastRatio: 1.0,
      spacingVariance: 10,
      vlmSlopScore: 100,
    }
    // (60 * 0.6) + (100 * 0.4) = 36 + 40 = 76
    expect(calculateFinalSlopScore(overHundred)).toBeLessThanOrEqual(100)

    const extremeScore = calculateFinalSlopScore(
      { contrastRatio: 1.0, spacingVariance: 20, vlmSlopScore: 100 },
      { contrastPenalty: 100, spacingPenalty: 100, deterministicWeight: 1.0 }
    )
    expect(extremeScore).toBe(100)

    const negativeScore = calculateFinalSlopScore({
      contrastRatio: 10.0,
      spacingVariance: 0,
      vlmSlopScore: -50,
    })
    expect(negativeScore).toBe(0)
  })

  it("provides detailed intermediate values via evaluateScoreBreakdown", () => {
    const metrics: DesignMetrics = {
      contrastRatio: 3.5,
      spacingVariance: 8,
      vlmSlopScore: 50,
    }
    const breakdown = evaluateScoreBreakdown(metrics)

    expect(breakdown.contrastPenalty).toBe(40)
    expect(breakdown.spacingPenalty).toBe(20)
    expect(breakdown.totalDeterministicPenalties).toBe(60)
    expect(breakdown.weightedDeterministicScore).toBe(36)
    expect(breakdown.weightedVlmScore).toBe(20)
    expect(breakdown.finalScore).toBe(56)
  })
})
