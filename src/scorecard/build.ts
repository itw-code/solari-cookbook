/**
 * build.ts — ColdStart STEP 06: the scorecard builder + schema (DESIGN.md §5).
 *
 * `buildScorecard` turns an array of `RunRecord`s (one per variant run, each with
 * the agent outcome + the Step 05 verifier verdict) into the full DESIGN §5
 * `scorecard.json` object, then `writeScorecard` persists it.
 *
 * SUCCESS IS DEFINED EXACTLY (DESIGN §5): a variant is a SUCCESS iff
 *   outcome.status === "ok"  AND  verifier.task_completed === true.
 * `done` is only a self-report; the verifier decides. If the agent completes but
 * the verifier disagrees, it is `verifier_fail`. If the agent never finishes, the
 * honest terminal status (stuck / step_cap / aborted) is recorded. We do NOT hide
 * a perturbed-variant failure — that IS the generalization signal.
 *
 * Security: no keys here. URLs in `session` are redacted (token masked) before
 * being written; traces redact already.
 */

import { mkdir, writeFile } from "node:fs/promises"
import { dirname } from "node:path"
import { aggregateCost, COST_ESTIMATE_NOTE, type CostAggregate } from "./cost.ts"
import { generalizationCurve, successByAxis, successByPoint, whereItBreaks } from "./curve.ts"

// ---------------------------------------------------------------------------
// Axis vocabulary (matches variants.json intensity_by_axis keys)
// ---------------------------------------------------------------------------

export type AxisKey = "P1_relabel" | "P2_structure" | "P3_field_order" | "P4_nav_order" | "P5_theme"
export const AXIS_KEYS: AxisKey[] = ["P1_relabel", "P2_structure", "P3_field_order", "P4_nav_order", "P5_theme"]

export const AXIS_LABEL: Record<AxisKey, string> = {
  P1_relabel: "Semantic relabeling",
  P2_structure: "Structure / flow reorder",
  P3_field_order: "Field order & density",
  P4_nav_order: "Navigation order",
  P5_theme: "Theme / CSS skin",
}

// ---------------------------------------------------------------------------
// Verifier/check shapes (re-exported so the scorecard is self-describing)
// ---------------------------------------------------------------------------

export interface FieldError {
  field: string
  expected: string
  actual: string
  severity: "critical" | "major" | "minor"
}
export interface CheckResult {
  check: string
  passed: boolean
  detail: string
}

// ---------------------------------------------------------------------------
// Per-run record (DESIGN §5 `runs[i]`)
// ---------------------------------------------------------------------------

export interface RunCost {
  credits: number | null
  hours: number
  sandbox_seconds: number
  browser_seconds: number
  model_tokens_in: number
  model_tokens_out: number
  model_request_count: number
  /** Number of model turns (one per step; an ESTIMATE of HTTP calls). */
  llm_calls: number
}

export interface RunRecord {
  run_id: string
  variant_id: string
  seed: number
  intensity_by_axis: Record<AxisKey, number>
  agent: {
    model: string
    steps_taken: number
    max_steps: number
    terminated_by: string // "done" | "abort" | "stuck" | "step_cap"
    status: string // "ok"|"verifier_fail"|"stuck"|"step_cap"|"aborted"
    error?: string | null
  }
  outcome: {
    status: string
    task_completed: boolean
    action_trace_path: string
    verifier: {
      task_completed: boolean
      field_errors: FieldError[]
      checks_run: CheckResult[]
      evidence_hash: string
    }
  }
  session: {
    replay_url: string | null
    recording_id: string | null
    sandbox_id: string | null
    snapshot_id: string | null
    fixture_path: string | null
  }
  cost: RunCost
}

// ---------------------------------------------------------------------------
// Scorecard
// ---------------------------------------------------------------------------

export interface GeneralizationPoint {
  axis: AxisKey
  intensity: number
  success_rate: number
  n_runs: number
}

