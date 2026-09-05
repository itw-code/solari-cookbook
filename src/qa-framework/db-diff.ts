/**
 * db-diff.ts — Dual-Layer State Verification (UI + Direct Database Diffing)
 *
 * Prevents Silent Persistence Failures & Optimistic UI Blind Spots:
 * A web frontend may optimistically update its UI or display a success toast even
 * when the backend API silently fails to persist changes to SQLite/Postgres.
 *
 * ColdStart Dual-Layer Verification takes database snapshots before and after
 * test steps to assert exact row-level mutations.
 */

export interface DbRow {
  [column: string]: any
}

export interface TableSnapshot {
  table: string
  primaryKey: string
  rows: DbRow[]
}

export type DatabaseSnapshot = Record<string, TableSnapshot>

export interface RowUpdateDiff {
  primaryKey: string
  id: any
  before: DbRow
  after: DbRow
  changedColumns: string[]
}

export interface TableDiff {
  table: string
  inserted: DbRow[]
  deleted: DbRow[]
  updated: RowUpdateDiff[]
  totalMutations: number
}

export interface DatabaseDiffReport {
  tables: Record<string, TableDiff>
  totalInserted: number
  totalDeleted: number
  totalUpdated: number
  hasMutations: boolean
}

export interface DbQueryable {
  all<T = any>(sql: string, params?: any[]): T[]
}

export class DatabaseDiffEngine {
  private db: DbQueryable

  constructor(db: DbQueryable) {
    this.db = db
  }

  /**
   * Captures an instant snapshot of specified tables.
   */
  snapshot(tables: { name: string; primaryKey?: string }[] | string[]): DatabaseSnapshot {
    const result: DatabaseSnapshot = {}

    for (const item of tables) {
      const tableName = typeof item === "string" ? item : item.name
      const primaryKey = typeof item === "string" ? "id" : (item.primaryKey ?? "id")

      try {
        const rows = this.db.all(`SELECT * FROM ${tableName}`)
        result[tableName] = {
          table: tableName,
          primaryKey,
          rows: JSON.parse(JSON.stringify(rows)), // deep clone
        }
      } catch (err: any) {
        console.warn(`[DatabaseDiffEngine] Warning reading table ${tableName}:`, err.message)
        result[tableName] = {
          table: tableName,
          primaryKey,
          rows: [],
        }
      }
    }

    return result
  }

  /**
   * Compares a baseline snapshot with the current database state (or a secondary snapshot).
   */
  diff(before: DatabaseSnapshot, after?: DatabaseSnapshot): DatabaseDiffReport {
    const currentSnapshot =
      after ??
      this.snapshot(
        Object.values(before).map((t) => ({ name: t.table, primaryKey: t.primaryKey }))
      )

    const report: DatabaseDiffReport = {
      tables: {},
      totalInserted: 0,
      totalDeleted: 0,
      totalUpdated: 0,
      hasMutations: false,
    }

    for (const [tableName, beforeTable] of Object.entries(before)) {
      const afterTable = currentSnapshot[tableName] ?? {
        table: tableName,
        primaryKey: beforeTable.primaryKey,
        rows: [],
      }

      const pk = beforeTable.primaryKey
      const beforeMap = new Map<any, DbRow>()
      for (const r of beforeTable.rows) {
        beforeMap.set(r[pk], r)
      }

      const afterMap = new Map<any, DbRow>()
      for (const r of afterTable.rows) {
        afterMap.set(r[pk], r)
      }

      const inserted: DbRow[] = []
      const deleted: DbRow[] = []
      const updated: RowUpdateDiff[] = []

      // Check for inserted or updated
      for (const [id, afterRow] of afterMap.entries()) {
        const beforeRow = beforeMap.get(id)
        if (!beforeRow) {
          inserted.push(afterRow)
        } else {
          // Compare columns
          const changedCols: string[] = []
          const allKeys = new Set([...Object.keys(beforeRow), ...Object.keys(afterRow)])
          for (const k of allKeys) {
            if (JSON.stringify(beforeRow[k]) !== JSON.stringify(afterRow[k])) {
              changedCols.push(k)
            }
          }
          if (changedCols.length > 0) {
            updated.push({
              primaryKey: pk,
              id,
              before: beforeRow,
              after: afterRow,
              changedColumns: changedCols,
            })
          }
        }
      }

      // Check for deleted
      for (const [id, beforeRow] of beforeMap.entries()) {
        if (!afterMap.has(id)) {
          deleted.push(beforeRow)
        }
      }

      const totalMutations = inserted.length + deleted.length + updated.length
      report.tables[tableName] = {
        table: tableName,
        inserted,
        deleted,
        updated,
        totalMutations,
      }

      report.totalInserted += inserted.length
      report.totalDeleted += deleted.length
      report.totalUpdated += updated.length
    }

    report.hasMutations =
      report.totalInserted > 0 || report.totalDeleted > 0 || report.totalUpdated > 0

    return report
  }

