/**
 * verifier.ts — Fail-closed ground-truth verifier for the Demo Site.
 *
 * Verifies that the ColdStart agent actually submitted the early access form
 * by reading the SQLite database directly — NEVER trusting the agent's narration,
 * DOM state, or completion claims.
 *
 * Checks:
 *   - D1: row exists in `signups`
 *   - D2: email matches expected
 *   - D3: created_at is within the run window
 *
 * Returns `{ task_completed: boolean, checks: { D1, D2, D3 }, row? }`.
 */

import { DatabaseSync } from "../sqlite.ts"
import type { SignupRecord } from "./server.ts"

export interface VerifyDemoInput {
  /** The expected email submitted by the agent. */
  expectedEmail: string
  /** DatabaseSync instance or file path to SQLite DB. */
  db: DatabaseSync | string
  /** Timestamp when the run/task started (Date, ISO string, or epoch ms). */
  windowStart?: Date | string | number
  /** Allowed clock skew / tolerance in ms (default: 5000). */
  skewMs?: number
  /** Maximum window duration in ms if windowStart is omitted (default: 60,000). */
  windowMs?: number
}

export interface DemoCheckResult {
  passed: boolean
  detail: string
}

export interface DemoVerifierResult {
  /** Fail-closed: true only if D1, D2, and D3 all pass. */
  task_completed: boolean
  checks: {
    D1: DemoCheckResult
    D2: DemoCheckResult
    D3: DemoCheckResult
  }
  row?: SignupRecord
}

/**
 * Executes fail-closed ground truth verification against the demo site SQLite database.
 */
export function verifyDemoSignup(input: VerifyDemoInput): DemoVerifierResult {
  let db: DatabaseSync | null = null
  let shouldCloseDb = false

  try {
    if (typeof input.db === "string") {
      db = new DatabaseSync(input.db, { readOnly: true })
      shouldCloseDb = true
    } else {
      db = input.db
    }

    // Query the latest signup record
    const row = db
      .prepare("SELECT id, name, email, created_at FROM signups ORDER BY id DESC LIMIT 1")
      .get() as SignupRecord | undefined

    if (!row) {
      return {
        task_completed: false,
        checks: {
          D1: { passed: false, detail: "D1 FAILED: No records found in signups table" },
          D2: { passed: false, detail: "D2 FAILED: Not evaluated because no signup row exists" },
          D3: { passed: false, detail: "D3 FAILED: Not evaluated because no signup row exists" },
        },
      }
    }

    // D1: row exists
    const d1Passed = true
    const d1Detail = `D1 PASSED: Signup row found (id=${row.id}, name="${row.name}")`

    // D2: email matches expected
    const expected = input.expectedEmail.trim().toLowerCase()
    const actual = (row.email ?? "").trim().toLowerCase()
    const d2Passed = actual === expected && expected.length > 0
    const d2Detail = d2Passed
      ? `D2 PASSED: Email matches expected "${input.expectedEmail}"`
      : `D2 FAILED: Email mismatch — expected "${input.expectedEmail}", found "${row.email}"`

    // D3: created_at within run window
    const rowTime = new Date(row.created_at).getTime()
    let d3Passed = false
    let d3Detail = ""

    if (Number.isNaN(rowTime)) {
      d3Passed = false
      d3Detail = `D3 FAILED: Invalid or unparseable created_at value "${row.created_at}"`
    } else {
      const windowStartMs = input.windowStart
        ? new Date(input.windowStart).getTime()
        : Date.now() - (input.windowMs ?? 60_000)
      const maxSkew = input.skewMs ?? 5000
      const windowEndMs = Date.now() + maxSkew

      if (rowTime >= windowStartMs && rowTime <= windowEndMs) {
        d3Passed = true
        d3Detail = `D3 PASSED: created_at (${row.created_at}) is within window [${new Date(windowStartMs).toISOString()} - ${new Date(windowEndMs).toISOString()}]`
      } else {
        d3Passed = false
        d3Detail = `D3 FAILED: created_at (${row.created_at}) is outside window [${new Date(windowStartMs).toISOString()} - ${new Date(windowEndMs).toISOString()}]`
      }
    }

    const task_completed = d1Passed && d2Passed && d3Passed

    return {
      task_completed,
      checks: {
        D1: { passed: d1Passed, detail: d1Detail },
        D2: { passed: d2Passed, detail: d2Detail },
        D3: { passed: d3Passed, detail: d3Detail },
      },
      row,
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    return {
      task_completed: false,
      checks: {
        D1: { passed: false, detail: `D1 FAILED: Database error / query failed: ${msg}` },
        D2: { passed: false, detail: "D2 FAILED: Not evaluated due to database failure" },
        D3: { passed: false, detail: "D3 FAILED: Not evaluated due to database failure" },
      },
    }
  } finally {
    if (shouldCloseDb && db) {
      try {
        db.close()
      } catch {
        // Ignore close error
      }
    }
  }
}
