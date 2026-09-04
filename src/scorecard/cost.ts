/**
 * cost.ts — ColdStart STEP 06: cost accounting for the scorecard.
 *
 * Solari bills per hour, and there is no SDK API to read a live credit balance or
 * the current $/hour rate. So this module does the most complete accounting that
 * is actually observable:
 *   - sandbox_seconds: wall time the variant sandbox VM existed (create -> kill).
 *   - browser_seconds: wall time the shared browser session was actively driving
 *     this variant (goto -> after the agent loop).
 *   - llm_calls / model_request_count: (lower-bound) number of model turns.
 *   - model_tokens_est: a documented token estimate (vision image + text).
 *   - estimated_billable_hours: the field Solari actually bills on.
 *
 * `credits` is intentionally `null` — there is no defensible $ conversion without
 * a published rate, so we report hours/seconds and label credits "not observable".
 * This is the honest envelope per DESIGN.md §5 and MASTER_PLAN Step 06 acceptance
 * ("cost accounting is complete") — we account for every second + call we can see,
 * and state plainly what we cannot.
 *
 * Security: nothing here reads or prints a key.
 */

import type { AxisKey, RunRecord } from "./build.ts"

// ---------------------------------------------------------------------------
// Token-estimation heuristic (documented; an estimate, not a metered value)
// ---------------------------------------------------------------------------

/** Fixed viewport the harness pins (DESIGN §3): 1280×800, PNG clip = viewport. */
export const TOKEN_VIEWPORT = { width: 1280, height: 800 }

/**
 * Image tokens for the vision model. Using the common OpenAI-compatible patch
 * heuristic `ceil(w*h / 750)` (≈ "low" fidelity). 1280*800 = 1,024,000 -> 1366.
 * This is an ESTIMATE — the endpoint does not return usage in model.ts.
 */
export function estimateImageTokens(width = TOKEN_VIEWPORT.width, height = TOKEN_VIEWPORT.height): number {
  return Math.ceil((width * height) / 750)
}

/**
 * Text tokens per call ≈ characters / 4 (rough tokens for system+user+history).
 * The instruction is ~250 chars and the system prompt is ~1400 chars, so we
 * budget a per-call text estimate. ESTIMATE only.
 */
export function estimateTextTokensPerCall(): number {
  return 420
}

/** Estimated output tokens per decision (a single JSON action + short rationale). */
export function estimateOutTokensPerCall(): number {
  return 42
}

export const COST_ESTIMATE_NOTE =
  "tokens are an estimate: image=ceil(w*h/750), text=~chars/4, out=~42/turn. " +
  "Solari credit balance + $/hour rate are NOT exposed by the SDK, so credits=null and " +
  "estimated_billable_hours=(sandbox_seconds+browser_seconds)/3600 is the observable cost."

export interface CostAggregate {
  /** True only when the per-run cost numbers are fully metered (false -> estimates). */
  metered: boolean
  total_sandbox_seconds: number
  total_browser_seconds: number
  total_llm_calls: number
  total_model_tokens_in: number
  total_model_tokens_out: number
  estimated_billable_hours: number
  /** Not observable via the SDK; null with a note. */
  credits: null
  by_variant: Record<string, { runs: number; sandbox_seconds: number; browser_seconds: number; llm_calls: number; model_tokens_in: number; model_tokens_out: number }>
  by_axis: Record<AxisKey, { runs: number; sandbox_seconds: number; browser_seconds: number; llm_calls: number; model_tokens_in: number; model_tokens_out: number }>
}

/** Aggregate per-run cost into the DESIGN §5 `cost` block (total + by_variant + by_axis). */
export function aggregateCost(runs: RunRecord[], axisKeys: AxisKey[]): CostAggregate {
  const byVariant: CostAggregate["by_variant"] = {}
  const byAxis: CostAggregate["by_axis"] = {} as CostAggregate["by_axis"]

  for (const k of axisKeys) byAxis[k] = { runs: 0, sandbox_seconds: 0, browser_seconds: 0, llm_calls: 0, model_tokens_in: 0, model_tokens_out: 0 }

  let ts = 0
  let tb = 0
  let tc = 0
  let ti = 0
  let to = 0

  for (const r of runs) {
    const c = r.cost
    ts += c.sandbox_seconds
    tb += c.browser_seconds
    tc += c.llm_calls
    ti += c.model_tokens_in
    to += c.model_tokens_out

    byVariant[r.variant_id] = {
      runs: (byVariant[r.variant_id]?.runs ?? 0) + 1,
      sandbox_seconds: c.sandbox_seconds,
      browser_seconds: c.browser_seconds,
      llm_calls: c.llm_calls,
      model_tokens_in: c.model_tokens_in,
      model_tokens_out: c.model_tokens_out,
    }

    // Attribute cost to every axis the variant perturbed (intensity > 0).
    for (const k of axisKeys) {
      const int = r.intensity_by_axis[k]
      if (int > 0) {
        byAxis[k].runs += 1
        byAxis[k].sandbox_seconds += c.sandbox_seconds
        byAxis[k].browser_seconds += c.browser_seconds
        byAxis[k].llm_calls += c.llm_calls
        byAxis[k].model_tokens_in += c.model_tokens_in
        byAxis[k].model_tokens_out += c.model_tokens_out
      }
    }
  }

  return {
    metered: false,
    total_sandbox_seconds: ts,
    total_browser_seconds: tb,
    total_llm_calls: tc,
    total_model_tokens_in: ti,
    total_model_tokens_out: to,
    estimated_billable_hours: (ts + tb) / 3600,
    credits: null,
    by_variant: byVariant,
    by_axis: byAxis,
  }
}
