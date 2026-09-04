/**
 * prng.spec.ts — determinism tests for the seeded PRNG + domain-separated
 * sub-streams (DESIGN.md §2 determinism rule). `sameSeed -> same output`.
 */
import { describe, it, expect } from "vitest"
import { mulberry32, deriveStream, hashString } from "../src/generate-variants/prng.js"

describe("prng", () => {
  it("mulberry32 is deterministic for the same seed", () => {
    const a = mulberry32(42)
    const b = mulberry32(42)
    const seqA = Array.from({ length: 10 }, () => a())
    const seqB = Array.from({ length: 10 }, () => b())
    expect(seqA).toEqual(seqB)
  })

  it("different seeds yield different streams", () => {
    const a = mulberry32(1)
    const b = mulberry32(2)
    expect(a()).not.toBe(b())
  })

  it("domain-separated sub-streams differ per axis", () => {
    const s1 = deriveStream(42, "P1_relabel")
    const s2 = deriveStream(42, "P2_structure")
    expect(s1()).not.toBe(s2())
  })

  it("hashString is stable and varies across inputs", () => {
    expect(hashString("P1_relabel")).toBe(hashString("P1_relabel"))
    expect(hashString("P1_relabel")).not.toBe(hashString("P2_structure"))
  })

  it("sub-streams are re-derivable (same seed + axis -> same first draw)", () => {
    const a = deriveStream(7, "task_customer")()
    const b = deriveStream(7, "task_customer")()
    expect(a).toBe(b)
  })
})
