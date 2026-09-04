/**
 * scan-url.test.ts — Unit tests for the external page URL scanner.
 */
import { describe, it, expect, afterEach, vi } from "vitest"
import { existsSync, readFileSync, rmSync, readdirSync, statSync } from "node:fs"
import { join, resolve } from "node:path"
import { scanExternalPage } from "../src/design-qa/scan-url.ts"
import type { DesignQAResult } from "../src/design-qa/orchestrator.ts"

describe("Standalone URL Scanner (scanExternalPage)", () => {
  let createdRunIds: string[] = []

  afterEach(() => {
    for (const runId of createdRunIds) {
      const dir = join(resolve("artifacts/runs"), runId)
      if (existsSync(dir)) {
        rmSync(dir, { recursive: true, force: true })
      }
    }
    createdRunIds = []
  })

  it("calls scanExternalPage('https://example.com') and returns a valid DesignQAResult object without throwing", async () => {
    const targetUrl = "https://example.com"
    const result: DesignQAResult = await scanExternalPage(targetUrl, { delayMs: 10 })
    createdRunIds.push(result.runId)

    expect(result).toBeDefined()
    expect(result.runId).toContain("scan_")
    expect(result.targetUrl).toBe(targetUrl)
    expect(typeof result.slopScore).toBe("number")
    expect(result.slopScore).toBeGreaterThanOrEqual(0)
    expect(result.slopScore).toBeLessThanOrEqual(100)
    expect(["PASS", "WARN", "BLOCK"]).toContain(result.status)
    expect(Array.isArray(result.flags)).toBe(true)

    // Verify report persistence
    const reportPath = join(resolve("artifacts/runs"), result.runId, "design-qa-report.json")
    expect(existsSync(reportPath)).toBe(true)
    const saved = JSON.parse(readFileSync(reportPath, "utf8")) as DesignQAResult
    expect(saved.runId).toBe(result.runId)
    expect(saved.targetUrl).toBe(targetUrl)
  })

  it("detects accessibility flaws on external pages when low contrast or spacing variance is detected", async () => {
    const targetUrl = "https://example.com/bad-contrast"
    const result: DesignQAResult = await scanExternalPage(targetUrl, {
      delayMs: 10,
      computedCss: {
        contrastRatio: 2.3,
        spacingVariance: 12,
      },
    })
    createdRunIds.push(result.runId)

    expect(result.slopScore).toBeGreaterThanOrEqual(36)
    expect(result.flags.some((f) => f.includes("Low contrast ratio"))).toBe(true)
    expect(result.flags.some((f) => f.includes("Off-grid spacing variance"))).toBe(true)
    expect(["WARN", "BLOCK"]).toContain(result.status)
  })

  it("uses default 1-second delay in mock mode without throwing", async () => {
    const result = await scanExternalPage("https://getsolari.com")
    createdRunIds.push(result.runId)

    expect(result.status).toBe("PASS")
    expect(result.targetUrl).toBe("https://getsolari.com")
  }, 10000)

  it("labels the scan result, persisted report, and CLI output as MOCK/dry-run (audit B4)", async () => {
    const targetUrl = "https://example.com/mock-disclosure"
    const result = await scanExternalPage(targetUrl, { delayMs: 0 })
    createdRunIds.push(result.runId)

    // (a) the scan result object carries an unambiguous MOCK mode + disclosure
    expect(result.mode).toBe("MOCK")
    expect(typeof result.disclosure).toBe("string")
    expect(result.disclosure).toMatch(/mock|dry-run/i)
    expect(result.disclosure).toMatch(/not a live VLM audit/i)

    // ...and the persisted design-qa-report.json carries the same marker
    const reportPath = join(resolve("artifacts/runs"), result.runId, "design-qa-report.json")
    const saved = JSON.parse(readFileSync(reportPath, "utf8")) as DesignQAResult
    expect(saved.mode).toBe("MOCK")
    expect(saved.disclosure).toMatch(/not a live VLM audit/i)
  })

  it("CLI output prints an unambiguous MOCK / dry-run banner (audit B4)", async () => {
    const { main } = await import("../src/design-qa/cli-scan.ts")
    const runsRoot = resolve("artifacts/runs")
    const before = new Date(Date.now() - 1000)
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {})
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {})
    let logged = ""
    try {
      await main(["https://example.com/cli-test"])
    } finally {
      logged = logSpy.mock.calls.flat().join("\n")
      logSpy.mockRestore()
      errSpy.mockRestore()
    }

    // Clean up the scan artifact dir this CLI run just created (mtime-guarded
    // so pre-existing committed artifacts like the getsolari fixture are safe).
    try {
      for (const entry of readdirSync(runsRoot)) {
        if (!entry.startsWith("scan_")) continue
        const stat = statSync(join(runsRoot, entry))
        if (stat.mtime > before) rmSync(join(runsRoot, entry), { recursive: true, force: true })
      }
    } catch {
      /* runs root may not exist */
    }

    // Unambiguous MOCK labeling — no misleading microVM language
    expect(logged).toMatch(/MOCK \/ DRY-RUN/i)
    expect(logged).toMatch(/NOT a live audit/i)
    expect(logged).toMatch(/mock VLM fixture/i)
    expect(logged).not.toMatch(/Solari MicroVM Fast-Fork/)
  })
})
