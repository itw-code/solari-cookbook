/**
 * verifier.spec.ts — ColdStart STEP 05: ground-truth verifier tests.
 *
 * Proves the DESIGN §4 contract: the verifier is INDEPENDENT (recomputes expected
 * from the seed, reads the DB channel, never trusts the agent) and FAIL-CLOSED
 * (task_completed stays false on any ambiguity / mismatch).
 *
 * Fixtures are built PROGRAMMATICALLY with node:sqlite (same schema as the
 * variant app) so the tests are fully offline — no network, no Solari key.
 *
 * Required negatives: NEG-1 empty, NEG-2 wrong values, NEG-3 draft-only,
 * NEG-4 cross-run / double-POSTED. Plus a positive `seed=0` case and additional
 * fail-closed edges (missing file, corrupt artifact, sandbox channel failure).
 */

import { describe, it, expect, afterEach } from "vitest"
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import type { Sandbox } from "@solarisdk/sdk"

import { verifyAgainstPath, verifyAgainstSandbox } from "../src/verify/verifier.js"
import { createInvoice, ensureSchema, openDb } from "../src/variant-app/db.js"
import type { ParsedInvoice } from "../src/variant-app/invoice.js"
import { deriveTaskSpec } from "../src/generate-variants/task-spec.js"

// ---------------------------------------------------------------------------
// Fixture helpers (all offline, temp-dir based)
// ---------------------------------------------------------------------------

const tmpDirs: string[] = []

function freshDbPath(): string {
  const dir = mkdtempSync(join(tmpdir(), "coldstart-verify-"))
  tmpDirs.push(dir)
  return join(dir, "invoice.db")
}

afterEach(() => {
  for (const d of tmpDirs.splice(0)) {
    try {
      rmSync(d, { recursive: true, force: true })
    } catch {
      /* ignore */
    }
  }
})

/** Build a POSTED invoice exactly as the app would (createInvoice). */
function seedPosted(dbPath: string, parsed: ParsedInvoice): void {
  const db = openDb(dbPath)
  ensureSchema(db)
  createInvoice(db, parsed)
  db.close()
}

interface RawItem {
  description: string
  qty: number
  unit_price_cents: number
  line_total_cents: number
}

interface RawInvoice {
  invoice_no: string
  customer: string
  status: "DRAFT" | "POSTED"
  invoice_date: string
  due_date: string
  tax_rate_bps: number
  subtotal_cents: number
  tax_cents: number
  total_cents: number
  items: RawItem[]
}

/** Insert a RAW invoice row (for cases the app's createInvoice can't produce). */
function insertRaw(dbPath: string, inv: RawInvoice): void {
  const db = openDb(dbPath)
  ensureSchema(db)
  const created_at = new Date().toISOString()
  const res = db
    .prepare(
      `INSERT INTO invoices
         (invoice_no, customer, status, subtotal_cents, tax_cents, total_cents,
          tax_rate_bps, invoice_date, due_date, created_at)
       VALUES (?,?,?,?,?,?,?,?,?,?)`,
    )
    .run(
      inv.invoice_no,
      inv.customer,
      inv.status,
      inv.subtotal_cents,
      inv.tax_cents,
      inv.total_cents,
      inv.tax_rate_bps,
      inv.invoice_date,
      inv.due_date,
      created_at,
    )
  const invoiceId = Number(res.lastInsertRowid)
  inv.items.forEach((it, i) => {
    db.prepare(
      `INSERT INTO invoice_items
         (invoice_id, position, description, qty, unit_price_cents, line_total_cents)
       VALUES (?,?,?,?,?,?)`,
    ).run(invoiceId, i + 1, it.description, it.qty, it.unit_price_cents, it.line_total_cents)
  })
  db.close()
}

/** A minimal structural stand-in for a Solari Sandbox: only the FILE channel. */
function mockSandbox(bytes: Uint8Array): Sandbox {
  return { files: { read: async () => bytes } } as unknown as Sandbox
}

// ---------------------------------------------------------------------------
// Seed 0 baseline (canonical example from DESIGN §1)
// ---------------------------------------------------------------------------

const spec0 = deriveTaskSpec(0)
const exp0 = spec0.expected

const parsed0: ParsedInvoice = {
  customer: exp0.customer,
  invoice_date: exp0.invoice_date,
  due_date: exp0.due_date,
  tax_rate_bps: exp0.tax_rate_bps,
  tax_rate_percent: exp0.tax_rate_bps / 100,
  items: exp0.items,
}

