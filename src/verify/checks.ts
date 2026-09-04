/**
 * checks.ts — ColdStart verifier (DESIGN.md §4): the pure C1–C7 checks.
 *
 * This module holds ONLY the comparison logic. It never touches the DB, the
 * filesystem, or any Solari channel. The verifier (`verifier.ts`) reads + parses
 * the artifact into an `ActualSnapshot` and hands it here; `runChecks` compares
 * that snapshot against the RECOMPUTED expected values (from `deriveTaskSpec(seed)`),
 * returning the per-check results and the field-level errors.
 *
 * Fail-closed is enforced by the consumer: `task_completed = every check passed`.
 * If there is anything ambiguous or any mismatch, a check flips to `passed:false`
 * and `task_completed` becomes false. This file only computes the comparison.
 *
 * Expected is the GROUND TRUTH — it is recomputed from the seed by the pure
 * `deriveTaskSpec` function, never taken from the app, the agent, or the page.
 */

import { computeTotals } from "../variant-app/invoice.js"
import type { TaskExpected } from "../generate-variants/task-spec.js"

// ---------------------------------------------------------------------------
// Verifier contract types (DESIGN §4)
// ---------------------------------------------------------------------------

export interface CheckResult {
  check: string
  passed: boolean
  detail: string
}

export interface FieldError {
  field: string
  expected: string
  actual: string
  severity: "critical" | "major" | "minor"
}

// ---------------------------------------------------------------------------
// Normalized "actual" snapshot (parsed from the DB by the verifier)
// ---------------------------------------------------------------------------

export interface ActualItem {
  position: number
  description: string
  qty: number
  unit_price_cents: number
  line_total_cents: number
}

export interface ActualInvoiceRecord {
  id: number
  invoice_no: string
  customer: string
  status: "DRAFT" | "POSTED"
  subtotal_cents: number
  tax_cents: number
  total_cents: number
  tax_rate_bps: number
  invoice_date: string
  due_date: string
  items: ActualItem[]
}

export interface ActualSnapshot {
  /** Every invoice row in the artifact, in id order (POSTED and DRAFT). */
  invoices: ActualInvoiceRecord[]
}

/** Canonical invoice-number shape (DESIGN C7). */
export const INVOICE_NO_RE = /^INV-\d{4}-\d{4}$/

const CRITICAL: FieldError["severity"] = "critical"

function fe(field: string, expected: string, actual: string, severity: FieldError["severity"] = CRITICAL): FieldError {
  return { field, expected, actual, severity }
}

function itemMatches(exp: TaskExpected["items"][number], act: ActualItem | undefined): boolean {
  return (
    act !== undefined &&
    act.description === exp.description &&
    act.qty === exp.qty &&
    act.unit_price_cents === exp.unit_price_cents
  )
}

/**
 * Evaluate C1–C7 against a parsed snapshot and the seed-derived expected values.
 *
 * Returns a CheckResult for EVERY check (so the scorecard always has a full
 * trace) and the field-level errors for the mismatches. When there is not
 * exactly one POSTED invoice (C1 fails), C2–C7 are reported as failed with a
 * "nothing to compare" detail and `field_errors` is left empty — there is no
 * single artifact to diff, and DIFFING NOTHING must not flip the task to true.
 */
