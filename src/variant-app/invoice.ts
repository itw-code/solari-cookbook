/**
 * invoice.ts — domain logic for the Create-Invoice task app.
 *
 * Holds the deterministic arithmetic (subtotal / tax / total in cents), the
 * INV-YYYY-#### invoice number generator, and input validation. The variant
 * app (server.ts) and the generator's task-spec both use `computeTotals` so
 * there is a single source of truth for the money math.
 *
 * All money is stored in **integer cents** (per DESIGN.md §1); tax rate is
 * stored in **basis points** (800 = 8%).
 */

export interface LineItem {
  description: string
  qty: number
  unit_price_cents: number
}

export interface InvoiceTotals {
  subtotal_cents: number
  tax_cents: number
  total_cents: number
  tax_rate_bps: number
}

/**
 * Recompute totals from raw line-item columns. Tax is rounded to the nearest
 * cent (round-half-up) on the subtotal. This is the exact arithmetic the
 * verifier (Step 05, check C6) recomputes independently.
 */
export function computeTotals(items: readonly LineItem[], tax_rate_bps: number): InvoiceTotals {
  const subtotal_cents = items.reduce((sum, it) => sum + it.qty * it.unit_price_cents, 0)
  const tax_cents = Math.round((subtotal_cents * tax_rate_bps) / 10000)
  return { subtotal_cents, tax_cents, total_cents: subtotal_cents + tax_cents, tax_rate_bps }
}

/** Build the auto invoice number: INV-<year>-<4-digit seq>. */
export function makeInvoiceNo(year: number, seq: number): string {
  const yyyy = String(year).padStart(4, "0")
  return `INV-${yyyy}-${String(seq).padStart(4, "0")}`
}

/**
 * Raw, client-supplied form values (POST body). Field NAMES are the canonical
 * contract regardless of perturbation — perturbation only changes labels/order,
 * never the submitted field names.
 */
export interface InvoiceInput {
  customer: string
  invoice_date: string
  due_date: string
  tax_rate: string // percent, e.g. "8" or "8%"
  description: string
  qty: string
  unit_price: string // dollars, e.g. "120.00"
}

/** Parsed, validated, canonical invoice ready to persist. */
export interface ParsedInvoice {
  customer: string
  invoice_date: string
  due_date: string
  tax_rate_bps: number
  tax_rate_percent: number
  items: LineItem[]
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/

function isValidIsoDate(s: string): boolean {
  if (!ISO_DATE.test(s)) return false
  const d = new Date(`${s}T00:00:00Z`)
  return !Number.isNaN(d.getTime())
}

/** Parse + validate the submitted form. Never throws. Returns ok/errors. */
export function parseAndValidate(input: InvoiceInput): { ok: true; value: ParsedInvoice } | { ok: false; errors: string[] } {
  const errors: string[] = []

  const customer = (input.customer ?? "").trim()
  if (!customer) errors.push("customer is required")

  const invoice_date = (input.invoice_date ?? "").trim()
  if (!isValidIsoDate(invoice_date)) errors.push("invoice_date must be YYYY-MM-DD")

  const due_date = (input.due_date ?? "").trim()
  if (!isValidIsoDate(due_date)) errors.push("due_date must be YYYY-MM-DD")

  // tax_rate: accept "8", "8%", "8.0" → percent value.
  const taxClean = (input.tax_rate ?? "").replace("%", "").trim()
  const taxPercent = Number.parseFloat(taxClean)
  if (Number.isNaN(taxPercent)) errors.push("tax_rate must be a number")
  else if (taxPercent < 0 || taxPercent > 100) errors.push("tax_rate must be between 0 and 100")
  const tax_rate_bps = Number.isFinite(taxPercent) ? Math.round(taxPercent * 100) : 0

  const qty = Number.parseInt((input.qty ?? "").trim(), 10)
  if (!Number.isInteger(qty) || qty <= 0) errors.push("qty must be a positive integer")

  const unit_price_dollars = Number.parseFloat((input.unit_price ?? "").trim())
  if (Number.isNaN(unit_price_dollars)) errors.push("unit_price must be a number")
  else if (unit_price_dollars < 0) errors.push("unit_price must be >= 0")
  const unit_price_cents = Number.isFinite(unit_price_dollars) ? Math.round(unit_price_dollars * 100) : 0

  const description = (input.description ?? "").trim()
  if (!description) errors.push("description is required")

  if (errors.length > 0) return { ok: false, errors }

  const items: LineItem[] = [{ description, qty, unit_price_cents }]
  return {
    ok: true,
    value: {
      customer,
      invoice_date,
      due_date,
      tax_rate_bps,
      tax_rate_percent: taxPercent,
      items,
    },
  }
}
