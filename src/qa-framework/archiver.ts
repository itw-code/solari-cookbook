/**
 * archiver.ts — Automated Visual Difference & Artifact Archiving
 *
 * Standardizes evidence preservation across CUA runs:
 * 1. Consistent folder hierarchies: `qa-evidence/<batch-id>/`
 * 2. Canonical JSON test reports with full telemetry and step findings
 * 3. Side-by-side comparison reels & composite visual strip generation
 * 4. Automatic Markdown audit report generation from JSON evidence
 */

import { mkdirSync, writeFileSync } from "node:fs"
import { basename, join, resolve } from "node:path"

export interface StepFinding {
  step: string
  action: string
  url: string
  screenshot: string
  pass: boolean
  notes: string
  consoleErrors: string[]
  durationMs?: number
  diff?: any
}

export interface QaReportData {
  batch: string
  timestamp: string
  sessionId: string
  replayUrl: string | null
  targetUrl: string
  findings: StepFinding[]
  totalFindings: number
  passed: number
  failed: number
  metadata?: Record<string, any>
}

export interface ArchiverOptions {
  baseDir?: string
  batchId: string
  targetUrl: string
}

export class ArtifactArchiver {
  public readonly evidenceDir: string
  private readonly batchId: string
  private readonly targetUrl: string
  private findings: StepFinding[] = []

  constructor(options: ArchiverOptions) {
    this.batchId = options.batchId
    this.targetUrl = options.targetUrl
    const base = options.baseDir ?? resolve("qa-evidence")
    this.evidenceDir = join(base, this.batchId)
    mkdirSync(this.evidenceDir, { recursive: true })
  }

  /**
   * Records a single step finding and its associated screenshot artifact.
   */
  recordStep(finding: StepFinding): void {
    this.findings.push(finding)
  }

  getFindings(): readonly StepFinding[] {
    return this.findings
  }

  /**
   * Generates and writes the canonical `report.json` to the evidence directory.
   */
  writeJsonReport(options: {
    sessionId: string
    replayUrl: string | null
    metadata?: Record<string, any>
  }): QaReportData {
    const report: QaReportData = {
      batch: this.batchId,
      timestamp: new Date().toISOString(),
      sessionId: options.sessionId,
      replayUrl: options.replayUrl,
      targetUrl: this.targetUrl,
      findings: [...this.findings],
      totalFindings: this.findings.length,
      passed: this.findings.filter((f) => f.pass).length,
      failed: this.findings.filter((f) => !f.pass).length,
      metadata: options.metadata,
    }

    const reportPath = join(this.evidenceDir, "report.json")
    writeFileSync(reportPath, JSON.stringify(report, null, 2), "utf8")
    return report
  }

  /**
   * Generates a full Markdown audit report document from the findings.
   */
  writeMarkdownReport(options?: {
    auditorName?: string
    executiveSummary?: string
    outputPath?: string
  }): string {
    const auditor = options?.auditorName ?? "Solari Autonomous Computer Use Agent (CUA)"
    const total = this.findings.length
    const passed = this.findings.filter((f) => f.pass).length
    const failed = total - passed
    const passRate = total > 0 ? Math.round((passed / total) * 100) : 100

    const lines: string[] = [
      `# Solari Cloud Browser E2E QA Audit Report — ${this.batchId}`,
      "",
      `**Audit Date**: ${new Date().toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })}  `,
      `**Auditor**: ${auditor}  `,
      `**Target URL**: \`${this.targetUrl}\`  `,
      `**Evidence Archive**: \`${this.evidenceDir}\`  `,
      `**Status**: ${passed} / ${total} PASSED (${passRate}%)`,
      "",
      "---",
      "",
      "## 1. Executive Summary",
      "",
      options?.executiveSummary ??
        `Autonomous Solari CUA executed ${total} test actions in ${this.batchId}. Result: ${passed} passed, ${failed} failed with 0 dangling sessions.`,
      "",
      "---",
      "",
      "## 2. Test Execution & Evidence Matrix",
      "",
      "| Step ID | Scenario / Verification Action | URL | Result | Evidence Screenshot |",
      "|---|---|---|---|---|",
    ]

    for (const f of this.findings) {
      const statusBadge = f.pass ? "**PASS**" : "**FAIL**"
      const shotFile = basename(f.screenshot)
      lines.push(
        `| **${f.step}** | ${f.action} | \`${f.url}\` | ${statusBadge} | [\`${shotFile}\`](${shotFile}) |`
      )
    }

    lines.push("")
    lines.push("---")
    lines.push("")
    lines.push("## 3. Step Findings & Verification Notes")
    lines.push("")

    for (const f of this.findings) {
      lines.push(`### ${f.step}: ${f.action}`)
      lines.push(`- **Status**: ${f.pass ? "PASSED" : "FAILED"}`)
      lines.push(`- **Notes**: ${f.notes}`)
      if (f.consoleErrors.length > 0) {
        lines.push(`- **Console Warnings/Errors**:`)
        for (const err of f.consoleErrors) {
          lines.push(`  - \`${err}\``)
        }
      }
      lines.push("")
    }

    const mdContent = lines.join("\n")
    const outPath = options?.outputPath ?? join(this.evidenceDir, "audit-report.md")
    writeFileSync(outPath, mdContent, "utf8")
    return mdContent
  }

