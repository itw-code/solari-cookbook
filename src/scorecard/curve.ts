/**
 * curve.ts — ColdStart STEP 06: generalization curve, per-axis success, "where it
 * breaks", and a dependency-free PNG chart renderer.
 *
 * Pure functions:
 *   - successByAxis(runs)        -> { axis: success_rate } (runs where intensity>0)
 *   - generalizationCurve(runs)  -> [{axis,intensity,success_rate,n_runs}]
 *   - whereItBreaks(runs)        -> [{axis,intensity,variant_id,failure_mode}]
 *
 * renderCurvePng(runs, outPath) draws success_rate vs intensity per axis using
 * ONLY the Node stdlib (`node:zlib`) — no chart/image library exists in this repo.
 * The PNG is an auxiliary visual; the authoritative numbers are scorecard.json.
 *
 * Security: no keys, no network. Purely data -> pixels.
 */

import { deflateSync } from "node:zlib"
import { writeFileSync, mkdirSync } from "node:fs"
import { dirname } from "node:path"
import {
  AXIS_KEYS,
  isSuccess,
  type AxisKey,
  type BreakEntry,
  type GeneralizationPoint,
  type RunRecord,
} from "./build.ts"

// ---------------------------------------------------------------------------
// Pure aggregation
// ---------------------------------------------------------------------------

/** successes / runs where the axis intensity is > 0 (DESIGN §5 definition). */
export function successByAxis(runs: RunRecord[]): Record<AxisKey, number> {
  const out = {} as Record<AxisKey, number>
  for (const axis of AXIS_KEYS) {
    const active = runs.filter((r) => r.intensity_by_axis[axis] > 0)
    const successes = active.filter(isSuccess).length
    out[axis] = active.length === 0 ? NaN : successes / active.length
  }
  return out
}

/** Group runs by (axis, intensity); include intensity 0 (the seed=0 baseline). */
export function generalizationCurve(runs: RunRecord[]): GeneralizationPoint[] {
  const points: GeneralizationPoint[] = []
  for (const axis of AXIS_KEYS) {
    const byIntensity = new Map<number, { total: number; succ: number }>()
    for (const r of runs) {
      const k = r.intensity_by_axis[axis]
      const slot = byIntensity.get(k) ?? { total: 0, succ: 0 }
      slot.total += 1
      if (isSuccess(r)) slot.succ += 1
      byIntensity.set(k, slot)
    }
    const sorted = [...byIntensity.entries()].sort((a, b) => a[0] - b[0])
    for (const [intensity, slot] of sorted) {
      points.push({ axis, intensity, success_rate: slot.total ? slot.succ / slot.total : NaN, n_runs: slot.total })
    }
  }
  return points
}

/** For every failed run, attribute a break entry to each axis it perturbed. */
export function whereItBreaks(runs: RunRecord[]): BreakEntry[] {
  const out: BreakEntry[] = []
  for (const r of runs) {
    if (isSuccess(r)) continue
    const mode = failureMode(r)
    for (const axis of AXIS_KEYS) {
      const intensity = r.intensity_by_axis[axis]
      if (intensity > 0) out.push({ axis, intensity, variant_id: r.variant_id, failure_mode: mode })
    }
  }
  return out
}

function failureMode(run: RunRecord): string {
  const s = run.agent.status
  if (s === "verifier_fail") {
    const top = run.outcome.verifier.field_errors[0]
    return top
      ? `verifier_fail: ${top.field} expected ${top.expected} got ${top.actual} (${run.outcome.verifier.field_errors.length} field error(s))`
      : `verifier_fail: task_completed=false but no field error diff (${run.outcome.verifier.checks_run.filter((c) => !c.passed).length} check(s) failed)`
  }
  if (s === "stuck") return `agent_stuck: terminated after ${run.agent.steps_taken}/${run.agent.max_steps} steps (repeated clicks, no new screenshot)`
  if (s === "step_cap") return `agent_step_cap: hit ${run.agent.max_steps} steps without reaching 'done'`
  if (s === "aborted") return `agent_aborted: ${run.agent.error ?? "terminated"}`
  return `unknown: ${s}`
}

// ---------------------------------------------------------------------------
// PNG chart renderer (dependency-free; node:zlib)
// ---------------------------------------------------------------------------