// ---------------------------------------------------------------------------
describe("verifyAgainstPath — POSITIVE: correct POSTED invoice", () => {
  it("seed=0 with the exact expected row -> task_completed:true, totals match", async () => {
    const dbPath = freshDbPath()
    seedPosted(dbPath, parsed0)

    const res = await verifyAgainstPath({ seed: 0, dbPath })

    expect(res.task_completed).toBe(true)
    expect(res.field_errors).toEqual([])
    expect(res.checks_run.every((c) => c.passed)).toBe(true)
    expect(res.checks_run).toHaveLength(7) // C1..C7

    // The recomputed expected totals are the ground truth (seed=0 canonical).
    expect(exp0.subtotal_cents).toBe(36000)
    expect(exp0.tax_cents).toBe(2880)
    expect(exp0.total_cents).toBe(38880)

    // The artifact's recomputed totals agree with expected (C6 passes).
    const c6 = res.checks_run.find((c) => c.check === "C6")
    expect(c6?.passed).toBe(true)
    expect(c6?.detail).toContain("stored subtotal=36000 tax=2880 total=38880")

    // evidence_hash is a 64-char sha256.
    expect(res.evidence_hash).toMatch(/^[0-9a-f]{64}$/)
  })

  it("re-running the verifier on the same stored DB reproduces the verdict + hash", async () => {
    const dbPath = freshDbPath()
    seedPosted(dbPath, parsed0)

    const r1 = await verifyAgainstPath({ seed: 0, dbPath })
    const r2 = await verifyAgainstPath({ seed: 0, dbPath })

    expect(r1).toEqual(r2)
    expect(r1.task_completed).toBe(true)
    expect(r1.evidence_hash).toBe(r2.evidence_hash)
  })
})

// ---------------------------------------------------------------------------
describe("verifyAgainstPath — NEGATIVE (fail-closed)", () => {
  it("NEG-1 · empty DB (no invoices) -> false; C1 fails; field_errors empty", async () => {
    const dbPath = freshDbPath()
    const db = openDb(dbPath)
    ensureSchema(db)
    db.close()

    const res = await verifyAgainstPath({ seed: 0, dbPath })

    expect(res.task_completed).toBe(false)
    expect(res.field_errors).toEqual([]) // nothing to compare
    const c1 = res.checks_run.find((c) => c.check === "C1")
    expect(c1?.passed).toBe(false)
    expect(c1?.detail).toContain("no POSTED invoice found")
  })

  it("NEG-2a · wrong values (customer/qty/unit_price/tax all wrong) -> false; field_errors populated", async () => {
    const dbPath = freshDbPath()
    // Internally consistent, but matches NEITHER seed-0 expected. E.g. "ACME Co.",
    // qty 2, unit $100.00, tax 10%.
    const wrong = seedPostedWrongInvoice()
    seedPosted(dbPath, wrong)

    const res = await verifyAgainstPath({ seed: 0, dbPath })

    expect(res.task_completed).toBe(false)
    expect(res.field_errors.length).toBeGreaterThan(0)
    expect(res.checks_run.find((c) => c.check === "C2")?.passed).toBe(false) // customer
    expect(res.checks_run.find((c) => c.check === "C3")?.passed).toBe(false) // items
    expect(res.checks_run.find((c) => c.check === "C4")?.passed).toBe(false) // tax
  })

  it("NEG-2b · stored total disagrees with the recomputed total -> false; C6 fails", async () => {
    const dbPath = freshDbPath()
    // Correct items/tax/dates but the STORED total is off by one cent.
    insertRaw(dbPath, {
      invoice_no: "INV-2026-0001",
      customer: exp0.customer,
      status: "POSTED",
      invoice_date: exp0.invoice_date,
      due_date: exp0.due_date,
      tax_rate_bps: exp0.tax_rate_bps,
      subtotal_cents: 36000,
      tax_cents: 2880,
      total_cents: 38881, // recomputed total is 38880
      items: [{ description: "Consulting", qty: 3, unit_price_cents: 12000, line_total_cents: 36000 }],
    })

    const res = await verifyAgainstPath({ seed: 0, dbPath })

    expect(res.task_completed).toBe(false)
    expect(res.checks_run.find((c) => c.check === "C6")?.passed).toBe(false)
    expect(res.field_errors.some((e) => e.field === "total_cents")).toBe(true)
    expect(res.field_errors.some((e) => e.field === "total_cents" && e.expected === "38880")).toBe(true)
  })

  it("NEG-3 · draft-only (form filled, never POSTED) -> false", async () => {
    const dbPath = freshDbPath()
    insertRaw(dbPath, {
      invoice_no: "INV-2026-0001",
      customer: exp0.customer,
      status: "DRAFT", // never posted
      invoice_date: exp0.invoice_date,
      due_date: exp0.due_date,
      tax_rate_bps: exp0.tax_rate_bps,
      subtotal_cents: 36000,
      tax_cents: 2880,
      total_cents: 38880,
      items: [{ description: "Consulting", qty: 3, unit_price_cents: 12000, line_total_cents: 36000 }],
    })

    const res = await verifyAgainstPath({ seed: 0, dbPath })

    expect(res.task_completed).toBe(false)
    expect(res.field_errors).toEqual([])
    expect(res.checks_run.find((c) => c.check === "C1")?.passed).toBe(false)
  })

  it("NEG-4a · cross-run: a row matching a DIFFERENT seed's expectation -> false", async () => {
    const dbPath = freshDbPath()
    // Create the invoice seed=1 would require, then verify against seed=0.
    const spec1 = deriveTaskSpec(1)
    seedPosted(dbPath, {
      customer: spec1.expected.customer,
      invoice_date: spec1.expected.invoice_date,
      due_date: spec1.expected.due_date,
      tax_rate_bps: spec1.expected.tax_rate_bps,
      tax_rate_percent: spec1.expected.tax_rate_bps / 100,
      items: spec1.expected.items,
    })

    const res = await verifyAgainstPath({ seed: 0, dbPath })

    expect(res.task_completed).toBe(false)
    expect(res.field_errors.length).toBeGreaterThan(0) // does not match seed-0 expected
  })

  it("NEG-4b · double-submit (two POSTED rows) -> false; C1 fails; field_errors empty", async () => {
    const dbPath = freshDbPath()
    const db = openDb(dbPath)
    ensureSchema(db)
    createInvoice(db, parsed0) // INV-2026-0001, POSTED
    createInvoice(db, parsed0) // INV-2026-0002, POSTED (double submit)
    db.close()

    const res = await verifyAgainstPath({ seed: 0, dbPath })

    expect(res.task_completed).toBe(false)
    expect(res.field_errors).toEqual([]) // ambiguous — cannot pick one to diff
    expect(res.checks_run.find((c) => c.check === "C1")?.passed).toBe(false)
    expect(res.checks_run.find((c) => c.check === "C1")?.detail).toContain("found 2 POSTED")
  })

  it("NEG-5 · missing DB file -> false (fail-closed, no artifact)", async () => {
    const res = await verifyAgainstPath({ seed: 0, dbPath: join(tmpdir(), "does-not-exist-coldstart.db") })

    expect(res.task_completed).toBe(false)
    expect(res.checks_run.find((c) => c.check === "C1")?.passed).toBe(false)
    expect(res.checks_run.find((c) => c.check === "C1")?.detail).toContain("artifact unavailable")
  })

  it("NEG-6 · corrupt / not-a-sqlite artifact -> false (unparseable)", async () => {
    const dbPath = freshDbPath()
    writeFileSync(dbPath, "this is not a sqlite database at all")

    const res = await verifyAgainstPath({ seed: 0, dbPath })

    expect(res.task_completed).toBe(false)
    expect(res.checks_run.find((c) => c.check === "C1")?.passed).toBe(false)
    expect(res.checks_run.find((c) => c.check === "C1")?.detail).toContain("unparseable")
  })
})