export function runChecks(expected: TaskExpected, snapshot: ActualSnapshot): { checks: CheckResult[]; errors: FieldError[] } {
  const checks: CheckResult[] = []
  const errors: FieldError[] = []

  const posted = snapshot.invoices.filter((i) => i.status === "POSTED")

  // C1 — Existence: exactly one POSTED invoice row.
  const c1Passed = posted.length === 1
  checks.push({
    check: "C1",
    passed: c1Passed,
    detail: c1Passed
      ? `exactly one POSTED invoice (id=${posted[0]!.id})`
      : posted.length === 0
        ? `no POSTED invoice found (${snapshot.invoices.length} invoice(s) total)`
        : `found ${posted.length} POSTED invoices (expected exactly 1) — possible double-submit / cross-run contamination`,
  })

  if (!c1Passed) {
    // Without a unique POSTED row there is nothing to diff against expected.
    // C2–C7 cannot be evaluated against a single artifact and are fail-closed.
    const reason =
      posted.length === 0 ? "no POSTED invoice to evaluate against expected" : `ambiguous: ${posted.length} POSTED invoices`
    for (const c of ["C2", "C3", "C4", "C5", "C6", "C7"]) checks.push({ check: c, passed: false, detail: reason })
    return { checks, errors }
  }

  const inv = posted[0]!

  // C7 — invoice_no present, non-empty, unique, and matches ^INV-\d{4}-\d{4}$.
  // Uniqueness is checked across ALL rows (a duplicate on a DRAFT also fails it).
  const invoiceNos = snapshot.invoices.map((i) => i.invoice_no)
  const invoiceNoUnique = new Set(invoiceNos).size === invoiceNos.length
  const c7Format = INVOICE_NO_RE.test(inv.invoice_no)
  const c7Passed = c7Format && invoiceNoUnique
  checks.push({
    check: "C7",
    passed: c7Passed,
    detail: `invoice_no="${inv.invoice_no}" ${c7Format ? "matches" : "does NOT match"} ^INV-\\d{4}-\\d{4}$; unique=${invoiceNoUnique ? "yes" : "NO"}`,
  })
  if (!c7Format) errors.push(fe("invoice_no", `INV-YYYY-#### (${INVOICE_NO_RE.source})`, String(inv.invoice_no)))
  if (!invoiceNoUnique) errors.push(fe("invoice_no", `unique among ${invoiceNos.length} rows`, String(inv.invoice_no)))

  // C2 — customer.
  const c2Passed = inv.customer === expected.customer
  checks.push({ check: "C2", passed: c2Passed, detail: `customer "${inv.customer}" vs expected "${expected.customer}"` })
  if (!c2Passed) errors.push(fe("customer", expected.customer, inv.customer))

  // C3 — line items: count + each (description, qty, unit_price_cents) in order.
  const expItems = expected.items
  const actItems = inv.items
  const countOk = actItems.length === expItems.length
  const c3Passed = countOk && expItems.every((it, i) => itemMatches(it, actItems[i]))
  checks.push({
    check: "C3",
    passed: c3Passed,
    detail: `items count ${actItems.length} vs expected ${expItems.length}; in-order (description,qty,unit_price_cents) compared`,
  })
  if (!countOk) errors.push(fe("items.length", String(expItems.length), String(actItems.length)))
  const n = Math.min(actItems.length, expItems.length)
  for (let i = 0; i < n; i++) {
    const exp = expItems[i]!
    const act = actItems[i]!
    if (act.description !== exp.description) errors.push(fe(`items[${i}].description`, exp.description, act.description))
    if (act.qty !== exp.qty) errors.push(fe(`items[${i}].qty`, String(exp.qty), String(act.qty)))
    if (act.unit_price_cents !== exp.unit_price_cents) errors.push(fe(`items[${i}].unit_price_cents`, String(exp.unit_price_cents), String(act.unit_price_cents)))
  }

  // C4 — tax_rate_bps.
  const c4Passed = inv.tax_rate_bps === expected.tax_rate_bps
  checks.push({ check: "C4", passed: c4Passed, detail: `tax_rate_bps ${inv.tax_rate_bps} vs expected ${expected.tax_rate_bps}` })
  if (!c4Passed) errors.push(fe("tax_rate_bps", String(expected.tax_rate_bps), String(inv.tax_rate_bps)))

  // C5 — invoice_date + due_date.
  const dateOk = inv.invoice_date === expected.invoice_date && inv.due_date === expected.due_date
  checks.push({
    check: "C5",
    passed: dateOk,
    detail: `invoice_date ${inv.invoice_date} due_date ${inv.due_date} vs expected ${expected.invoice_date} / ${expected.due_date}`,
  })
  if (inv.invoice_date !== expected.invoice_date) errors.push(fe("invoice_date", expected.invoice_date, inv.invoice_date))
  if (inv.due_date !== expected.due_date) errors.push(fe("due_date", expected.due_date, inv.due_date))

  // C6 — total consistency: recompute subtotal/tax/total from the raw line-item
  // columns + tax_rate_bps and compare to the STORED values. Money math uses the
  // single source of truth `computeTotals` (same function the app + task-spec use).
  const totals = computeTotals(inv.items, inv.tax_rate_bps)
  const subtotalOk = totals.subtotal_cents === inv.subtotal_cents
  const taxOk = totals.tax_cents === inv.tax_cents
  const totalOk = totals.total_cents === inv.total_cents
  const c6Passed = subtotalOk && taxOk && totalOk
  checks.push({
    check: "C6",
    passed: c6Passed,
    detail: `stored subtotal=${inv.subtotal_cents} tax=${inv.tax_cents} total=${inv.total_cents} vs recomputed subtotal=${totals.subtotal_cents} tax=${totals.tax_cents} total=${totals.total_cents}`,
  })
  if (!subtotalOk) errors.push(fe("subtotal_cents", String(totals.subtotal_cents), String(inv.subtotal_cents)))
  if (!taxOk) errors.push(fe("tax_cents", String(totals.tax_cents), String(inv.tax_cents)))
  if (!totalOk) errors.push(fe("total_cents", String(totals.total_cents), String(inv.total_cents)))

  return { checks, errors }
}
