/**
 * seeder.ts — Smart Reset & Idempotent Data Fixture Seeding
 *
 * Guarantees Zero-Drift Idempotency Across Test Runs:
 * Without systematic pre-test cleanups and seeders, subsequent test runs hit duplicate
 * conflict blockers (e.g. unique constraint violations, 409 Conflict dialogs, dirty state).
 *
 * This module manages:
 * 1. Automatic database cleanup and seeding (SQLite via node:sqlite, raw SQL, or adapters)
 * 2. File-system fixture creation and cleanup (knowledge base docs, test uploads)
 * 3. Seed tracking: remembers seeded records and purges them completely upon teardown
 */

import { existsSync, readdirSync, unlinkSync, writeFileSync } from "node:fs"
import { join } from "node:path"

export interface SeederDbAdapter {
  run(sql: string, params?: any[]): void
  all?(sql: string, params?: any[]): any[]
}

export interface SeedRecord {
  table: string
  primaryKey: string
  id: any
}

export interface SmartResetOptions {
  dbAdapter?: SeederDbAdapter
  debug?: boolean
}

export class SmartReset {
  private seededRecords: SeedRecord[] = []
  private trackedFiles: string[] = []
  private db: SeederDbAdapter | null = null

  constructor(options: SmartResetOptions = {}) {
    this.db = options.dbAdapter ?? null
  }

  setDbAdapter(db: SeederDbAdapter): void {
    this.db = db
  }

  /**
   * Seeds one or more records into a database table idempotently (upsert if conflict).
   */
  seed<T extends Record<string, any>>(
    table: string,
    records: T | T[],
    options: { primaryKey?: string; onConflictUpdate?: boolean } = {}
  ): void {
    if (!this.db) {
      throw new Error("[SmartReset] No database adapter configured. Call setDbAdapter() first.")
    }

    const rows = Array.isArray(records) ? records : [records]
    const pk = options.primaryKey ?? "id"
    const onConflictUpdate = options.onConflictUpdate ?? true

    for (const row of rows) {
      const keys = Object.keys(row)
      const values = Object.values(row)
      const placeholders = keys.map(() => "?").join(", ")

      let sql = `INSERT INTO ${table} (${keys.join(", ")}) VALUES (${placeholders})`
      if (onConflictUpdate && pk && keys.includes(pk)) {
        const updateAssignments = keys
          .filter((k) => k !== pk)
          .map((k) => `${k} = excluded.${k}`)
          .join(", ")
        if (updateAssignments.length > 0) {
          sql += ` ON CONFLICT(${pk}) DO UPDATE SET ${updateAssignments}`
        } else {
          sql += ` ON CONFLICT(${pk}) DO NOTHING`
        }
      }

      this.db.run(sql, values)

      if (row[pk] !== undefined) {
        this.seededRecords.push({ table, primaryKey: pk, id: row[pk] })
      }
    }
  }

  /**
   * Clean up specific records from a table by primary key.
   */
  cleanup(table: string, ids: any | any[], primaryKey = "id"): void {
    if (!this.db) return
    const idList = Array.isArray(ids) ? ids : [ids]
    if (idList.length === 0) return

    for (const id of idList) {
      try {
        this.db.run(`DELETE FROM ${table} WHERE ${primaryKey} = ?`, [id])
      } catch (err) {
        console.warn(`[SmartReset] Cleanup notice on ${table}.${primaryKey}=${id}:`, err)
      }
    }
  }

  /**
   * Cleans files matching a regex pattern inside a target directory.
   */
  cleanFiles(dirPath: string, pattern: RegExp | string): number {
    if (!existsSync(dirPath)) return 0
    const regex = typeof pattern === "string" ? new RegExp(pattern) : pattern
    let cleaned = 0

    try {
      const files = readdirSync(dirPath)
      for (const file of files) {
        if (regex.test(file)) {
          const fullPath = join(dirPath, file)
          try {
            unlinkSync(fullPath)
            cleaned++
          } catch {}
        }
      }
    } catch {}

    return cleaned
  }

  /**
   * Creates an ephemeral test file on disk and tracks it for automatic deletion.
   */
  createTestFile(filePath: string, content: string | Buffer): string {
    writeFileSync(filePath, content)
    this.trackedFiles.push(filePath)
    return filePath
  }

  /**
   * Complete reset: deletes all seeded records in reverse order and unlinks tracked files.
   */
  resetAll(): void {
    // 1. Purge seeded DB records
    if (this.db && this.seededRecords.length > 0) {
      for (let i = this.seededRecords.length - 1; i >= 0; i--) {
        const item = this.seededRecords[i]
        try {
          this.db.run(`DELETE FROM ${item.table} WHERE ${item.primaryKey} = ?`, [item.id])
        } catch {}
      }
      this.seededRecords = []
    }

    // 2. Unlink tracked disk files
    for (const filePath of this.trackedFiles) {
      if (existsSync(filePath)) {
        try {
          unlinkSync(filePath)
        } catch {}
      }
    }
    this.trackedFiles = []
  }
}