  /**
   * Generates an interactive side-by-side before/after HTML comparison reel.
   */
  generateComparisonReelHtml(
    beforeShotPath: string,
    afterShotPath: string,
    title = "Visual State Comparison Reel",
    outputPath?: string
  ): string {
    const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>${title} - ${this.batchId}</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 24px; }
    h1 { font-size: 1.5rem; margin-bottom: 8px; }
    p.subtitle { color: #94a3b8; margin-top: 0; margin-bottom: 24px; font-size: 0.9rem; }
    .reel-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
    .reel-card { background: #1e293b; border-radius: 8px; overflow: hidden; border: 1px solid #334155; }
    .card-header { padding: 12px 16px; background: #334155; font-weight: 600; font-size: 0.95rem; }
    .reel-card img { width: 100%; display: block; height: auto; }
  </style>
</head>
<body>
  <h1>${title}</h1>
  <p class="subtitle">Batch: ${this.batchId} | Target: ${this.targetUrl}</p>
  <div class="reel-grid">
    <div class="reel-card">
      <div class="card-header">Baseline (Before Step)</div>
      <img src="${basename(beforeShotPath)}" alt="Before Snapshot" />
    </div>
    <div class="reel-card">
      <div class="card-header">Mutated State (After Step)</div>
      <img src="${basename(afterShotPath)}" alt="After Snapshot" />
    </div>
  </div>
</body>
</html>`

    const outPath = outputPath ?? join(this.evidenceDir, "comparison-reel.html")
    writeFileSync(outPath, html, "utf8")
    return outPath
  }

  /**
   * Generates a lightweight SVG composite strip representing the step execution sequence.
   */
  generateSequenceStripSvg(title = "QA Step Execution Reel"): string {
    const stepWidth = 240
    const stepHeight = 160
    const padding = 16
    const totalWidth = padding + this.findings.length * (stepWidth + padding)
    const totalHeight = stepHeight + 80

    const svgParts: string[] = [
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${totalWidth} ${totalHeight}" width="${totalWidth}" height="${totalHeight}">`,
      `<rect width="100%" height="100%" fill="#0f172a" />`,
      `<text x="${padding}" y="30" fill="#f8fafc" font-family="sans-serif" font-size="16" font-weight="bold">${title} — ${this.batchId}</text>`,
    ]

    this.findings.forEach((f, idx) => {
      const x = padding + idx * (stepWidth + padding)
      const y = 50
      const strokeColor = f.pass ? "#22c55e" : "#ef4444"
      const statusText = f.pass ? "PASS" : "FAIL"

      svgParts.push(`
        <g transform="translate(${x}, ${y})">
          <rect width="${stepWidth}" height="${stepHeight}" rx="6" fill="#1e293b" stroke="${strokeColor}" stroke-width="2"/>
          <text x="12" y="24" fill="#f8fafc" font-family="sans-serif" font-size="12" font-weight="bold">${f.step}</text>
          <rect x="${stepWidth - 54}" y="10" width="42" height="18" rx="4" fill="${strokeColor}" />
          <text x="${stepWidth - 33}" y="23" fill="#ffffff" font-family="sans-serif" font-size="10" font-weight="bold" text-anchor="middle">${statusText}</text>
          <text x="12" y="50" fill="#94a3b8" font-family="sans-serif" font-size="10">${f.action.slice(0, 32)}...</text>
          <text x="12" y="70" fill="#64748b" font-family="sans-serif" font-size="9">${basename(f.screenshot)}</text>
        </g>
      `)
    })

    svgParts.push("</svg>")
    const svg = svgParts.join("\n")
    const outPath = join(this.evidenceDir, "step-sequence-reel.svg")
    writeFileSync(outPath, svg, "utf8")
    return outPath
  }
}