const AXIS_COLOR: Record<AxisKey, [number, number, number]> = {
  P1_relabel: [225, 29, 72],
  P2_structure: [217, 119, 6],
  P3_field_order: [8, 145, 178],
  P4_nav_order: [124, 58, 237],
  P5_theme: [22, 163, 74],
}
const AXIS_SHORT: Record<AxisKey, string> = {
  P1_relabel: "P1_RELABEL",
  P2_structure: "P2_STRUCTURE",
  P3_field_order: "P3_FIELD_ORDER",
  P4_nav_order: "P4_NAV_ORDER",
  P5_theme: "P5_THEME",
}

class Canvas {
  readonly w: number
  readonly h: number
  private readonly px: Uint8ClampedArray
  constructor(w: number, h: number) {
    this.w = w
    this.h = h
    this.px = new Uint8ClampedArray(w * h * 4)
    this.fill(255, 255, 255, 255)
  }
  fill(r: number, g: number, b: number, a: number): void {
    for (let i = 0; i < this.px.length; i += 4) {
      this.px[i] = r
      this.px[i + 1] = g
      this.px[i + 2] = b
      this.px[i + 3] = a
    }
  }
  set(x: number, y: number, r: number, g: number, b: number, a = 255): void {
    if (x < 0 || y < 0 || x >= this.w || y >= this.h) return
    const i = (y * this.w + x) * 4
    const ia = a / 255
    this.px[i] = Math.round(this.px[i] * (1 - ia) + r * ia)
    this.px[i + 1] = Math.round(this.px[i + 1] * (1 - ia) + g * ia)
    this.px[i + 2] = Math.round(this.px[i + 2] * (1 - ia) + b * ia)
    this.px[i + 3] = Math.round(this.px[i + 3] * (1 - ia) + a * ia)
  }
  rect(x: number, y: number, w: number, h: number, r: number, g: number, b: number): void {
    for (let yy = y; yy < y + h; yy++) for (let xx = x; xx < x + w; xx++) this.set(xx, yy, r, g, b)
  }
  line(x0: number, y0: number, x1: number, y1: number, r: number, g: number, b: number, w = 1): void {
    let dx = Math.abs(x1 - x0)
    let sx = x0 < x1 ? 1 : -1
    let dy = -Math.abs(y1 - y0)
    let sy = y0 < y1 ? 1 : -1
    let err = dx + dy
    for (let guard = 0; guard < 10000; guard++) {
      for (let ow = 0; ow < w; ow++) for (let oh = 0; oh < w; oh++) this.set(x0 + ow, y0 + oh, r, g, b)
      if (x0 === x1 && y0 === y1) break
      const e2 = 2 * err
      if (e2 >= dy) {
        err += dy
        x0 += sx
      }
      if (e2 <= dx) {
        err += dx
        y0 += sy
      }
    }
  }
  circle(cx: number, cy: number, radius: number, r: number, g: number, b: number): void {
    for (let dy = -radius; dy <= radius; dy++)
      for (let dx = -radius; dx <= radius; dx++)
        if (dx * dx + dy * dy <= radius * radius) this.set(cx + dx, cy + dy, r, g, b)
  }
  /** Draw a scaled 5x7 bitmap glyph; returns the next x. */
  glyph(x: number, y: number, rows: string[], scale: number, r: number, g: number, b: number): number {
    for (let col = 0; col < 5; col++) {
      for (let row = 0; row < 7; row++) {
        if (rows[row][col] === "#") {
          this.rect(x + col * scale, y + row * scale, scale, scale, r, g, b)
        }
      }
    }
    return x + 6 * scale
  }
  text(x: number, y: number, s: string, scale: number, r: number, g: number, b: number): number {
    let cx = x
    for (const ch of s.toUpperCase()) {
      const glyph = FONT[ch] ?? FONT["?"]
      cx = this.glyph(cx, y, glyph, scale, r, g, b)
    }
    return cx
  }
  toPng(): Buffer {
    const raw = Buffer.alloc(this.h * (1 + this.w * 4))
    let off = 0
    for (let y = 0; y < this.h; y++) {
      raw[off++] = 0 // filter: None
      for (let x = 0; x < this.w; x++) {
        const i = (y * this.w + x) * 4
        raw[off++] = this.px[i]
        raw[off++] = this.px[i + 1]
        raw[off++] = this.px[i + 2]
        raw[off++] = this.px[i + 3]
      }
    }
    const idat = deflateSync(raw)
    const chunks: Buffer[] = []
    chunks.push(pngChunk("IHDR", ihdr(this.w, this.h)))
    chunks.push(pngChunk("IDAT", idat))
    chunks.push(pngChunk("IEND", Buffer.alloc(0)))
    const sig = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])
    return Buffer.concat([sig, ...chunks])
  }
}

