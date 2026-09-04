/**
 * agent-loop.spec.ts — MOCK-mode plumbing test for the vision-first agent loop.
 *
 * No network, no model key. A scripted stub `ModelCaller` (returns a fixed
 * Action sequence) drives a `MockPage` through `runAgentLoop`, and `MockSolari`
 * (Step 00 driver seam) proves the lifecycle closes cleanly. This proves the
 * loop LOGIC: screenshot → decide → execute → repeat, terminal conditions
 * (`done`/`abort`/`stuck`/`step_cap`), and trace emission.
 *
 * It also unit-tests the robust JSON extraction / action normalization in
 * model.ts (the one part the live model depends on and that must never rely on
 * the endpoint returning structured output).
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest"
import { mkdtemp, rm, readFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"

import { runAgentLoop, type PageHandle } from "../src/agent/loop.ts"
import type { Action } from "../src/agent/action.ts"
import type { ModelCaller, ModelDecision, ModelTurnInput } from "../src/agent/model.ts"
import { extractDecision, normalizeAction, parseJsonFlexibly } from "../src/agent/model.ts"
import { MockSolari } from "../src/solari/driver.ts"

// ---------------------------------------------------------------------------
// Stub model — returns a fixed, scripted action sequence.
// ---------------------------------------------------------------------------
class ScriptedModel implements ModelCaller {
  index = 0
  seenSteps: number[] = []
  seenHistoryLen: number[] = []
  constructor(private readonly seq: Action[]) {}

  async decide(input: ModelTurnInput): Promise<ModelDecision> {
    this.seenSteps.push(input.step)
    this.seenHistoryLen.push(input.history.length)
    if (this.index >= this.seq.length) throw new Error(`model called past scripted sequence (step ${input.step})`)
    const action = this.seq[this.index]!
    this.index++
    return { action, rationale: `plan step ${input.step}` }
  }
}

// ---------------------------------------------------------------------------
// Mock page — minimal structural Stand-In for the Playwright Page subset.
// ---------------------------------------------------------------------------
class MockPage implements PageHandle {
  calls: string[] = []
  private counter = 0
  private submitClicked = false
  private readonly changeOnClick: boolean
  private readonly submitCoords: [number, number]

  // The reducer drives mouse.click / keyboard.type / keyboard.press / goto (no DOM).
  readonly mouse = {
    click: async (x: number, y: number): Promise<void> => this.handleClick(x, y),
  }
  readonly keyboard = {
    type: async (text: string): Promise<void> => {
      this.calls.push(`type ${text}`)
    },
    press: async (keys: string): Promise<void> => {
      this.calls.push(`press ${keys}`)
    },
  }

  constructor(opts: { changeOnClick?: boolean; submitCoords?: [number, number] } = {}) {
    this.changeOnClick = opts.changeOnClick ?? true
    this.submitCoords = opts.submitCoords ?? [640, 720]
  }

  private async handleClick(x: number, y: number): Promise<void> {
    this.calls.push(`click ${x},${y}`)
    if (this.changeOnClick) this.counter++
    if (x === this.submitCoords[0] && y === this.submitCoords[1]) this.submitClicked = true
  }

  async goto(url: string): Promise<void> {
    this.calls.push(`goto ${url}`)
  }
  async screenshot(): Promise<Buffer> {
    const b = Buffer.alloc(4)
    b.writeUInt32BE(this.counter + 1000, 0)
    return b
  }
  async title(): Promise<string> {
    return this.submitClicked ? "Invoice Created" : "Create Invoice"
  }
  async evaluate<A, R>(_fn: (arg: A) => R, _arg: A): Promise<R> {
    // No grounding in the mock: snapToInteractive falls back to raw coordinates.
    return null as unknown as R
  }
}

const TASK = `Open the billing app and create an invoice for customer "ACMECORP" ... report done.`

const BASELINE_SEQUENCE: Action[] = [
  { kind: "click", x: 400, y: 200 },
  { kind: "type", text: "ACMECORP" },
  { kind: "click", x: 400, y: 260 },
  { kind: "type", text: "2026-10-01" },
  { kind: "click", x: 400, y: 320 },
  { kind: "type", text: "2026-10-31" },
  { kind: "click", x: 400, y: 380 },
  { kind: "type", text: "8" },
  { kind: "click", x: 400, y: 460 },
  { kind: "type", text: "Consulting" },
  { kind: "click", x: 400, y: 520 },
  { kind: "type", text: "3" },
  { kind: "click", x: 400, y: 580 },
  { kind: "type", text: "120.00" },
  { kind: "click", x: 640, y: 720 }, // Submit
  { kind: "done" },
]

let runDir = ""
beforeEach(async () => {
  runDir = await mkdtemp(join(tmpdir(), "coldstart-agent-"))
})
afterEach(async () => {
  await rm(runDir, { recursive: true, force: true })
})

describe("runAgentLoop (MOCK), no network / no model key", () => {
  it("completes the scripted baseline and emits a done trace", async () => {
    const page = new MockPage({ submitCoords: [640, 720] })
    const model = new ScriptedModel(BASELINE_SEQUENCE)

    const result = await runAgentLoop({
      page,
      model,
      baseUrl: "http://preview.solari.test?pt_token=abcdef123456",
      task: TASK,
      runDir,
      runId: "r_t_s0",
      seed: 0,
      variantId: "inv__s0__P1:0__P2:0__P3:0__P4:0__P5:0",
      maxSteps: 20,
      viewport: { width: 1280, height: 800 },
    })

    expect(result.status).toBe("done")
    expect(result.terminatedBy).toBe("done")
    expect(result.stepsTaken).toBe(BASELINE_SEQUENCE.length)

    // The model received a strictly increasing step counter and growing history.
    expect(model.seenSteps).toEqual(BASELINE_SEQUENCE.map((_, i) => i + 1))
    expect(model.seenHistoryLen[0]).toBe(0)
    expect(model.seenHistoryLen[1]).toBe(1)

    // Final title reflects having submitted (does not rely on DOM — the page merely
    // reports its own title, which the loop captures as evidence, never feeds the model).
    expect(result.finalTitle).toBe("Invoice Created")

    // The trace was written with the frame + actions.
    const trace = JSON.parse(await readFile(join(runDir, "trace.json"), "utf8"))
    expect(trace.terminated_by).toBe("done")
    expect(trace.task).toBe(TASK)
    expect(trace.steps_taken).toBe(BASELINE_SEQUENCE.length)
    expect(trace.actions).toHaveLength(BASELINE_SEQUENCE.length)
    expect(trace.actions[0].action.kind).toBe("click")
    expect(trace.actions[0].screenshot).toBe("step-01.png")
    // The gateway token must be redacted in the trace.
    expect(trace.base_url).not.toContain("abcdef123456")

    // Per-step screenshots are the evidence that each decision came from pixels.
    const fs = await import("node:fs")
    expect(fs.existsSync(join(runDir, "step-01.png"))).toBe(true)
    expect(fs.existsSync(join(runDir, "final.png"))).toBe(true)

    // The loop drove the browser via click/type only (no locator/innerText).
    expect(page.calls[0]).toBe("click 400,200")
    expect(page.calls[1]).toBe("type ACMECORP")
  })

  it("stops on abort", async () => {
    const page = new MockPage()
    const model = new ScriptedModel([{ kind: "click", x: 100, y: 100 }, { kind: "abort", reason: "lost" }])
    const result = await runAgentLoop({
      page,
      model,
      baseUrl: "http://preview.solari.test",
      task: TASK,
      runDir,
      runId: "r_abort_s0",
      maxSteps: 10,
    })
    expect(result.status).toBe("aborted")
    expect(result.stepsTaken).toBe(2)
  })

  it("detects stuck on 3 identical clicks with no page change", async () => {
    const page = new MockPage({ changeOnClick: false }) // clicks do not change the view
    const seq: Action[] = Array.from({ length: 6 }, () => ({ kind: "click", x: 120, y: 120 }))
    const model = new ScriptedModel(seq)
    const result = await runAgentLoop({
      page,
      model,
      baseUrl: "http://preview.solari.test",
      task: TASK,
      runDir,
      runId: "r_stuck_s0",
      maxSteps: 10,
    })
    expect(result.status).toBe("stuck")
    expect(result.stepsTaken).toBeLessThan(seq.length)
  })

  it("hits the step cap when the model never terminates", async () => {
    const page = new MockPage() // page changes each click
    const loop = (n: number): Action[] => Array.from({ length: n }, (_, i) => ({ kind: "click", x: 200 + i, y: 300 }))
    const model = new ScriptedModel(loop(20))
    const result = await runAgentLoop({
      page,
      model,
      baseUrl: "http://preview.solari.test",
      task: TASK,
      runDir,
      runId: "r_cap_s0",
      maxSteps: 5,
    })
    expect(result.status).toBe("step_cap")
    expect(result.stepsTaken).toBe(5)
  })
})

describe("MockSolari driver seam", () => {
  it("createSandbox + shutdown close cleanly (no throw)", async () => {
    const driver = new MockSolari()
    const sandbox = await driver.createSandbox()
    expect(sandbox).toBeDefined()
    await expect(driver.shutdown()).resolves.toBeUndefined()
  })
})

describe("model.ts robust JSON extraction (no network)", () => {
  it("parses a bare JSON envelope", () => {
    const d = extractDecision('{"action":{"kind":"click","x":123,"y":456},"rationale":"hi"}')
    expect(d.action).toEqual({ kind: "click", x: 123, y: 456 })
    expect(d.rationale).toBe("hi")
  })

  it("recovers JSON buried in prose / code fences", () => {
    const content = 'Here you go:\n```json\n{"action":{"kind":"type","text":"ACMECORP"}}\n```'
    const d = extractDecision(content)
    expect(d.action).toEqual({ kind: "type", text: "ACMECORP" })
  })

  it("normalizes number coercion + unknown values", () => {
    expect(normalizeAction({ kind: "click", x: "640", y: "720.6" })).toEqual({ kind: "click", x: 640, y: 721 })
    expect(normalizeAction({ kind: "done" })).toEqual({ kind: "done" })
    expect(() => normalizeAction({ kind: "hover" })).toThrow()
  })

  it("rejects a non-object / missing action", () => {
    expect(() => parseJsonFlexibly("not json one bit")).toThrow()
    expect(() => extractDecision('{"rationale":"no action"}')).toThrow()
  })
})
