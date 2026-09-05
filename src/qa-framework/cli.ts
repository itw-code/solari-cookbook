#!/usr/bin/env node
/**
 * cli.ts — ColdStart Autonomous QA Automation CLI
 *
 * Usage:
 *   npx tsx src/qa-framework/cli.ts tunnel <port>
 *   npx tsx src/qa-framework/cli.ts heuristics --report <path-to-report.json>
 *   npx tsx src/qa-framework/cli.ts diff --before <img1> --after <img2> [--out <path>]
 */

import { readFileSync } from "node:fs"
import { startTunnel } from "./tunnel.js"
import { HeuristicEngine } from "./heuristics.js"
import { ArtifactArchiver } from "./archiver.js"

async function main() {
  const args = process.argv.slice(2)
  const command = args[0]

  if (!command || command === "--help" || command === "-h") {
    printHelp()
    process.exit(0)
  }

  if (command === "tunnel") {
    const portArg = args[1]
    if (!portArg) {
      console.error("Error: tunnel requires a port argument (e.g. coldstart tunnel 4310)")
      process.exit(1)
    }
    const port = parseInt(portArg, 10)
    if (isNaN(port)) {
      console.error(`Error: Invalid port '${portArg}'.`)
      process.exit(1)
    }

    console.log(`[ColdStart CLI] Booting autonomous ingress tunnel for port ${port}...`)
    try {
      const tunnel = await startTunnel(port, { debug: true })
      console.log(`\nTunnel active at: ${tunnel.url}`)
      console.log("Press Ctrl+C to terminate tunnel.\n")

      const cleanup = async () => {
        console.log("\n[ColdStart CLI] Stopping tunnel daemon...")
        await tunnel.stop()
        process.exit(0)
      }

      process.on("SIGINT", cleanup)
      process.on("SIGTERM", cleanup)
    } catch (err: any) {
      console.error(`Failed to boot tunnel: ${err.message}`)
      process.exit(1)
    }
    return
  }

  if (command === "heuristics") {
    const reportIndex = args.indexOf("--report")
    if (reportIndex === -1 || !args[reportIndex + 1]) {
      console.error("Error: heuristics requires --report <path-to-report.json>")
      process.exit(1)
    }
    const reportPath = args[reportIndex + 1]
    const content = JSON.parse(readFileSync(reportPath, "utf8"))

    const engine = new HeuristicEngine()
    // Run automated heuristics on report findings
    for (const f of content.findings || []) {
      if (f.action.toLowerCase().includes("delete") || f.action.toLowerCase().includes("cleanup")) {
        engine.inspectDestructiveGuard({
          route: f.url || "/unknown",
          actionName: f.action,
          hasConfirmationModal: f.notes.toLowerCase().includes("guard") || f.notes.toLowerCase().includes("confirm"),
          hasCancelDefaultFocus: true,
        })
      }
      if (f.action.toLowerCase().includes("empty state") || f.action.toLowerCase().includes("initial")) {
        engine.inspectEmptyState({
          route: f.url || "/unknown",
          containerName: f.action,
          itemCount: 0,
          hasActionableCta: f.notes.toLowerCase().includes("create") || f.notes.toLowerCase().includes("button"),
          hasStarterTemplates: f.notes.toLowerCase().includes("template"),
          displayedCopy: "Select an automation to view runs",
        })
      }
      if (f.action.toLowerCase().includes("submit") || f.action.toLowerCase().includes("form") || f.action.toLowerCase().includes("edit")) {
        engine.inspectFormValidation({
          route: f.url || "/unknown",
          formName: f.action,
          hasInlineDebounce: true,
          hasValidationFeedback: true,
          hasClearErrorState: true,
        })
      }
    }

    const md = engine.formatMarkdown()
    console.log(md)
    return
  }

  if (command === "diff") {
    const beforeIdx = args.indexOf("--before")
    const afterIdx = args.indexOf("--after")
    const outIdx = args.indexOf("--out")

    if (beforeIdx === -1 || afterIdx === -1) {
      console.error("Error: diff requires --before <imagePath> and --after <imagePath>")
      process.exit(1)
    }

    const beforeImg = args[beforeIdx + 1]
    const afterImg = args[afterIdx + 1]
    const outPath = outIdx !== -1 ? args[outIdx + 1] : "comparison-reel.html"

    const archiver = new ArtifactArchiver({ batchId: "cli-diff", targetUrl: "localhost" })
    const created = archiver.generateComparisonReelHtml(beforeImg, afterImg, "Visual Comparison", outPath)
    console.log(`[ColdStart CLI] Comparison reel generated: ${created}`)
    return
  }

  console.error(`Unknown command: '${command}'`)
  printHelp()
  process.exit(1)
}

function printHelp() {
  console.log(`
ColdStart Autonomous QA Automation CLI

Usage:
  coldstart tunnel <port>                       Boot autonomous Cloudflare quick tunnel & export TARGET_URL
  coldstart heuristics --report <file.json>     Run UX heuristic analyzer on QA report
  coldstart diff --before <img1> --after <img2> Generate visual comparison reel
  coldstart --help                              Show this help message
`)
}

main().catch((err) => {
  console.error("Fatal:", err)
  process.exit(1)
})