function ihdr(w: number, h: number): Buffer {
  const b = Buffer.alloc(13)
  b.writeUInt32BE(w, 0)
  b.writeUInt32BE(h, 4)
  b[8] = 8 // bit depth
  b[9] = 6 // color type RGBA
  b[10] = 0
  b[11] = 0
  b[12] = 0
  return b
}

function crc32(buf: Buffer): number {
  let c = ~0
  for (let i = 0; i < buf.length; i++) {
    c ^= buf[i]
    for (let k = 0; k < 8; k++) c = (c >>> 1) ^ (c & 1 ? 0xedb88320 : 0)
  }
  return ~c >>> 0
}
function pngChunk(type: string, data: Buffer): Buffer {
  const len = Buffer.alloc(4)
  len.writeUInt32BE(data.length, 0)
  const typeBuf = Buffer.from(type, "ascii")
  const crc = Buffer.alloc(4)
  crc.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])), 0)
  return Buffer.concat([len, typeBuf, data, crc])
}

// ---------------------------------------------------------------------------
// 5x7 bitmap font (rows; '#' = on). Upper-cased at render time.
// ---------------------------------------------------------------------------

const FONT: Record<string, string[]> = {
  " ": [".....", ".....", ".....", ".....", ".....", ".....", "....."],
  "?": ["###..", "#..#.", "...#.", "..#..", ".....", "..#..", "....."],
  ".": [".....", ".....", ".....", ".....", ".....", ".##..", ".##.."],
  "-": [".....", ".....", ".....", "#####", ".....", ".....", "....."],
  "_": [".....", ".....", ".....", ".....", ".....", ".....", "#####"],
  ":": [".....", ".##..", ".....", ".....", ".##..", ".....", "....."],
  "/": ["....#", "...#.", "...#.", "..#..", ".#...", ".#...", "#...."],
  "=": [".....", "#####", ".....", "#####", ".....", ".....", "....."],
  "(": ["...#.", "..#..", ".#...", ".#...", ".#...", "..#..", "...#."],
  ")": [".#...", "..#..", "...#.", "...#.", "...#.", "..#..", ".#..."],
  "%": ["##..#", "##.#.", "...#.", "..#..", ".#...", ".#..#", "#...#"],
  "0": [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
  "1": ["..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."],
  "2": [".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"],
  "3": ["####.", "....#", "....#", ".###.", "....#", "....#", "####."],
  "4": ["...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."],
  "5": ["#####", "#....", "####.", "....#", "....#", "#...#", ".###."],
  "6": [".###.", "#....", "#....", "####.", "#...#", "#...#", ".###."],
  "7": ["#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."],
  "8": [".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."],
  "9": [".###.", "#...#", "#...#", ".####", "....#", "....#", ".###."],
  A: [".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
  B: ["####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."],
  C: [".###.", "#...#", "#....", "#....", "#....", "#...#", ".###."],
  D: ["####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."],
  E: ["#####", "#....", "#....", "####.", "#....", "#....", "#####"],
  F: ["#####", "#....", "#....", "####.", "#....", "#....", "#...."],
  G: [".###.", "#...#", "#....", "#.###", "#...#", "#...#", ".####"],
  H: ["#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
  I: [".###.", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."],
  J: ["..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."],
  K: ["#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"],
  L: ["#....", "#....", "#....", "#....", "#....", "#....", "#####"],
  M: ["#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"],
  N: ["#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#", "#...#"],
  O: [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
  P: ["####.", "#...#", "#...#", "####.", "#....", "#....", "#...."],
  Q: [".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"],
  R: ["####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"],
  S: [".####", "#....", "#....", ".###.", "....#", "....#", "####."],
  T: ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."],
  U: ["#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
  V: ["#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."],
  W: ["#...#", "#...#", "#...#", "#.#.#", "#.#.#", "##.##", "#...#"],
  X: ["#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"],
  Y: ["#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."],
  Z: ["#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"],
}

/**
 * Render success_rate vs perturbation intensity per axis into a PNG.
 * Returns the output path.
 */
export async function renderCurvePng(runs: RunRecord[], outPath: string): Promise<string> {
  const curve = generalizationCurve(runs)
  const byAxis = new Map<AxisKey, GeneralizationPoint[]>()
  for (const p of curve) {
    const arr = byAxis.get(p.axis) ?? []
    arr.push(p)
    byAxis.set(p.axis, arr)
  }

  const W = 1150
  const H = 770
  const ml = 90
  const mr = 335
  const mt = 84
  const mb = 84
  const pw = W - ml - mr
  const ph = H - mt - mb

  const c = new Canvas(W, H)

  // Title + subtitle
  c.text(ml, 20, "COLDSTART GENERALIZATION CURVE", 3, 15, 23, 42)
  c.text(ml, 58, "SUCCESS RATE VS PERTURBATION INTENSITY (N=1 / VARIANT)", 2, 100, 116, 139)

  // Plot area
  c.rect(ml - 4, mt - 4, pw + 8, ph + 8, 244, 244, 246)

  // Horizontal gridlines + y labels (0..1)
  for (let i = 0; i <= 4; i++) {
    const frac = i / 4
    const y = mt + ph - frac * ph
    c.line(ml, y, ml + pw, y, 226, 232, 240)
    c.line(ml - 6, y, ml, y, 148, 163, 184)
    c.text(ml - 58, y - 8, frac.toFixed(2), 2, 71, 85, 105)
  }
  c.text(ml - 74, mt + ph / 2 - 8, "SUCCESS", 2, 71, 85, 105)
  c.text(ml - 74, mt + ph / 2 + 12, "RATE", 2, 71, 85, 105)

  // Vertical gridlines + x labels (0..max intensity per axis)
  const allInt = new Set<number>()
  for (const p of curve) allInt.add(p.intensity)
  const maxInt = Math.max(...allInt, 1)
  for (let i = 0; i <= maxInt; i++) {
    const x = ml + (i / maxInt) * pw
    c.line(x, mt, x, mt + ph, 236, 240, 245)
    c.line(x, mt + ph, x, mt + ph + 6, 148, 163, 184)
    c.text(x - 8, mt + ph + 16, String(i), 2, 71, 85, 105)
  }
  c.text(ml + pw / 2 - 90, H - 26, "PERTURBATION INTENSITY K", 2, 100, 116, 139)

  // Series per axis
  const lx = ml + pw + 22
  let ly = mt + 6
  for (const axis of AXIS_KEYS) {
    const pts = byAxis.get(axis) ?? []
    if (pts.length === 0) continue
    const [r, g, b] = AXIS_COLOR[axis]
    const xy = pts.map((p) => ({
      x: ml + (p.intensity / maxInt) * pw,
      y: mt + ph - p.success_rate * ph,
      rate: p.success_rate,
      n: p.n_runs,
    }))
    // line
    for (let i = 1; i < xy.length; i++) c.line(xy[i - 1].x, xy[i - 1].y, xy[i].x, xy[i].y, r, g, b, 3)
    // markers
    for (const p of xy) {
      c.circle(p.x, p.y, 7, r, g, b)
      c.circle(p.x, p.y, 3, 255, 255, 255)
      c.text(p.x - 12, p.y + 12, p.rate.toFixed(2), 1, 71, 85, 105)
    }
    // Legend swatch + label + counts
    c.rect(lx, ly, 16, 16, r, g, b)
    c.text(lx + 24, ly + 2, AXIS_SHORT[axis], 2, 51, 65, 85)
    c.text(lx + 24, ly + 24, `n=${pts.reduce((s, p) => s + p.n_runs, 0)}`, 1, 148, 163, 184)
    ly += 62
  }

  mkdirSync(dirname(outPath), { recursive: true })
  writeFileSync(outPath, c.toPng())
  return outPath
}
