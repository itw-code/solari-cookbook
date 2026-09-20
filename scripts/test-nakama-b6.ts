/**
 * test-nakama-b6.ts — Solari Cloud Browser E2E QA runner for Nakama Batch 6
 *
 * System, Integrations, Settings & Full Surface Verification
 * Tests:
 * 1. B6-01: Settings Page (/settings, ThemeToggle, Timezone, ProviderSettingsCard, DataPortability)
 * 2. B6-02: Integrations Page (/integrations, Telegram, WhatsApp, Discord, Composio, Local Token)
 * 3. B6-03: System Hub (/system, ToolsTab registered builtins, McpTab, Usage tab)
 * 4. B6-04: Tool Playground (/system/playground/web_search, schema form, param inputs, execution panel)
 * 5. B6-05: Notifications Page (/notifications, feed view & empty state)
 * 6. B6-06: Full Surface Navigation Integrity Loop (all top-level routes, zero unhandled errors)
 */
import { Solari } from "@solarisdk/browser"
import Database from "bun:sqlite"
import { existsSync, mkdirSync, unlinkSync, writeFileSync } from "node:fs"
import { homedir } from "node:os"
import { resolve, join } from "node:path"

const TARGET_URL =
  process.env.TARGET_URL ?? "https://won-excluded-premises-writer.trycloudflare.com"
const EVIDENCE_DIR = resolve("C:/Users/oneda/Projects/OSS/nakama/qa-evidence/solari-b6")
mkdirSync(EVIDENCE_DIR, { recursive: true })

const DB_PATH = join(homedir(), ".nakama", "data", "sqlite", "nakama.sqlite")
const TOOL_FILE = join(homedir(), ".nakama", "tools", "tool_qa_echo.js")

function cleanupCustomTool() {
  if (existsSync(DB_PATH)) {
    try {
      const db = new Database(DB_PATH)
      db.query("DELETE FROM tools WHERE id = 'tool_qa_echo'").run()
      db.close()
    } catch {}
  }
  if (existsSync(TOOL_FILE)) {
    try {
      unlinkSync(TOOL_FILE)
    } catch {}
  }
}

function seedCustomTool() {
  const toolsDir = join(homedir(), ".nakama", "tools")
  mkdirSync(toolsDir, { recursive: true })
  writeFileSync(TOOL_FILE, "export async function run(input, context) { return { ok: true, echo: input.query }; }")
  const db = new Database(DB_PATH)
  const now = new Date().toISOString()
  db.query(`
    INSERT OR REPLACE INTO tools (id, name, description, handler_type, handler_config, created_at, updated_at, org_id)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
  `).run(
    "tool_qa_echo",
    "qa_echo",
    "QA Echo tool for playground verification",
    "javascript",
    JSON.stringify({
      modulePath: "tool_qa_echo.js",
      parameters: {
        type: "object",
        properties: { query: { type: "string", description: "Echo query input" } },
        required: ["query"],
      },
    }),
    now,
    now,
    "org_0d1b7bae4b414138b8af227e18a3653f"
  )
  db.close()
}

interface StepFinding {
  step: string
  action: string
  url: string
  screenshot: string
  pass: boolean
  notes: string
  consoleErrors: string[]
}

async function handleChunkReload(page: any) {
  const reloadBtn = page.locator('button:has-text("Reload")')
  if ((await reloadBtn.count()) > 0) {
    console.log("[Helper] Chunk reload prompt detected, clicking...")
    await reloadBtn.first().click()
    await page.waitForLoadState("networkidle")
    await page.waitForTimeout(2000)
  }
}