  /**
   * Asserts that exactly N rows were inserted into the target table.
   */
  assertInserted(diff: DatabaseDiffReport, table: string, expectedCount?: number): DbRow[] {
    const tableDiff = diff.tables[table]
    if (!tableDiff) {
      throw new Error(`[DB Attestation] Table '${table}' not found in diff snapshot.`)
    }
    if (expectedCount !== undefined && tableDiff.inserted.length !== expectedCount) {
      throw new Error(
        `[DB Attestation] Expected ${expectedCount} rows inserted in '${table}', but found ${tableDiff.inserted.length}.`
      )
    }
    if (expectedCount === undefined && tableDiff.inserted.length === 0) {
      throw new Error(`[DB Attestation] Expected rows to be inserted in '${table}', but 0 were created.`)
    }
    return tableDiff.inserted
  }

  /**
   * Asserts that exactly N rows were deleted from the target table.
   */
  assertDeleted(diff: DatabaseDiffReport, table: string, expectedCount?: number): DbRow[] {
    const tableDiff = diff.tables[table]
    if (!tableDiff) {
      throw new Error(`[DB Attestation] Table '${table}' not found in diff snapshot.`)
    }
    if (expectedCount !== undefined && tableDiff.deleted.length !== expectedCount) {
      throw new Error(
        `[DB Attestation] Expected ${expectedCount} rows deleted from '${table}', but found ${tableDiff.deleted.length}.`
      )
    }
    if (expectedCount === undefined && tableDiff.deleted.length === 0) {
      throw new Error(`[DB Attestation] Expected rows to be deleted from '${table}', but 0 were removed.`)
    }
    return tableDiff.deleted
  }

  /**
   * Asserts that no mutations occurred in specified table.
   */
  assertUnchanged(diff: DatabaseDiffReport, table: string): void {
    const tableDiff = diff.tables[table]
    if (tableDiff && tableDiff.totalMutations > 0) {
      throw new Error(
        `[DB Attestation] Expected table '${table}' to remain unchanged, but detected mutations (inserted: ${tableDiff.inserted.length}, updated: ${tableDiff.updated.length}, deleted: ${tableDiff.deleted.length}).`
      )
    }
  }

  /**
   * Human-readable formatted summary of diff.
   */
  formatSummary(diff: DatabaseDiffReport): string {
    const lines: string[] = [
      `Database Mutation Summary: +${diff.totalInserted} inserted, ~${diff.totalUpdated} updated, -${diff.totalDeleted} deleted.`,
    ]
    for (const [tName, tDiff] of Object.entries(diff.tables)) {
      if (tDiff.totalMutations > 0) {
        lines.push(`  • ${tName}: +${tDiff.inserted.length}, ~${tDiff.updated.length}, -${tDiff.deleted.length}`)
      }
    }
    return lines.join("\n")
  }
}
