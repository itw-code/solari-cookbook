/**
 * verifier.ts — ColdStart STEP 05: the independent ground-truth verifier.
 *
 * READ DESIGN.md §4 FIRST. This is the single place that decides whether the
 * task *actually* happened, by reading the variant app's SQLite ground-truth
 * record via the DB/files channel — NEVER the agent's narration, NEVER the page
 * DOM, NEVER the `done` claim.
 *
 * Two input modes:
 *   (a) verifyAgainstPath({ seed, dbPath })  — offline / re-runs / Mock fixtures.
 *       Opens a local `invoice.db` directly with node:sqlite. Deterministic.
 *   (b) verifyAgainstSandbox({ seed, sandbox, dbPath? }) — live runs. Reads the
 *       raw artifact bytes from the sandbox FILE channel (`sandbox.files.read`),
 *       so it never trusts the agent. Not exercised live in Step 05 but fully
 *       implemented + type-correct.
 *
 * Fail-closed: `task_completed` defaults to false. Any ambiguity — DB missing,
 * unreadable, not a SQLite DB, missing tables, zero rows, extra rows, no POSTED
 * row, unsanitized/garbage values — keeps it false. ONLY an unambiguous,
 * fully-matching, internally-consistent POSTED invoice flips it true.
 *
 * Evidence binding: `evidence_hash = sha256(<raw artifact bytes read>)`. Re-running
 * over the same artifact reproduces the identical hash AND the identical verdict.
 *
 * SECURITY: never reads/prints keys. No Solari key here. Reads only the artifact.
 *
 * NOTE: `DatabaseSync` is imported from `../sqlite.js` (a createRequire loader),
 * not directly from `node:sqlite`, because Vite/Vitest cannot statically
 * externalize the experimental `node:sqlite` builtin (see sqlite.ts).
 */

import { createHash } from "node:crypto"
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { DatabaseSync } from "../sqlite.js"
import type { Sandbox } from "@solarisdk/sdk"

import { deriveTaskSpec } from "../generate-variants/task-spec.js"
import {
  runChecks,
  type ActualItem,
  type ActualInvoiceRecord,
  type ActualSnapshot,
  type CheckResult,
  type FieldError,
} from "./checks.js"

// ---------------------------------------------------------------------------
// Public contract (DESIGN §4)
// ---------------------------------------------------------------------------

export interface VerifyResult {
  /** THE signal the scorecard uses. Fail-closed: false on any error/ambiguity. */
  task_completed: boolean
  field_errors: FieldError[]
  checks_run: CheckResult[]
  /** sha256 over the raw artifact bytes read via the channel. */
  evidence_hash: string
}

export interface VerifyAgainstPathInput {
  seed: number
  dbPath: string
}

export interface VerifyAgainstSandboxInput {
  seed: number
  /** A connected Solari `Sandbox` (from `@solarisdk/sdk`). */
  sandbox: Sandbox
  /** Guest DB path (default `/app/data/invoice.db` per DESIGN §1). */
  dbPath?: string
}

/** The app's fixed ground-truth artifact path inside a Solari sandbox. */
export const DEFAULT_DB_PATH = "/app/data/invoice.db"

// ---------------------------------------------------------------------------
// Input modes
// ---------------------------------------------------------------------------

/** Mode (a): open a local SQLite file directly. Offline + deterministic. */
export async function verifyAgainstPath(input: VerifyAgainstPathInput): Promise<VerifyResult> {
  let bytes: Uint8Array
  try {
    bytes = readFileSync(input.dbPath)
  } catch (e) {
    return noArtifact(`DB file unreadable at ${input.dbPath}: ${errText(e)}`)
  }
  return verifyFromBytes(input.seed, bytes)
}

/** Mode (b): read the live artifact via the sandbox FILE channel. Never trust the agent. */
export async function verifyAgainstSandbox(input: VerifyAgainstSandboxInput): Promise<VerifyResult> {
  const dbPath = input.dbPath ?? DEFAULT_DB_PATH
  try {
    // `sandbox.files.read` returns the raw DB file bytes — the same artifact a
    // re-run would read, and the exact bytes we sha256 for evidence binding.
    const bytes = await input.sandbox.files.read(dbPath)
    return verifyFromBytes(input.seed, Uint8Array.from(bytes))
  } catch (e) {
    return noArtifact(`sandbox DB unreadable at ${dbPath}: ${errText(e)}`)
  }
}

