/**
 * task-spec.ts — seed → (natural-language task instruction + expected values).
 *
 * The harness renders `instruction` to the agent. The verifier (Step 05)
 * RECOMPUTES `expected` from the seed by this same pure function — it never
 * trusts the app or the agent's narration (DESIGN.md §1, §4).
 *
 * The instruction deliberately does NOT contain the seed or any axis
 * intensities (the agent must never see them, DESIGN.md §3). It only tells the
 * agent WHICH concrete invoice to create.
 */

import { deriveStream, pickIntIn, pick } from "./prng.js"
import { computeTotals } from "../variant-app/invoice.js"

export interface ExpectedLineItem {
  description: string
  qty: number
  unit_price_cents: number
}

export interface TaskExpected {
  customer: string
  invoice_date: string // yyyy-mm-dd
  due_date: string // yyyy-mm-dd
  tax_rate_bps: number
  items: ExpectedLineItem[]
  subtotal_cents: number
  tax_cents: number
  total_cents: number
}

export interface TaskSpec {
  seed: number
  instruction: string
  expected: TaskExpected
}

const CUSTOMERS = ["ACMECORP", "GLOBEX", "INITECH", "UMBRELLA", "STARK", "WAYNE", "HOOLI", "VINYL"]
const DESCRIPTIONS = ["Consulting", "Design Services", "Development", "Maintenance", "Licensing", "Support", "Training", "Setup Fees"]
const TAX_RATES_BPS = [750, 800, 1000, 1250, 1500, 1825, 2100]

/** Format integer cents as a dollars string: 12000 -> "$120.00". */
export function formatMoney(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`
}

/** Format basis points as a percent string: 800 -> "8", 750 -> "7.5". */
export function formatPercentBps(bps: number): string {
  const pct = bps / 100
  return Number.isInteger(pct) ? String(pct) : pct.toFixed(2)
}

/** Add `days` to a YYYY-MM-DD date using UTC arithmetic (TZ-safe). */
function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

/** Pure function: seed -> task spec (instruction + expected values). */
export function deriveTaskSpec(seed: number): TaskSpec {
  // Baseline (seed=0) is the canonical example from DESIGN.md §1.
  if (seed === 0) {
    const items: ExpectedLineItem[] = [{ description: "Consulting", qty: 3, unit_price_cents: 12000 }]
    const totals = computeTotals(items, 800)
    return {
      seed,
      instruction: makeInstruction("ACMECORP", items, 800, "2026-10-01", "2026-10-31"),
      expected: {
        customer: "ACMECORP",
        invoice_date: "2026-10-01",
        due_date: "2026-10-31",
        items,
        ...totals,
      },
    }
  }

  const custStream = deriveStream(seed, "task_customer")
  const itemStream = deriveStream(seed, "task_items")
  const dateStream = deriveStream(seed, "task_dates")
  const taxStream = deriveStream(seed, "task_tax")

  const customer = pick(custStream, CUSTOMERS)
  const description = pick(itemStream, DESCRIPTIONS)
  const qty = pickIntIn(itemStream, 1, 5)
  const unit_price_dollars = pickIntIn(itemStream, 20, 500)
  const unit_price_cents = unit_price_dollars * 100
  const items: ExpectedLineItem[] = [{ description, qty, unit_price_cents }]

  const tax_rate_bps = pick(taxStream, TAX_RATES_BPS)

  const invoiceDate = addDays("2026-01-01", pickIntIn(dateStream, 0, 300))
  const dueDate = addDays(invoiceDate, pickIntIn(dateStream, 15, 45))

  const totals = computeTotals(items, tax_rate_bps)
  return {
    seed,
    instruction: makeInstruction(customer, items, tax_rate_bps, invoiceDate, dueDate),
    expected: {
      customer,
      invoice_date: invoiceDate,
      due_date: dueDate,
      items,
      ...totals,
    },
  }
}

function makeInstruction(customer: string, items: ExpectedLineItem[], tax_rate_bps: number, invoiceDate: string, dueDate: string): string {
  const line = items[0]!
  const money = formatMoney(line.unit_price_cents)
  const tax = formatPercentBps(tax_rate_bps)
  return (
    `Open the billing app and create an invoice for customer "${customer}" ` +
    `with one line item: description "${line.description}", qty ${line.qty}, unit price ${money}, ` +
    `tax rate ${tax}%, invoice date ${invoiceDate}, due date ${dueDate}. ` +
    `Leave everything else at its default. Submit and confirm the invoice is created, then report done.`
  )
}
