/**
 * prng.ts — mulberry32 PRNG + domain-separated sub-streams.
 *
 * ColdStart determinism rule (DESIGN.md §2):
 *   - A single seeded PRNG (mulberry32).
 *   - Each axis / sub-domain draws from its own sub-stream so axes never
 *     interfere and adding an axis can never perturb another axis's output:
 *       stream = prng(seed ^ hash(axisId))
 *   - `sameSeed -> same output` (a pure function of the seed only).
 *
 * These are the lowest-level shared primitives in the variant factory. They are
 * also imported by the variant app so that the app and the generator agree on
 * what a given seed means.
 */

/**
 * mulberry32 — a tiny, fast, seeded 32-bit PRNG.
 * Returns a function that emits floats in [0, 1).
 */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return function next(): number {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** FNV-1a 32-bit string hash (stable, not cryptographic). */
export function hashString(input: string): number {
  let h = 0x811c9dc5
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return h >>> 0
}

/**
 * Domain-separated sub-stream: `stream = prng(seed ^ hash(axisId))`.
 * `axisId` is a stable, human-readable identifier for the sub-domain
 * (e.g. "P1_relabel", "task", "customer"). Changing one sub-domain's seed
 * derivation never affects another.
 */
export function deriveStream(seed: number, axisId: string): () => number {
  const mixed = (seed ^ hashString(axisId)) >>> 0
  return mulberry32(mixed)
}

/** Pick a uniformly-distributed integer in [0, max] (inclusive) from a stream. */
export function pickInt(stream: () => number, max: number): number {
  return Math.floor(stream() * (max + 1))
}

/** Pick a uniformly-distributed integer in [min, max] (inclusive) from a stream. */
export function pickIntIn(stream: () => number, min: number, max: number): number {
  return min + Math.floor(stream() * (max - min + 1))
}

/** Pick one element from a non-empty array using a stream. */
export function pick<T>(stream: () => number, arr: readonly T[]): T {
  const idx = Math.floor(stream() * arr.length) % arr.length
  return arr[idx]!
}

/** rng.range helper — draw a float in [min, max). */
export function inRange(stream: () => number, min: number, max: number): number {
  return min + stream() * (max - min)
}
