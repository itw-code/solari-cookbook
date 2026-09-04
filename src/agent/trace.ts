/**
 * trace.ts — write JSON action traces to `artifacts/runs/<run_id>/trace.json`.
 *
 * The trace is the audit evidence: it records the task text, the screenshot that
 * drove each step, the action chosen, whether it executed OK, the rationale, and
 * the terminal status. It is written to the run directory, NOT stdout, and never
 * contains secrets (the preview URL token is redacted; the model key is never
 * written anywhere).
 */
import { mkdir, writeFile } from "node:fs/promises"
import type { Action } from "./action.ts"

export interface StepTraceRecord {
  step: number
  action: Action
  ok: boolean
  error?: string
  rationale?: string
  screenshot: string
}

export interface ActionTrace {
  run_id: string
  seed: number | null
  variant_id: string | null
  /** The natural-language task instruction given to the agent. */
  task: string
  status: string
  terminated_by: string
  steps_taken: number
  max_steps: number
  model: string | null
  /** Redacted preview base URL (gateway token masked). */
  base_url: string
  viewport: string
  final_title: string | null
  final_screenshot: string | null
  actions: StepTraceRecord[]
  error: string | null
  generated_at: string
}

/** Write `trace.json` into `runDir` and return the absolute path. */
export async function writeActionTrace(runDir: string, trace: ActionTrace): Promise<string> {
  await mkdir(runDir, { recursive: true })
  const file = `${runDir}/trace.json`
  await writeFile(file, JSON.stringify(trace, null, 2))
  return file
}