async function run() {
  const apiKey = process.env.SOLARI_API_KEY
  if (!apiKey) {
    console.error("SOLARI_API_KEY is required")
    process.exit(1)
  }

  console.log("==================================================================")
  console.log("SOLARI CUA BATCH 6 AUDIT: SYSTEM, INTEGRATIONS AND SETTINGS")
  console.log(`Target URL: ${TARGET_URL}`)
  console.log(`Evidence Directory: ${EVIDENCE_DIR}`)
  console.log("==================================================================")

  const solari = new Solari({ apiKey })
  console.log("[Solari] Launching cloud browser session with recording...")
  const browser = await solari.launch({ recording: true })
  console.log(`[Solari] Connected to cloud browser session: ${browser.id}`)

    const authBootstrapErrors: string[] = []
    const consoleErrors: string[] = []
    let authEstablished = false

    function recordConsoleError(message: string) {
      const bucket = authEstablished ? consoleErrors : authBootstrapErrors
      bucket.push(message)
    }

  try {
    const page = await browser.newPage()
    await page.setViewportSize({ width: 1280, height: 800 })

    page.on("console", (msg) => {
      if (msg.type() === "error") {
        recordConsoleError(msg.text())
      }
    })

    page.on("pageerror", (err) => {
      console.error(`[Browser Page Error] ${err.message}`)
      recordConsoleError(err.message)
    })

    // Establish auth first
    console.log("\n[Auth] Logging in as Platform Admin...")
    await page.goto(`${TARGET_URL}/login`, { waitUntil: "networkidle" })
    const emailInput = page.locator('input[type="email"], input[name="email"]')
    const passInput = page.locator('input[type="password"], input[name="password"]')
    const submitBtn = page.locator('button[type="submit"]')

    await emailInput.first().fill("ihsantriwanda@gmail.com")
    await passInput.first().fill("ihsan3wanda")
    await submitBtn.first().click()
    await page.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 20000 })
    await page.waitForLoadState("networkidle")
    console.log(`[Auth] Reached: ${page.url()}`)
    authEstablished = true

    const findings: StepFinding[] = []

    // ------------------------------------------------------------------------
    // STEP 1: Settings Page (/settings)
    // ------------------------------------------------------------------------
    console.log("\n[Step 1] Navigating to /settings ...")
    await page.goto(`${TARGET_URL}/settings`, { waitUntil: "networkidle" })
    await page.waitForTimeout(1500)
    await handleChunkReload(page)

    const appearanceSection = page.locator(':text("Appearance")')
    const hasAppearance = (await appearanceSection.count()) > 0

    const providersSection = page.locator(':text("Providers"), :text("LLM Providers"), :text("Models")')
    const hasProviders = (await providersSection.count()) > 0

    const timezoneSection = page.locator(':text("Timezone")')
    const hasTimezone = (await timezoneSection.count()) > 0

    const shotStep1 = "01-settings-overview.png"
    await page.screenshot({ path: join(EVIDENCE_DIR, shotStep1) })

    findings.push({
      step: "B6-01",
      action: "Inspect Settings page, appearance, timezone and providers card",
      url: page.url(),
      screenshot: shotStep1,
      pass: hasAppearance && (hasProviders || hasTimezone),
      notes: `Settings rendered. Appearance toggle: ${hasAppearance}, Providers card: ${hasProviders}, Timezone selector: ${hasTimezone}.`,
      consoleErrors: [...consoleErrors],
    })
    console.log(`[Step 1] Finished: hasAppearance=${hasAppearance}, hasProviders=${hasProviders}, hasTimezone=${hasTimezone}`)

    // ------------------------------------------------------------------------
    // STEP 2: Integrations Page (/integrations)
    // ------------------------------------------------------------------------
    console.log("\n[Step 2] Navigating to /integrations ...")
    await page.goto(`${TARGET_URL}/integrations`, { waitUntil: "networkidle" })
    await page.waitForTimeout(1500)
    await handleChunkReload(page)

    const telegramCard = page.locator(':text("Telegram")')
    const hasTelegram = (await telegramCard.count()) > 0

    const whatsappCard = page.locator(':text("WhatsApp")')
    const hasWhatsapp = (await whatsappCard.count()) > 0

    const discordCard = page.locator(':text("Discord")')
    const hasDiscord = (await discordCard.count()) > 0

    const composioCard = page.locator(':text("Composio")')
    const hasComposio = (await composioCard.count()) > 0

    const tokenCard = page.locator(':text("Local token"), :text("Local Token")')
    const hasToken = (await tokenCard.count()) > 0

    const shotStep2 = "02-integrations-overview.png"
    await page.screenshot({ path: join(EVIDENCE_DIR, shotStep2) })

    findings.push({
      step: "B6-02",
      action: "Inspect Integrations cards for messaging channels and connectors",
      url: page.url(),
      screenshot: shotStep2,
      pass: hasTelegram && hasWhatsapp && hasDiscord && hasComposio,
      notes: `Integrations cards rendered: Telegram=${hasTelegram}, WhatsApp=${hasWhatsapp}, Discord=${hasDiscord}, Composio=${hasComposio}, LocalToken=${hasToken}.`,
      consoleErrors: [...consoleErrors],
    })
    console.log(`[Step 2] Finished: hasTelegram=${hasTelegram}, hasWhatsapp=${hasWhatsapp}, hasDiscord=${hasDiscord}, hasComposio=${hasComposio}`)

    // ------------------------------------------------------------------------
    // STEP 3: System Page (/system)
    // ------------------------------------------------------------------------
    console.log("\n[Step 3] Navigating to /system ...")
    await page.goto(`${TARGET_URL}/system`, { waitUntil: "networkidle" })
    await page.waitForTimeout(1500)
    await handleChunkReload(page)

    const toolsTabBtn = page.locator('button:has-text("Tools")')
    const hasToolsTab = (await toolsTabBtn.count()) > 0

    const mcpTabBtn = page.locator('button:has-text("MCP")')
    const hasMcpTab = (await mcpTabBtn.count()) > 0

    // Inspect tools table or list
    const toolRows = page.locator('table tr, [role="row"], .rounded-md')
    const hasToolsList = (await toolRows.count()) > 0

    const shotStep3 = "03-system-tools-tab.png"
    await page.screenshot({ path: join(EVIDENCE_DIR, shotStep3) })

    // Click MCP tab to inspect MCP servers
    if (hasMcpTab) {
      await mcpTabBtn.first().click()
      await page.waitForTimeout(1000)
      const shotStep3Mcp = "04-system-mcp-tab.png"
      await page.screenshot({ path: join(EVIDENCE_DIR, shotStep3Mcp) })
    }

    findings.push({
      step: "B6-03",
      action: "Inspect System page, Tools catalog and MCP server management tabs",
      url: page.url(),
      screenshot: shotStep3,
      pass: hasToolsTab && hasToolsList,
      notes: `System page rendered. Tools tab: ${hasToolsTab}, MCP tab: ${hasMcpTab}, Registered tools/items visible: ${hasToolsList}.`,
      consoleErrors: [...consoleErrors],
    })
    console.log(`[Step 3] Finished: hasToolsTab=${hasToolsTab}, hasMcpTab=${hasMcpTab}, hasToolsList=${hasToolsList}`)

    // ------------------------------------------------------------------------
    // STEP 4: Tool Playground (/system/playground/tool_qa_echo)
    // ------------------------------------------------------------------------
    console.log("\n[Step 4] Seeding custom tool and navigating to /system/playground/tool_qa_echo ...")
    seedCustomTool()
    await page.goto(`${TARGET_URL}/system/playground/tool_qa_echo`, { waitUntil: "networkidle" })
    await page.waitForTimeout(1500)
    await handleChunkReload(page)

    const hasParamsJson = (await page.locator(':text("Parameters (JSON)")').count()) > 0
    const hasSuggestBtn = (await page.locator(':text("Suggest params")').count()) > 0
    const hasRunBtn = (await page.locator('button:has-text("Run")').count()) > 0
    const hasPlayground = hasParamsJson || hasSuggestBtn

    const shotStep4 = "05-tool-playground-runner.png"
    await page.screenshot({ path: join(EVIDENCE_DIR, shotStep4) })

    findings.push({
      step: "B6-04",
      action: "Inspect Tool Playground parameter form, runner controls and schema",
      url: page.url(),
      screenshot: shotStep4,
      pass: hasPlayground && hasRunBtn,
      notes: `Tool Playground rendered for qa_echo custom tool: form=${hasPlayground}, execute/run button=${hasRunBtn}.`,
      consoleErrors: [...consoleErrors],
    })
    console.log(`[Step 4] Finished: hasPlayground=${hasPlayground}, hasRunBtn=${hasRunBtn}`)

    // ------------------------------------------------------------------------
    // STEP 5: Notifications Page (/notifications)
    // ------------------------------------------------------------------------
    console.log("\n[Step 5] Navigating to /notifications ...")
    await page.goto(`${TARGET_URL}/notifications`, { waitUntil: "networkidle" })
    await page.waitForTimeout(1500)
    await handleChunkReload(page)

    const emptyNotice = page.locator(':text("All caught up"), :text("No notifications")')
    const notifItems = page.locator('[role="listitem"], .divide-y > div')
    const hasEmpty = (await emptyNotice.count()) > 0
    const hasItems = (await notifItems.count()) > 0

    const shotStep5 = "06-notifications-page.png"
    await page.screenshot({ path: join(EVIDENCE_DIR, shotStep5) })

    findings.push({
      step: "B6-05",
      action: "Inspect Notifications page feed and empty-state feedback",
      url: page.url(),
      screenshot: shotStep5,
      pass: hasEmpty || hasItems,
      notes: `Notifications view rendered: empty state ("All caught up")=${hasEmpty}, items count=${await notifItems.count()}.`,
      consoleErrors: [...consoleErrors],
    })
    console.log(`[Step 5] Finished: hasEmpty=${hasEmpty}, hasItems=${hasItems}`)

    // ------------------------------------------------------------------------
    // STEP 6: Full Surface Navigation Integrity Loop
    // ------------------------------------------------------------------------
    console.log("\n[Step 6] Running full platform navigation integrity loop...")
    const routesToTest = [
      "/chat",
      "/history",
      "/profiles",
      "/automations",
      "/workers",
      "/files",
      "/organization",
      "/settings",
      "/system",
      "/integrations",
      "/notifications",
    ]

    let navigationPass = true
    const navResults: string[] = []
    const navigationErrorStart = consoleErrors.length

    for (const route of routesToTest) {
      console.log(`   Navigating to ${route} ...`)
      await page.goto(`${TARGET_URL}${route}`, { waitUntil: "networkidle" })
      await page.waitForTimeout(1000)
      await handleChunkReload(page)

      const crashed = (await page.locator(':text("Something went wrong"), :text("ChunkLoadError")').count()) > 0
      if (crashed) {
        navigationPass = false
        navResults.push(`${route}: CRASHED`)
      } else {
        navResults.push(`${route}: OK`)
      }
    }

    const navigationConsoleErrors = consoleErrors.slice(navigationErrorStart)
    navigationPass = navigationPass && navigationConsoleErrors.length === 0

    const shotStep6 = "07-navigation-loop-complete.png"
    await page.screenshot({ path: join(EVIDENCE_DIR, shotStep6) })

    findings.push({
      step: "B6-06",
      action: "Execute full navigation loop across all 11 primary platform routes",
      url: page.url(),
      screenshot: shotStep6,
      pass: navigationPass,
      notes: `Navigation loop completed across ${routesToTest.length} routes: ${navResults.join(", ")}; post-auth console errors=${navigationConsoleErrors.length}.`,
      consoleErrors: navigationConsoleErrors,
    })
    console.log(`[Step 6] Finished: navigationPass=${navigationPass}`)

    console.log("\n==================================================================")
    console.log("BATCH 6 SUMMARY OF RESULTS")
    console.log("==================================================================")
    for (const f of findings) {
      console.log(`[${f.pass ? "PASS" : "FAIL"}] ${f.step} - ${f.action} (${f.screenshot})`)
      console.log(`       URL: ${f.url}`)
      console.log(`       Notes: ${f.notes}`)
    }

    const report = {
      batch: "Batch 6: System, Integrations, Settings and Full Surface Verification",
      timestamp: new Date().toISOString(),
      sessionId: browser.id,
      replayUrl: null,
      targetUrl: TARGET_URL,
      authBootstrapErrors,
      findings,
      totalFindings: findings.length,
      passed: findings.filter((f) => f.pass).length,
      failed: findings.filter((f) => !f.pass).length,
    }

    const reportPath = join(EVIDENCE_DIR, "report.json")
    writeFileSync(reportPath, JSON.stringify(report, null, 2))
    console.log(`\nReport written to: ${reportPath}`)
  } finally {
    console.log("\n[Teardown] Cleaning up custom tool and releasing cloud browser session...")
    cleanupCustomTool()
    await browser.close()
    console.log("[Solari] Session closed.")
  }
}

run().catch((err) => {
  console.error("[Fatal Error]", err)
  process.exit(1)
})