// ---------------------------------------------------------------------------
// Core: bytes -> verdict
// ---------------------------------------------------------------------------

function verifyFromBytes(seed: number, bytes: Uint8Array): VerifyResult {
  // Evidence binding FIRST: hash the raw artifact bytes we read (reproducible).
  const evidenceHash = sha256Hex(bytes)

  let snapshot: ActualSnapshot
  try {
    snapshot = parseDbSnapshot(bytes)
  } catch (e) {
    // Not a parseable, well-formed ColdStart artifact -> fail-closed.
    return failClosed(evidenceHash, parseErrorChecks(`artifact unparseable / unsanitized: ${errText(e)}`))
  }

  // Expected is RECOMPUTED from the seed — never trusted from the app or agent.
  const expected = deriveTaskSpec(seed).expected
  const { checks, errors } = runChecks(expected, snapshot)

  // Fail-closed: true only if EVERY check passed.
  const task_completed = checks.every((c) => c.passed)
  return { task_completed, field_errors: errors, checks_run: checks, evidence_hash: evidenceHash }
}

// ---------------------------------------------------------------------------
// Artifact parsing (reads the SQLite bytes into a normalized snapshot)
// ---------------------------------------------------------------------------

type Row = Record<string, unknown>

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/

function isValidIsoDate(s: string): boolean {
  if (!ISO_DATE.test(s)) return false
  return !Number.isNaN(new Date(`${s}T00:00:00Z`).getTime())
}

function rowInt(row: Row, key: string): number {
  const v = row[key]
  if (typeof v !== "number" || !Number.isInteger(v)) throw new Error(`${key} is not an integer: ${String(v)}`)
  return v
}

function rowStr(row: Row, key: string): string {
  const v = row[key]
  if (typeof v !== "string") throw new Error(`${key} is not a string: ${String(v)}`)
  return v
}

/**
 * Materialize the artifact bytes to a temp file and open with node:sqlite.
 * Any failure (not a SQLite DB, missing `invoices` table, malformed rows,
 * out-of-range / unsanitized values) throws and the caller fails closed.
 * The temp file is removed before returning. All queries are fixed-SQL
 * (no untrusted interpolation) — this is the "never unsanitized" guarantee.
 */
function parseDbSnapshot(bytes: Uint8Array): ActualSnapshot {
  const tmpDir = mkdtempSync(join(tmpdir(), "coldstart-verify-"))
  const tmpPath = join(tmpDir, "invoice.db")
  let db: DatabaseSync | null = null
  try {
    writeFileSync(tmpPath, bytes)
    db = new DatabaseSync(tmpPath, { readOnly: true })

    // Requiring these tables makes a swapped/garbage artifact fail closed.
    const invoiceRows = db.prepare("SELECT * FROM invoices ORDER BY id").all() as unknown as Row[]
    const itemRows = db.prepare("SELECT * FROM invoice_items ORDER BY invoice_id, position").all() as unknown as Row[]

    const invoices: ActualInvoiceRecord[] = invoiceRows.map(parseInvoiceRow)
    const itemsByInvoice = new Map<number, ActualItem[]>()
    for (const raw of itemRows) {
      const { invoice_id, item } = parseItemRow(raw)
      const arr = itemsByInvoice.get(invoice_id) ?? []
      arr.push(item)
      itemsByInvoice.set(invoice_id, arr)
    }

    // Referential integrity: every line item must point at a known invoice.
    const known = new Set(invoices.map((i) => i.id))
    for (const invoiceId of itemsByInvoice.keys()) {
      if (!known.has(invoiceId)) throw new Error(`invoice_items references unknown invoice_id=${invoiceId}`)
    }
    // Attach items; an invoice may legitimately have zero items only if malformed,
    // which C3/C1 will surface — we still parse it (fail-closed at the check layer).
    for (const inv of invoices) inv.items = itemsByInvoice.get(inv.id) ?? []

    return { invoices }
  } finally {
    try {
      db?.close()
    } catch {
      /* ignore */
    }
    try {
      rmSync(tmpDir, { recursive: true, force: true })
    } catch {
      /* ignore */
    }
  }
}

