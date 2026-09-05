/**
 * qa-framework.test.ts — Comprehensive Test Suite for ColdStart Architectural Enhancements
 *
 * Verifies:
 * 1. The "Visible & Interactive" Assertion Wrapper (Zero-Pixel Trap detection)
 * 2. Loose Locator Resilience & Normalized Accessibility Selectors (Copy Drift prevention)
 * 3. Cloud Browser Session Lifecycle & Graceful Replay Fallbacks
 * 4. Autonomous Ingress Tunnel Daemon
 * 5. Smart Reset & Idempotent Fixture Seeding
 * 6. Dual-Layer State Verification (UI + Direct Database Diffing)
 * 7. Automated Visual Difference & Artifact Archiving
 * 8. "I Think It Should Be Enhanced, Because..." Heuristic Generator
 */

import { describe, expect, it, vi, beforeEach } from "vitest"
import {
  expectInteractive,
  expectVisual,
  normalizePattern,
  fuzzyRoleLocator,
  resolveAccessibleLocator,
  safeGetReplayUrl,
  withSessionGuard,
  TunnelDaemon,
  SmartReset,
  DatabaseDiffEngine,
  ArtifactArchiver,
  HeuristicEngine,
} from "../src/qa-framework/index.js"
import { mkdtempSync, rmSync, existsSync, readFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { DatabaseSync } from "../src/sqlite.js"

describe("ColdStart QA Framework Enhancements", () => {
  // ==========================================================================
  // 1. The "Visible & Interactive" Assertion Wrapper
  // ==========================================================================
  describe("1. expectInteractive & expectVisual (Zero-Pixel Trap Prevention)", () => {
    it("passes when element is visible and has positive dimensions", async () => {
      const mockLocator = {
        waitFor: vi.fn().mockResolvedValue(undefined),
        boundingBox: vi.fn().mockResolvedValue({ x: 10, y: 10, width: 120, height: 40 }),
        evaluate: vi.fn().mockResolvedValue({
          opacity: "1",
          visibility: "visible",
          display: "block",
          pointerEvents: "auto",
        }),
      }

      const result = await expectInteractive(mockLocator)
      expect(result).toBe(mockLocator)
      expect(mockLocator.waitFor).toHaveBeenCalledWith({ state: "visible", timeout: 10000 })
    })

    it("catches the Zero-Pixel Trap when DOM element exists but has 0px height (F-039)", async () => {
      const mockLocator = {
        waitFor: vi.fn().mockResolvedValue(undefined),
        boundingBox: vi.fn().mockResolvedValue({ x: 0, y: 0, width: 200, height: 0 }),
        toString: () => "#profile-detail-panel-knowledge",
      }

      await expect(expectInteractive(mockLocator)).rejects.toThrow(
        /Zero-Pixel Trap.*has zero or sub-threshold dimensions.*CSS flex-collapse/
      )
    })

    it("throws when boundingBox returns null", async () => {
      const mockLocator = {
        waitFor: vi.fn().mockResolvedValue(undefined),
        boundingBox: vi.fn().mockResolvedValue(null),
        toString: () => ".hidden-container",
      }

      await expect(expectInteractive(mockLocator)).rejects.toThrow(
        /Zero-Pixel Trap.*has no layout bounding box/
      )
    })

    it("throws when element has computed opacity: 0", async () => {
      const mockLocator = {
        waitFor: vi.fn().mockResolvedValue(undefined),
        boundingBox: vi.fn().mockResolvedValue({ x: 10, y: 10, width: 50, height: 50 }),
        evaluate: vi.fn().mockResolvedValue({
          opacity: "0",
          visibility: "visible",
          display: "block",
          pointerEvents: "auto",
        }),
      }

      await expect(expectInteractive(mockLocator)).rejects.toThrow(/computed opacity is 0/)
    })

    it("throws when pointer-events is none", async () => {
      const mockLocator = {
        waitFor: vi.fn().mockResolvedValue(undefined),
        boundingBox: vi.fn().mockResolvedValue({ x: 10, y: 10, width: 50, height: 50 }),
        evaluate: vi.fn().mockResolvedValue({
          opacity: "1",
          visibility: "visible",
          display: "block",
          pointerEvents: "none",
        }),
      }

      await expect(expectInteractive(mockLocator)).rejects.toThrow(/pointer-events: none prevents agent clicks/)
    })

    it("expectVisual resolves selector string through page.locator and validates", async () => {
      const mockLocator = {
        waitFor: vi.fn().mockResolvedValue(undefined),
        boundingBox: vi.fn().mockResolvedValue({ x: 0, y: 0, width: 100, height: 30 }),
      }
      const mockPage = {
        locator: vi.fn().mockReturnValue(mockLocator),
      }

      const verified = await expectVisual(mockPage, "button.submit")
      expect(mockPage.locator).toHaveBeenCalledWith("button.submit")
      expect(verified).toBe(mockLocator)
    })
  })

  // ==========================================================================
  // 2. Loose Locator Resilience & Normalized Accessibility Selectors
  // ==========================================================================
  describe("2. normalizePattern & Normalized Accessibility Selectors", () => {
    it("normalizes text pattern stripping trailing colons and punctuation", () => {
      const regex = normalizePattern("Logs:")
      expect(regex.test("automation worker logs")).toBe(true)
      expect(regex.test("Logs: 12 active")).toBe(true)
      expect(regex.test("LOGS")).toBe(true)
    })

    it("collapses multi-spaces into flexible whitespace regex", () => {
      const regex = normalizePattern("Create    New   Automation")
      expect(regex.test("Create New Automation")).toBe(true)
      expect(regex.test("create  new  automation")).toBe(true)
    })

    it("fuzzyRoleLocator calls page.getByRole with normalized regex", () => {
      const mockPage = {
        locator: vi.fn(),
        getByRole: vi.fn().mockReturnValue("mock-role-locator"),
      }

      const loc = fuzzyRoleLocator(mockPage, "dialog", "Logs:")
      expect(mockPage.getByRole).toHaveBeenCalledWith("dialog", {
        name: expect.any(RegExp),
        exact: false,
      })
      expect(loc).toBe("mock-role-locator")
    })

    it("resolveAccessibleLocator prioritizes semantic role > label > placeholder > testId", () => {
      const mockPage = {
        locator: vi.fn().mockImplementation((sel) => `locator(${sel})`),
        getByRole: vi.fn().mockReturnValue("role-button"),
      }

      // Role + name
      const r1 = resolveAccessibleLocator(mockPage, { role: "button", name: /replace/i })
      expect(r1).toBe("role-button")

      // Label
      const r2 = resolveAccessibleLocator(mockPage, { label: "Search chats" })
      expect(mockPage.locator).toHaveBeenCalledWith(expect.stringContaining("aria-label"))
      expect(r2).toBeDefined()

      // Placeholder
      const r3 = resolveAccessibleLocator(mockPage, { placeholder: "Search..." })
      expect(mockPage.locator).toHaveBeenCalledWith(expect.stringContaining("placeholder"))
      expect(r3).toBeDefined()

      // TestId
      const r4 = resolveAccessibleLocator(mockPage, { testId: "modal-submit" })
      expect(mockPage.locator).toHaveBeenCalledWith('[data-testid="modal-submit"]')
      expect(r4).toBeDefined()
    })
  })

  // ==========================================================================
  // 3. Cloud Browser Session Lifecycle & Graceful Replay Fallbacks
  // ==========================================================================
  describe("3. safeGetReplayUrl & withSessionGuard", () => {
    it("returns null instead of crashing when getReplayUrl throws 404 or TypeError", async () => {
      const mockSolari = {
        sessions: {
          getReplayUrl: vi.fn().mockRejectedValue(new Error("HTTP 404: Session replay not found")),
        },
      }

      const replayUrl = await safeGetReplayUrl(mockSolari, "session-123", {
        timeoutMs: 1500,
        pollIntervalMs: 500,
      })
      expect(replayUrl).toBeNull()
    })

    it("returns replay URL when available", async () => {
      const mockSolari = {
        sessions: {
          getReplayUrl: vi.fn().mockResolvedValue({ url: "https://solari.replay/session-abc" }),
        },
      }

      const replayUrl = await safeGetReplayUrl(mockSolari, "session-abc", {
        timeoutMs: 2000,
      })
      expect(replayUrl).toBe("https://solari.replay/session-abc")
    })

    it("withSessionGuard executes test and guarantees browser.close() and solari.close() in finally block", async () => {
      const mockBrowser = {
        id: "browser-sess-xyz",
        newPage: vi.fn().mockResolvedValue({
          setViewportSize: vi.fn().mockResolvedValue(undefined),
          on: vi.fn(),
        }),
        close: vi.fn().mockResolvedValue(undefined),
      }
      const mockSolari = {
        launch: vi.fn().mockResolvedValue(mockBrowser),
        close: vi.fn().mockResolvedValue(undefined),
        sessions: {
          getReplayUrl: vi.fn().mockResolvedValue(null),
        },
      }

      const { result, teardown } = await withSessionGuard(
        mockSolari,
        { recording: true, replayTimeoutMs: 1000 },
        async (ctx) => {
          expect(ctx.sessionId).toBe("browser-sess-xyz")
          return "test-passed"
        }
      )

      expect(result).toBe("test-passed")
      expect(mockBrowser.close).toHaveBeenCalledTimes(1)
      expect(mockSolari.close).toHaveBeenCalledTimes(1)
      expect(teardown.sessionId).toBe("browser-sess-xyz")
    })

    it("guarantees browser teardown even when test function throws", async () => {
      const mockBrowser = {
        id: "browser-error-test",
        newPage: vi.fn().mockResolvedValue({
          setViewportSize: vi.fn().mockResolvedValue(undefined),
          on: vi.fn(),
        }),
        close: vi.fn().mockResolvedValue(undefined),
      }
      const mockSolari = {
        launch: vi.fn().mockResolvedValue(mockBrowser),
        close: vi.fn().mockResolvedValue(undefined),
      }

      await expect(
        withSessionGuard(mockSolari, {}, async () => {
          throw new Error("Assertion failed inside step")
        })
      ).rejects.toThrow("Assertion failed inside step")

      expect(mockBrowser.close).toHaveBeenCalled()
      expect(mockSolari.close).toHaveBeenCalled()
    })
  })

  // ==========================================================================
  // 4. Autonomous Ingress Tunnel Daemon
  // ==========================================================================
  describe("4. TunnelDaemon", () => {
    it("captures trycloudflare.com URL and sets TARGET_URL in mock fallback mode", async () => {
      const daemon = new TunnelDaemon()
      const instance = await daemon.start({
        port: 4310,
        binaryPath: "non-existent-cloudflared-binary",
        allowMockFallback: true,
      })

      expect(instance.url).toMatch(/https:\/\/mock-tunnel-[a-z0-9]+\.trycloudflare\.com/)
      expect(process.env.TARGET_URL).toBe(instance.url)
      expect(daemon.getTunnelUrl()).toBe(instance.url)

      const healthy = await instance.isHealthy()
      expect(healthy).toBe(true)

      await instance.stop()
      expect(daemon.getTunnelUrl()).toBeNull()
    })
  })

  // ==========================================================================
  // 5. Smart Reset & Idempotent Fixture Seeding
  // ==========================================================================
  describe("5. SmartReset (Idempotent Fixture Management)", () => {
    let db: DatabaseSync
    let tempDir: string

    beforeEach(() => {
      tempDir = mkdtempSync(join(tmpdir(), "seeder-test-"))
      db = new DatabaseSync(":memory:")
      db.exec(`
        CREATE TABLE automations (
          id TEXT PRIMARY KEY,
          name TEXT,
          enabled INTEGER
        );
      `)
    })

    it("seeds records with on-conflict update and tracks them for complete reset", () => {
      const seeder = new SmartReset({
        dbAdapter: {
          run: (sql, params) => db.prepare(sql).run(...(params ?? [])),
          all: (sql, params) => db.prepare(sql).all(...(params ?? [])),
        },
      })

      // Seed record
      seeder.seed("automations", { id: "auto-1", name: "Daily Report", enabled: 1 })
      let rows = db.prepare("SELECT * FROM automations").all() as any[]
      expect(rows.length).toBe(1)
      expect(rows[0].name).toBe("Daily Report")

      // Re-seed updated record (idempotency check)
      seeder.seed("automations", { id: "auto-1", name: "Updated Daily Report", enabled: 0 })
      rows = db.prepare("SELECT * FROM automations").all() as any[]
      expect(rows.length).toBe(1)
      expect(rows[0].name).toBe("Updated Daily Report")

      // Reset all seeded records
      seeder.resetAll()
      rows = db.prepare("SELECT * FROM automations").all() as any[]
      expect(rows.length).toBe(0)
    })

    it("tracks and cleans temporary disk files", () => {
      const seeder = new SmartReset()
      const testFile = join(tempDir, "temp-test.txt")
      seeder.createTestFile(testFile, "hello fixture")

      expect(existsSync(testFile)).toBe(true)
      seeder.resetAll()
      expect(existsSync(testFile)).toBe(false)

      rmSync(tempDir, { recursive: true, force: true })
    })
  })

  // ==========================================================================
  // 6. Dual-Layer State Verification (Database Diffing)
  // ==========================================================================
  describe("6. DatabaseDiffEngine (Dual-Layer State Verification)", () => {
    let db: DatabaseSync

    beforeEach(() => {
      db = new DatabaseSync(":memory:")
      db.exec(`
        CREATE TABLE users (
          id TEXT PRIMARY KEY,
          email TEXT,
          role TEXT
        );
        INSERT INTO users (id, email, role) VALUES ('u1', 'alice@test.com', 'admin');
      `)
    })

    it("detects exact inserted, updated, and deleted rows", () => {
      const engine = new DatabaseDiffEngine({
        all: (sql) => db.prepare(sql).all() as any[],
      })

      // 1. Take baseline snapshot
      const baseline = engine.snapshot(["users"])

      // 2. Perform mutations (simulating user actions)
      db.prepare("INSERT INTO users (id, email, role) VALUES ('u2', 'bob@test.com', 'member')").run()
      db.prepare("UPDATE users SET role = 'superadmin' WHERE id = 'u1'").run()

      // 3. Diff against baseline
      const diff = engine.diff(baseline)

      expect(diff.hasMutations).toBe(true)
      expect(diff.totalInserted).toBe(1)
      expect(diff.totalUpdated).toBe(1)
      expect(diff.totalDeleted).toBe(0)

      const inserted = engine.assertInserted(diff, "users", 1)
      expect(inserted[0].id).toBe("u2")
      expect(inserted[0].email).toBe("bob@test.com")

      const userDiff = diff.tables["users"]
      expect(userDiff.updated.length).toBe(1)
      expect(userDiff.updated[0].id).toBe("u1")
      expect(userDiff.updated[0].changedColumns).toContain("role")
      expect(userDiff.updated[0].before.role).toBe("admin")
      expect(userDiff.updated[0].after.role).toBe("superadmin")

      const summary = engine.formatSummary(diff)
      expect(summary).toContain("users: +1, ~1, -0")
    })

    it("assertUnchanged passes when no mutation occurs and throws when unexpected mutation happens", () => {
      const engine = new DatabaseDiffEngine({
        all: (sql) => db.prepare(sql).all() as any[],
      })

      const baseline = engine.snapshot(["users"])
      const noMutationDiff = engine.diff(baseline)
      expect(() => engine.assertUnchanged(noMutationDiff, "users")).not.toThrow()

      // Add unexpected mutation
      db.prepare("DELETE FROM users WHERE id = 'u1'").run()
      const mutatedDiff = engine.diff(baseline)
      expect(() => engine.assertUnchanged(mutatedDiff, "users")).toThrow(/Expected table 'users' to remain unchanged/)
    })
  })

  // ==========================================================================
  // 7. Automated Visual Difference & Artifact Archiving
  // ==========================================================================
  describe("7. ArtifactArchiver", () => {
    it("writes canonical report.json, markdown report, and comparison artifacts", () => {
      const tempDir = mkdtempSync(join(tmpdir(), "archiver-test-"))
      const archiver = new ArtifactArchiver({
        baseDir: tempDir,
        batchId: "solari-btest",
        targetUrl: "https://example.trycloudflare.com",
      })

      archiver.recordStep({
        step: "T-01",
        action: "Login and view dashboard",
        url: "https://example.trycloudflare.com/dashboard",
        screenshot: "01-dashboard.png",
        pass: true,
        notes: "Dashboard verified.",
        consoleErrors: [],
      })

      const report = archiver.writeJsonReport({
        sessionId: "session-test-01",
        replayUrl: "https://solari.replay/test",
      })

      expect(report.totalFindings).toBe(1)
      expect(report.passed).toBe(1)
      expect(existsSync(join(archiver.evidenceDir, "report.json"))).toBe(true)

      const md = archiver.writeMarkdownReport()
      expect(md).toContain("# Solari Cloud Browser E2E QA Audit Report — solari-btest")
      expect(md).toContain("T-01")
      expect(existsSync(join(archiver.evidenceDir, "audit-report.md"))).toBe(true)

      const reelPath = archiver.generateComparisonReelHtml("before.png", "after.png")
      expect(existsSync(reelPath)).toBe(true)
      const html = readFileSync(reelPath, "utf8")
      expect(html).toContain("Visual State Comparison Reel")

      const svgPath = archiver.generateSequenceStripSvg()
      expect(existsSync(svgPath)).toBe(true)
      const svg = readFileSync(svgPath, "utf8")
      expect(svg).toContain("<svg")
      expect(svg).toContain("T-01")

      rmSync(tempDir, { recursive: true, force: true })
    })
  })

  // ==========================================================================
  // 8. "I Think It Should Be Enhanced, Because..." Heuristic Generator
  // ==========================================================================
  describe("8. HeuristicEngine", () => {
    it("flags missing form debounce and formats canonical enhancement card", () => {
      const engine = new HeuristicEngine()
      const item = engine.inspectFormValidation({
        route: "/profiles",
        formName: "Profile Name Input",
        hasInlineDebounce: false,
        hasValidationFeedback: false,
        hasClearErrorState: false,
      })

      expect(item).not.toBeNull()
      expect(item?.category).toBe("validation")
      expect(item?.rationale).toContain("I think it should be enhanced, because")

      const md = engine.formatMarkdown()
      expect(md).toContain("### Feature: Profile Name Input (`/profiles`)")
      expect(md).toContain("- **\"I Think It Should Be Enhanced, Because...\"**:")
      expect(md).toContain("- **Proposed Enhancement**:")
      expect(md).toContain("- **Expected Impact**:")
    })

    it("flags unconfirmed destructive actions", () => {
      const engine = new HeuristicEngine()
      const item = engine.inspectDestructiveGuard({
        route: "/automations",
        actionName: "Delete Automation",
        hasConfirmationModal: false,
        hasCancelDefaultFocus: false,
      })

      expect(item).not.toBeNull()
      expect(item?.category).toBe("destructive_guard")
      expect(item?.rationale).toContain("destructive operations (deletions, purges, rotations) are irreversible")
    })

    it("flags unguided empty states lacking starter templates", () => {
      const engine = new HeuristicEngine()
      const item = engine.inspectEmptyState({
        route: "/automations",
        containerName: "Automations Detail Panel",
        itemCount: 0,
        hasActionableCta: false,
        hasStarterTemplates: false,
        displayedCopy: "Select an automation to view runs",
      })

      expect(item).not.toBeNull()
      expect(item?.category).toBe("empty_state")
      expect(item?.proposedEnhancement).toContain("starter blueprint cards")
    })

    it("flags async mutations lacking immediate pending / disabled feedback", () => {
      const engine = new HeuristicEngine()
      const item = engine.inspectAsyncFeedback({
        route: "/login",
        actionName: "Login Submit Button",
        displaysLoadingSpinner: false,
        disablesButtonOnSubmit: false,
      })

      expect(item).not.toBeNull()
      expect(item?.category).toBe("async_feedback")
      expect(item?.expectedImpact).toContain("Prevents double-click race conditions")
    })
  })
})
