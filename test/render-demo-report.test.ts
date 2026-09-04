/**
 * render-demo-report.test.ts — Unit and integration tests for HTML demo report rendering.
 */

import { describe, it, expect, beforeAll, afterAll } from "vitest"
import { mkdtempSync, writeFileSync, readFileSync, existsSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join, resolve } from "node:path"
import {
  renderDemoReportHtml,
  generateDemoReport,
  type CombinedDemoReport,
} from "../scripts/render-demo-report.js"
import { runCombinedDemo } from "../scripts/run-combined-demo.js"

describe("render-demo-report", () => {
  let tempDir: string
  let fixtureJsonPath: string
  let outputHtmlPath: string

  const sampleReport: CombinedDemoReport = {
    generated_at: "2026-09-03T10:00:00.000Z",
    run_id: "demo_test123",
    targets: {
      clean_url: "http://localhost:3000/",
      slop_url: "http://localhost:3000/?slop=1",
    },
    slop_catcher_reports: {
      clean: {
        runId: "scan_clean_test",
        slopScore: 4,
        status: "PASS",
        flags: [],
        recommendation: "Design passes baseline QA standards.",
        metrics: {
          contrastRatio: 7.2,
          spacingVariance: 0,
          vlmSlopScore: 10,
        },
        targetUrl: "http://localhost:3000/",
      },
      slop: {
        runId: "scan_slop_test",
        slopScore: 40,
        status: "WARN",
        flags: [
          "Low contrast ratio detected (2.1:1 < 4.5:1 WCAG AA)",
          "Off-grid spacing variance detected (15px deviation)",
        ],
        recommendation: "Design passes baseline QA standards.",
        metrics: {
          contrastRatio: 2.1,
          spacingVariance: 15,
          vlmSlopScore: 10,
        },
        targetUrl: "http://localhost:3000/?slop=1",
      },
    },
    coldstart_agent_result: {
      task: 'Open early access page, enter name "ColdStart Agent" and email "agent@demo.solari", submit form.',
      status: "done",
      steps_taken: 6,
      final_title: "Access Requested",
      actions: [
        { step: 1, action: { kind: "click", x: 200, y: 150 }, ok: true, rationale: "Focus name" },
        { step: 2, action: { kind: "type", text: "ColdStart Agent" }, ok: true, rationale: "Type name" },
        { step: 3, action: { kind: "click", x: 200, y: 220 }, ok: true, rationale: "Focus email" },
        { step: 4, action: { kind: "type", text: "agent@demo.solari" }, ok: true, rationale: "Type email" },
        { step: 5, action: { kind: "click", x: 200, y: 300 }, ok: true, rationale: "Click submit" },
        { step: 6, action: { kind: "done" }, ok: true, rationale: "Complete" },
      ],
    },
    ground_truth_verifier: {
      task_completed: true,
      checks: {
        D1: { passed: true, detail: "D1 PASSED: Signup row found (id=1, name=\"ColdStart Agent\")" },
        D2: { passed: true, detail: "D2 PASSED: Email matches expected \"agent@demo.solari\"" },
        D3: { passed: true, detail: "D3 PASSED: created_at is within window" },
      },
      row: {
        id: 1,
        name: "ColdStart Agent",
        email: "agent@demo.solari",
        created_at: "2026-09-03T10:00:05.000Z",
      },
    },
  }

  beforeAll(() => {
    tempDir = mkdtempSync(join(tmpdir(), "demo-report-test-"))
    fixtureJsonPath = join(tempDir, "combined-demo-report.json")
    outputHtmlPath = join(tempDir, "combined-demo-report.html")
    writeFileSync(fixtureJsonPath, JSON.stringify(sampleReport, null, 2), "utf8")
  })

  afterAll(() => {
    if (existsSync(tempDir)) {
      rmSync(tempDir, { recursive: true, force: true })
    }
  })

  it("renderDemoReportHtml produces valid self-contained HTML with required markers", () => {
    const html = renderDemoReportHtml(sampleReport, {
      actionConfig: { provider: "openai", modelName: "gpt-5.6-luna", apiKey: "" },
      perceptionConfig: { provider: "google", modelName: "gemini-1.5-flash", apiKey: "" },
    })

    // Valid HTML structure
    expect(html).toContain("<!DOCTYPE html>")
    expect(html).toContain("<html")
    expect(html).toContain("<head>")
    expect(html).toContain("<style>")
    expect(html).toContain("</style>")
    expect(html).toContain("<body")
    expect(html).toContain("</html>")

    // Key headers & titles
    expect(html).toContain("Combined Demo")
    expect(html).toContain("One target, two lenses: design QA + zero-shot generalization")

    // Both variant labels
    expect(html).toContain("Clean Design")
    expect(html).toContain("AI Slop")
    expect(html).toContain("<code>/</code>")
    expect(html).toContain("<code>/?slop=1</code>")

    // Status badges & scores
    expect(html).toContain("PASS")
    expect(html).toContain("WARN")
    expect(html).toContain("4<span>/100</span>")
    expect(html).toContain("40<span>/100</span>")

    // Visual hints & previews
    expect(html).toContain("mock-btn-clean")
    expect(html).toContain("mock-btn-slop")
    expect(html).toContain("linear-gradient(135deg, #667eea 0%, #764ba2 100%)")

    // Evaluation table
    expect(html).toContain("Evaluation Matrix")
    expect(html).toContain("Clean Landing Page")
    expect(html).toContain("Slop Landing Page")
    expect(html).toContain("PASS (D1, D2, D3)")

    // Agent summary & verifier checks
    expect(html).toContain("ColdStart Agent Execution")
    expect(html).toContain("Check D1: SQLite Row Existence")
    expect(html).toContain("Check D2: Target Email Match")
    expect(html).toContain("Check D3: Run Window Validity")
    expect(html).toContain("6 steps")

    // Model Router footer
    expect(html).toContain("PERCEPTION:")
    expect(html).toContain("google / gemini-1.5-flash")
    expect(html).toContain("demo_test123")
  })

  it("renderDemoReportHtml shows the offline scripted-run disclosure and labels it plumbing verification", () => {
    const html = renderDemoReportHtml(sampleReport)

    // Explicit, unambiguous disclosure (B3) — present and prominent (header area).
    expect(html).toContain(
      "Offline demo: scripted action sequence against a mock page — verifies plumbing, not model capability",
    )
    expect(html.indexOf("Offline demo: scripted action sequence")).toBeLessThan(
      html.indexOf("ColdStart Agent Execution"),
    )

    // W11 framing: the demo section is plumbing verification, local + mock page.
    expect(html).toContain("Plumbing Verification (Local, Mock Page)")

    // B4 (c): the report also discloses that its design-QA scans are mock/dry-run.
    expect(html).toContain("MOCK / dry-run")
    expect(html).toContain("not a live audit")

    // The report carries no scripted flag -> renderer must NOT attribute a live
    // model name to the (scripted) run. No ACTION-model badge may render.
    expect(html).not.toContain("openai / gpt-5.6-luna")
    expect(html).not.toContain('<strong>ACTION:</strong>')
  })

  it("renderDemoReportHtml renders the ACTION model badge only for a live (non-scripted) run", () => {
    const html = renderDemoReportHtml(sampleReport, {
      scripted: false,
      actionConfig: { provider: "openai", modelName: "gpt-5.6-luna", apiKey: "" },
    })

    expect(html).toContain('<strong>ACTION:</strong> openai / gpt-5.6-luna')
    expect(html).not.toContain("scripted action sequence")
  })

  it("generateDemoReport reads from JSON fixture and writes valid HTML file", async () => {
    const result = await generateDemoReport({
      jsonPath: fixtureJsonPath,
      htmlPath: outputHtmlPath,
    })

    expect(result.outputPath).toBe(outputHtmlPath)
    expect(existsSync(outputHtmlPath)).toBe(true)

    const savedHtml = readFileSync(outputHtmlPath, "utf8")
    expect(savedHtml).toContain("<!DOCTYPE html>")
    expect(savedHtml).toContain("Combined Demo")
    expect(savedHtml).toContain("</html>")
  })

  it("runCombinedDemo persists a report marked scripted with the offline disclosure (audit B3/W11)", async () => {
    const report = (await runCombinedDemo()) as CombinedDemoReport

    // The demo agent is DemoScriptedModel on DemoMockPage — the report must say so.
    expect(report.scripted).toBe(true)

    // The persisted JSON carries the same honest marker.
    const persisted = JSON.parse(
      readFileSync(resolve("artifacts/combined-demo-report.json"), "utf8"),
    ) as CombinedDemoReport
    expect(persisted.scripted).toBe(true)
  })

  it("generateDemoReport invokes runCombinedDemo when JSON report is missing", async () => {
    const missingJsonPath = join(tempDir, "missing-report.json")
    const generatedHtmlPath = join(tempDir, "auto-generated.html")

    const result = await generateDemoReport({
      jsonPath: missingJsonPath,
      htmlPath: generatedHtmlPath,
    })

    expect(existsSync(generatedHtmlPath)).toBe(true)
    expect(result.html).toContain("<!DOCTYPE html>")
    expect(result.html).toContain("Combined Demo")
  })
})