export interface BreakEntry {
  axis: AxisKey
  intensity: number
  variant_id: string
  failure_mode: string
}

export interface ScorecardConfig {
  max_steps: number
  viewport: string
  n_runs_per_point: number
  mode: "LIVE" | "MOCK"
}

export interface Scorecard {
  schema_version: string
  generated_at: string
  task_app: string
  config: ScorecardConfig
  variants: Array<{ variant_id: string; seed: number; intensity_by_axis: Record<AxisKey, number> }>
  runs: RunRecord[]
  success_by_variant: Record<string, number>
  /** Success rate per (axis,intensity) point, e.g. "P2_structure:3" -> 0.50. */
  success_by_point: Record<string, number>
  success_by_axis: Record<AxisKey, number>
  generalization_curve: GeneralizationPoint[]
  cost: CostAggregate & { note: string }
  where_it_breaks: BreakEntry[]
}

export interface BuildInput {
  runs: RunRecord[]
  config: ScorecardConfig
}

/** True precisely when a run is a computed SUCCESS (agent ok AND verifier true). */
export function isSuccess(run: RunRecord): boolean {
  return run.agent.status === "ok" && run.outcome.verifier.task_completed === true
}

/**
 * Build the DESIGN §5 scorecard from the per-run evidence.
 * `variants` is derived from the runs (one profile per run_id).
 */
export function buildScorecard(input: BuildInput): Scorecard {
  const runs = input.runs
  const variants = runs.map((r) => ({ variant_id: r.variant_id, seed: r.seed, intensity_by_axis: r.intensity_by_axis }))

  // Per-variant success RATE (successes / runs for that variant_id). With n>1 per
  // variant this must aggregate, not overwrite, so a 1-of-2 point reads 0.5.
  const variantTally: Record<string, { succ: number; total: number }> = {}
  for (const r of runs) {
    const slot = variantTally[r.variant_id] ?? { succ: 0, total: 0 }
    slot.total += 1
    if (isSuccess(r)) slot.succ += 1
    variantTally[r.variant_id] = slot
  }
  const successByVariant: Record<string, number> = {}
  for (const [k, v] of Object.entries(variantTally)) successByVariant[k] = v.succ / v.total

  const cost = aggregateCost(runs, AXIS_KEYS)

  return {
    schema_version: "1.0",
    generated_at: new Date().toISOString(),
    task_app: "create-invoice",
    config: input.config,
    variants,
    runs: runs.map(redactRunUrls),
    success_by_variant: successByVariant,
    success_by_point: successByPoint(runs),
    success_by_axis: successByAxis(runs),
    generalization_curve: generalizationCurve(runs),
    cost: { ...cost, note: COST_ESTIMATE_NOTE },
    where_it_breaks: whereItBreaks(runs),
  }
}

/** Mask any long query param (the preview gateway token) so the artifact is secret-free. */
function redactRunUrls(run: RunRecord): RunRecord {
  return {
    ...run,
    session: { ...run.session, replay_url: run.session.replay_url ? redactUrl(run.session.replay_url) : null },
    cost: { ...run.cost, credits: null },
  }
}

function redactUrl(url: string): string {
  try {
    const u = new URL(url)
    const mask = (v: string): string => (/[A-Za-z0-9_-]{8,}/.test(v) ? "*".repeat(Math.min(12, v.length)) : v)
    u.search = u.search ? "?" + [...u.searchParams.entries()].map(([k, v]) => `${k}=${mask(v)}`).join("&") : ""
    return `${u.protocol}//${u.host}${u.pathname}${u.search}`
  } catch {
    return "<unparseable-url>"
  }
}

/** Write the scorecard JSON to `path`. */
export async function writeScorecard(path: string, scorecard: Scorecard): Promise<string> {
  await mkdir(dirname(path), { recursive: true })
  await writeFile(path, JSON.stringify(scorecard, null, 2))
  return path
}