function parseInvoiceRow(row: Row): ActualInvoiceRecord {
  const id = rowInt(row, "id")
  const invoice_no = rowStr(row, "invoice_no")
  const customer = rowStr(row, "customer")
  const status = rowStr(row, "status")
  const subtotal_cents = rowInt(row, "subtotal_cents")
  const tax_cents = rowInt(row, "tax_cents")
  const total_cents = rowInt(row, "total_cents")
  const tax_rate_bps = rowInt(row, "tax_rate_bps")
  const invoice_date = rowStr(row, "invoice_date")
  const due_date = rowStr(row, "due_date")

  // Unsanitized / malformed row guards (fail-closed).
  if (!invoice_no) throw new Error("invoice_no is empty")
  if (!customer) throw new Error("customer is empty")
  if (status !== "DRAFT" && status !== "POSTED") throw new Error(`status is not DRAFT/POSTED: ${String(status)}`)
  if (subtotal_cents < 0 || tax_cents < 0 || total_cents < 0) throw new Error("negative money value")
  if (tax_rate_bps < 0 || tax_rate_bps > 10000) throw new Error(`tax_rate_bps out of range: ${tax_rate_bps}`)
  if (!isValidIsoDate(invoice_date)) throw new Error(`invoice_date not ISO yyyy-mm-dd: ${String(invoice_date)}`)
  if (!isValidIsoDate(due_date)) throw new Error(`due_date not ISO yyyy-mm-dd: ${String(due_date)}`)

  return {
    id,
    invoice_no,
    customer,
    status,
    subtotal_cents,
    tax_cents,
    total_cents,
    tax_rate_bps,
    invoice_date,
    due_date,
    items: [],
  }
}

function parseItemRow(row: Row): { invoice_id: number; item: ActualItem } {
  const invoice_id = rowInt(row, "invoice_id")
  const position = rowInt(row, "position")
  const description = rowStr(row, "description")
  const qty = rowInt(row, "qty")
  const unit_price_cents = rowInt(row, "unit_price_cents")
  const line_total_cents = rowInt(row, "line_total_cents")

  if (position <= 0) throw new Error(`position must be >= 1: ${position}`)
  if (!description) throw new Error("item description is empty")
  if (qty <= 0) throw new Error(`qty must be > 0: ${qty}`)
  if (unit_price_cents < 0) throw new Error(`negative unit_price_cents: ${unit_price_cents}`)
  if (line_total_cents < 0) throw new Error(`negative line_total_cents: ${line_total_cents}`)

  return {
    invoice_id,
    item: { position, description, qty, unit_price_cents, line_total_cents },
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function sha256Hex(bytes: Uint8Array): string {
  return createHash("sha256").update(bytes).digest("hex")
}

function errText(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

function failClosed(evidenceHash: string, checks: CheckResult[]): VerifyResult {
  // field_errors stays empty when we cannot diff anything (ambiguity / parse fail).
  return { task_completed: false, field_errors: [], checks_run: checks, evidence_hash: evidenceHash }
}

/** A deterministic "no artifact" result: hash the empty buffer so re-runs agree. */
function noArtifact(reason: string): VerifyResult {
  return failClosed(sha256Hex(new Uint8Array(0)), allChecksFailed(`artifact unavailable: ${reason}`))
}

/** All-of-C1-C7 failed with a shared reason (used when nothing read at all). */
function allChecksFailed(reason: string): CheckResult[] {
  return ["C1", "C2", "C3", "C4", "C5", "C6", "C7"].map((check) => ({ check, passed: false, detail: reason }))
}

/** C1-C7 failed with C1 carrying the specific parse/schema error. */
function parseErrorChecks(reason: string): CheckResult[] {
  return [
    { check: "C1", passed: false, detail: reason },
    ...["C2", "C3", "C4", "C5", "C6", "C7"].map((c) => ({ check: c, passed: false, detail: "not evaluated: artifact unparseable" })),
  ]
}
