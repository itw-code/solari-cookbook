/**
 * db.ts — SQLite ground-truth store for the Create-Invoice task app.
 *
 * Uses Node's built-in `node:sqlite` (DatabaseSync) — zero third-party runtime
 * deps (DESIGN.md §1). `ensureSchema()` creates the invoice tables and runs on
 * every fork boot so each variant sandbox starts with an EMPTY DB.
 *
 * The DB file path comes from the env var `DB_PATH` (default `/app/data/invoice.db`
 * for the Solari sandbox). To run locally on Windows set `DB_PATH=./data/invoice.db`.
 */

import { mkdirSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { DatabaseSync } from "../sqlite.js"
import { computeTotals, makeInvoiceNo, type ParsedInvoice } from "./invoice.js"

export const DEFAULT_DB_PATH = "/app/data/invoice.db"

export interface Invoice {
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
  created_at: string
}

export interface InvoiceItem {
  id: number
  invoice_id: number
  position: number
  description: string
  qty: number
  unit_price_cents: number
  line_total_cents: number
}

/** Resolve the DB path from the environment (DB_PATH) with the sandbox default. */
export function resolveDbPath(): string {
  const p = process.env.DB_PATH ?? DEFAULT_DB_PATH
  return p.startsWith("/") ? p : resolve(p)
}

/** Open (creating parent dirs if needed) the SQLite database. */
export function openDb(dbPath: string): DatabaseSync {
  const dir = dirname(dbPath)
  if (dir && dir !== ".") mkdirSync(dir, { recursive: true })
  return new DatabaseSync(dbPath)
}

/** Create the invoice schema. Idempotent; runs on every boot. */
export function ensureSchema(db: DatabaseSync): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS invoices (
      id             INTEGER PRIMARY KEY AUTOINCREMENT,
      invoice_no     TEXT    NOT NULL UNIQUE,
      customer       TEXT    NOT NULL,
      status         TEXT    NOT NULL CHECK (status IN ('DRAFT','POSTED')),
      subtotal_cents INTEGER NOT NULL,
      tax_cents      INTEGER NOT NULL,
      total_cents    INTEGER NOT NULL,
      tax_rate_bps   INTEGER NOT NULL,
      invoice_date   TEXT    NOT NULL,
      due_date       TEXT    NOT NULL,
      created_at     TEXT    NOT NULL
    );

    CREATE TABLE IF NOT EXISTS invoice_items (
      id               INTEGER PRIMARY KEY AUTOINCREMENT,
      invoice_id       INTEGER NOT NULL REFERENCES invoices(id),
      position         INTEGER NOT NULL,
      description      TEXT    NOT NULL,
      qty              INTEGER NOT NULL CHECK (qty > 0),
      unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents >= 0),
      line_total_cents INTEGER NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice ON invoice_items(invoice_id);
  `)
}

export interface CreatedInvoice {
  id: number
  invoice_no: string
}

/**
 * Persist a parsed invoice in a transaction: insert the invoice with status
 * POSTED, assign INV-YYYY-####, insert the line items. Throws on failure
 * (caller rolls back). Recomputed totals are stored (never trusted later).
 */
export function createInvoice(db: DatabaseSync, input: ParsedInvoice): CreatedInvoice {
  const totals = computeTotals(input.items, input.tax_rate_bps)
  const year = new Date(`${input.invoice_date}T00:00:00Z`).getUTCFullYear()
  db.exec("BEGIN")
  try {
    const countRow = db
      .prepare("SELECT COUNT(*) AS c FROM invoices WHERE invoice_no LIKE ?")
      .get(`INV-${year}-%`) as { c: number }
    const seq = countRow.c + 1
    const invoice_no = makeInvoiceNo(year, seq)
    const created_at = new Date().toISOString()

    const res = db
      .prepare(
        `INSERT INTO invoices
           (invoice_no, customer, status, subtotal_cents, tax_cents, total_cents,
            tax_rate_bps, invoice_date, due_date, created_at)
         VALUES (?,?,?,?,?,?,?,?,?,?)`,
      )
      .run(
        invoice_no,
        input.customer,
        "POSTED",
        totals.subtotal_cents,
        totals.tax_cents,
        totals.total_cents,
        totals.tax_rate_bps,
        input.invoice_date,
        input.due_date,
        created_at,
      )
    const invoiceId = Number(res.lastInsertRowid)

    for (const [index, item] of input.items.entries()) {
      const line_total_cents = item.qty * item.unit_price_cents
      db.prepare(
        `INSERT INTO invoice_items
           (invoice_id, position, description, qty, unit_price_cents, line_total_cents)
         VALUES (?,?,?,?,?,?)`,
      ).run(invoiceId, index + 1, item.description, item.qty, item.unit_price_cents, line_total_cents)
    }

    db.exec("COMMIT")
    return { id: invoiceId, invoice_no }
  } catch (err) {
    db.exec("ROLLBACK")
    throw err
  }
}

/** Load one invoice row (or null). */
export function getInvoice(db: DatabaseSync, id: number): Invoice | null {
  const row = db.prepare("SELECT * FROM invoices WHERE id = ?").get(id) as Invoice | undefined
  return row ?? null
}

/** Load all line items for an invoice, in position order. */
export function getInvoiceItems(db: DatabaseSync, invoiceId: number): InvoiceItem[] {
  return db
    .prepare("SELECT * FROM invoice_items WHERE invoice_id = ? ORDER BY position")
    .all(invoiceId) as unknown as InvoiceItem[]
}

/** List invoices (newest first) for the list page. */
export function listInvoices(db: DatabaseSync): Invoice[] {
  return db.prepare("SELECT * FROM invoices ORDER BY id DESC").all() as unknown as Invoice[]
}