// ---------------------------------------------------------------------------
describe("verifyAgainstSandbox (mock FILE channel — no live Solari)", () => {
  it("reads the artifact via the sandbox files channel and reproduces the path verdict + hash", async () => {
    const dbPath = freshDbPath()
    seedPosted(dbPath, parsed0)
    const bytes = new Uint8Array(readFileSync(dbPath))

    const viaPath = await verifyAgainstPath({ seed: 0, dbPath })
    const viaSandbox = await verifyAgainstSandbox({ seed: 0, sandbox: mockSandbox(bytes) })

    expect(viaSandbox.task_completed).toBe(true)
    expect(viaSandbox.evidence_hash).toBe(viaPath.evidence_hash)
    expect(viaSandbox.checks_run).toEqual(viaPath.checks_run)
  })

  it("empty DB via sandbox -> false (same fail-closed behaviour as path mode)", async () => {
    const dbPath = freshDbPath()
    const db = openDb(dbPath)
    ensureSchema(db)
    db.close()
    const bytes = new Uint8Array(readFileSync(dbPath))

    const res = await verifyAgainstSandbox({ seed: 0, sandbox: mockSandbox(bytes) })

    expect(res.task_completed).toBe(false)
    expect(res.checks_run.find((c) => c.check === "C1")?.passed).toBe(false)
  })

  it("sandbox read failure -> false (fail-closed)", async () => {
    const broken = { files: { read: async () => { throw new Error("ENOENT: no such file") } } } as unknown as Sandbox
    const res = await verifyAgainstSandbox({ seed: 0, sandbox: broken })

    expect(res.task_completed).toBe(false)
    expect(res.checks_run.find((c) => c.check === "C1")?.passed).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// Helper for NEG-2a: a wrong, internally-consistent POSTED invoice.
// ---------------------------------------------------------------------------

function seedPostedWrongInvoice(): ParsedInvoice {
  return {
    customer: "ACME Co.",
    invoice_date: exp0.invoice_date,
    due_date: exp0.due_date,
    tax_rate_bps: 1000, // 10% (expected 8%)
    tax_rate_percent: 10,
    items: [{ description: "Consulting", qty: 2, unit_price_cents: 10000 }], // qty/unit wrong
  }
}
