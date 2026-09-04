/**
 * axes.spec.ts — seed determinism tests for the variant factory.
 * Verifies `sameSeed -> sameVariant`, the canonical baseline (seed=0, all axes
 * k=0), and that intensities stay within [0, K_max].
 */
import { describe, it, expect } from "vitest"
import { deriveIntensities, deriveConfig, BASELINE_INTENSITY, AXIS_MAX } from "../src/generate-variants/axes.js"
import { buildVariant, buildVariantMatrix, VARIANT_SEEDS } from "../src/generate-variants/variants.js"

describe("axes", () => {
  it("seed 0 is the canonical baseline (all axes k=0)", () => {
    expect(deriveIntensities(0)).toEqual(BASELINE_INTENSITY)
  })

  it("same seed -> same intensities", () => {
    expect(deriveIntensities(123)).toEqual(deriveIntensities(123))
  })

  it("intensities stay within [0, K_max] across many seeds", () => {
    for (let s = 0; s < 200; s++) {
      const i = deriveIntensities(s)
      for (const key of Object.keys(AXIS_MAX) as (keyof typeof AXIS_MAX)[]) {
        expect(i[key]).toBeGreaterThanOrEqual(0)
        expect(i[key]).toBeLessThanOrEqual(AXIS_MAX[key])
      }
    }
  })

  it("same seed -> identical full perturbation config", () => {
    expect(deriveConfig(17)).toEqual(deriveConfig(17))
  })

  it("baseline config uses canonical labels/layout", () => {
    const c = deriveConfig(0)
    expect(c.P1.create).toBe("Create Invoice")
    expect(c.P1.customer).toBe("Customer")
    expect(c.P1.submit).toBe("Submit")
    expect(c.P2.layout).toBe("single")
    expect(c.P3.metaOrder).toEqual(["customer", "invoice_date", "due_date", "tax_rate"])
  })

  it("k>0 for P1 actually renames at least one label", () => {
    const c = deriveConfig(17)
    expect(c.axis.P1_relabel).toBeGreaterThan(0)
    expect(c.P1.create).not.toBe("Create Invoice")
  })
})

describe("variants", () => {
  it("buildVariant is deterministic (same seed -> identical record)", () => {
    expect(buildVariant(42)).toEqual(buildVariant(42))
  })

  it("variant_id matches the required scheme", () => {
    const v = buildVariant(42)
    expect(v.variant_id).toMatch(/^inv__s42__P1:\d+__P2:\d+__P3:\d+__P4:\d+__P5:\d+$/)
  })

  it("variant matrix includes the baseline seed=0 and >=10 variants", () => {
    const m = buildVariantMatrix()
    expect(m.variant_count).toBeGreaterThanOrEqual(10)
    expect(m.variants[0]!.seed).toBe(0)
    expect(m.variants[0]!.intensity_by_axis).toEqual(BASELINE_INTENSITY)
    expect(VARIANT_SEEDS[0]).toBe(0)
  })

  it("variant matrix is deterministic (re-build equal)", () => {
    expect(buildVariantMatrix()).toEqual(buildVariantMatrix())
  })
})
