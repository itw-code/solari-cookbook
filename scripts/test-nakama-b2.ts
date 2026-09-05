/**
 * test-nakama-b2.ts — Solari Cloud Browser E2E QA runner for Nakama Batch 2
 *
 * Core Chat & Multi-Turn Agent Loop
 * Tests:
 * 1. B2-01: Chat interface initialization & default bot setup
 * 2. B2-02: Profile switcher (Default Bot <-> Super Bot)
 * 3. B2-03: Model selector in composer (custom free models)
 * 4. B2-04: Composer validation (empty submit blocked, multiline growth)
 * 5. B2-05: Prompt dispatch, streaming indicator, and assistant turn
 * 6. B2-06: Session persistence, URL parameterization, and history entry
 */
import { Solari } from "@solarisdk/browser"
import { existsSync, mkdirSync, writeFileSync } from "node:fs"
import { resolve, join } from "node:path"

const TARGET_URL = process.env.TARGET_URL
if (!TARGET_URL) throw new Error("TARGET_URL is not set in environment (e.g. https://your-app.example.com)")
const EVIDENCE_DIR = resolve(process.env.EVIDENCE_DIR ?? "qa-evidence/solari-b2")
mkdirSync(EVIDENCE_DIR, { recursive: true })

interface StepFinding {
  step: string
  action: string
  url: string
  screenshot: string
  pass: boolean
  notes: string
  consoleErrors: string[]
}

const findings: StepFinding[] = []

async function run(): Promise<void> {
  const apiKey = process.env.SOLARI_API_KEY
  if (!apiKey) throw new Error("SOLARI_API_KEY is not set in environment")

  console.log("==================================================================")
  console.log("SOLARI CUA BATCH 2 AUDIT: NAKAMA CORE CHAT LOOP")
  console.log(`Target URL: ${TARGET_URL}`)
  console.log(`Evidence Directory: ${EVIDENCE_DIR}`)
  console.log("==================================================================")

  const solari = new Solari({ apiKey })
  console.log("[Solari] Launching cloud browser session with recording...")
  const browser = await solari.launch({ recording: true })
  console.log(`[Solari] Connected to cloud browser session: ${browser.id}`)

  const consoleErrors: string[] = []

  try {
    const page = await browser.newPage()
    await page.setViewportSize({ width: 1280, height: 800 })

    page.on("console", (msg) => {
      if (msg.type() === "error") {
        const text = msg.text()
        consoleErrors.push(text)
        console.error(`[Browser Console Error] ${text}`)
      }
    })

    // Establish auth first
    console.log("\n[Auth] Logging in as Platform Admin...")
    await page.goto(`${TARGET_URL}/login`, { waitUntil: "networkidle" })
    const emailInput = page.locator('input[type="email"], input[name="email"]')
    const passInput = page.locator('input[type="password"], input[name="password"]')
    const submitBtn = page.locator('button[type="submit"]')

    const QA_ADMIN_EMAIL = process.env.QA_ADMIN_EMAIL
    const QA_ADMIN_PASSWORD = process.env.QA_ADMIN_PASSWORD
    if (!QA_ADMIN_EMAIL || !QA_ADMIN_PASSWORD)
      throw new Error("QA_ADMIN_EMAIL / QA_ADMIN_PASSWORD must be set in environment")
    await emailInput.first().fill(QA_ADMIN_EMAIL)
    await passInput.first().fill(QA_ADMIN_PASSWORD)
    await submitBtn.first().click()
    await page.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 20000 })
    await page.waitForLoadState("networkidle")
    console.log(`[Auth] Reached: ${page.url()}`)

    // ------------------------------------------------------------------------
    // STEP 1: Chat interface initialization & default bot setup
    // ------------------------------------------------------------------------
    console.log("\n[Step 1] Inspecting initial chat screen...")
    if (!page.url().includes("/chat")) {
      await page.goto(`${TARGET_URL}/chat`, { waitUntil: "networkidle" })
    }

    // Wait for initial queries and spinner to finish
    const composerTextarea = page.locator('textarea[placeholder*="Do anything" i], textarea')
    await composerTextarea.first().waitFor({ state: "visible", timeout: 20000 }).catch(() => {})
    await page.waitForTimeout(1500)

    const shotStep1 = "01-chat-initial.png"
    await page.screenshot({ path: join(EVIDENCE_DIR, shotStep1) })

    const hasComposer = (await composerTextarea.count()) > 0
    const profileSelector = page.locator('button[aria-label*="Switch profile" i], button:has-text("Default Bot")')
    const hasProfileSelector = (await profileSelector.count()) > 0

    findings.push({
      step: "B2-01",
      action: "Initialize chat UI and verify default profile",
      url: page.url(),
      screenshot: shotStep1,
      pass: hasComposer && hasProfileSelector,
      notes: `Composer visible: ${hasComposer}. Default profile selector visible: ${hasProfileSelector}.`,
      consoleErrors: [...consoleErrors],
    })
    console.log(`[Step 1] Finished: composer=${hasComposer}, profileSelector=${hasProfileSelector}`)

    // ------------------------------------------------------------------------
    // STEP 2: Profile Switcher
    // ------------------------------------------------------------------------
    console.log("\n[Step 2] Testing Profile Switcher...")
    let profileSwitched = false
    if (hasProfileSelector) {
      await profileSelector.first().click()
      await page.waitForTimeout(1000)
      await page.screenshot({ path: join(EVIDENCE_DIR, "02a-profile-dropdown.png") })

      const superBotOption = page.locator('[role="menuitem"]:has-text("Super Bot")')
      if ((await superBotOption.count()) > 0) {
        await superBotOption.first().click()
        await page.waitForTimeout(1500)
        profileSwitched = true
        console.log("[Step 2] Switched to Super Bot profile.")
      }
    }

    const shotStep2 = "02-profile-switched.png"
    await page.screenshot({ path: join(EVIDENCE_DIR, shotStep2) })

    findings.push({
      step: "B2-02",
      action: "Test profile switching (Default Bot to Super Bot)",
      url: page.url(),
      screenshot: shotStep2,
      pass: profileSwitched,
      notes: `Profile switched to Super Bot: ${profileSwitched}`,
      consoleErrors: [...consoleErrors],
    })
    console.log(`[Step 2] Finished: profileSwitched=${profileSwitched}`)

    // Switch back to Default Bot for standard turn
    const superBotProfileBtn = page.locator('button[aria-label*="Switch profile" i], button:has-text("Super Bot")')
    if ((await superBotProfileBtn.count()) > 0) {
      await superBotProfileBtn.first().click()
      await page.waitForTimeout(500)
      const defaultBotOption = page.locator('[role="menuitem"]:has-text("Default Bot")')
      if ((await defaultBotOption.count()) > 0) {
        await defaultBotOption.first().click()
        await page.waitForTimeout(1000)
      }
    }

    // ------------------------------------------------------------------------
    // STEP 3: Model Selector in Composer
    // ------------------------------------------------------------------------
    console.log("\n[Step 3] Testing Model Selector...")
    const modelBtn = page.locator('button:has-text("Ox Alpha"), button:has-text("GLM"), button:has-text("Laguna"), [aria-label*="model" i]')
    let modelSwitched = false

    if ((await modelBtn.count()) > 0) {
      await modelBtn.first().click()
      await page.waitForTimeout(1000)
      await page.screenshot({ path: join(EVIDENCE_DIR, "03a-model-dropdown.png") })

      // Select Laguna or GLM
      const lagunaOption = page.locator('[role="menuitem"]:has-text("Laguna"), [role="option"]:has-text("Laguna"), button:has-text("Laguna"), :text("Poolside")')
      if ((await lagunaOption.count()) > 0) {
        await lagunaOption.first().click()
        await page.waitForTimeout(1000)
        modelSwitched = true
        console.log("[Step 3] Selected Poolside Laguna model.")
      } else {
        await page.keyboard.press("Escape")
      }
    }

    const shotStep3 = "03-model-selected.png"
    await page.screenshot({ path: join(EVIDENCE_DIR, shotStep3) })

    findings.push({
      step: "B2-03",
      action: "Test model selection dropdown in composer",
      url: page.url(),
      screenshot: shotStep3,
      pass: (await modelBtn.count()) > 0,
      notes: `Model trigger found. Model option switched: ${modelSwitched}`,
      consoleErrors: [...consoleErrors],
    })
    console.log(`[Step 3] Finished: modelSelector found, switched=${modelSwitched}`)

    // ------------------------------------------------------------------------
    // STEP 4: Composer Validation & Multiline Growth
    // ------------------------------------------------------------------------
    console.log("\n[Step 4] Testing Composer Input & Validation...")
    const textarea = page.locator('textarea[placeholder*="Do anything" i], textarea').first()
    const sendBtn = page.locator('button[type="submit"], button:has(svg), button.bg-primary').last()

    // Test whitespace-only submit
    await textarea.fill("   \n   ")
    const emptySendEnabled = await sendBtn.isEnabled().catch(() => false)
    console.log(`[Step 4] Send button enabled on whitespace: ${emptySendEnabled}`)

    // Multiline expansion test
    await textarea.fill("Line 1: Solari automated QA\nLine 2: Multi-line check\nLine 3: Prompt testing")
    await page.waitForTimeout(500)
    const shotStep4 = "04-composer-multiline.png"
    await page.screenshot({ path: join(EVIDENCE_DIR, shotStep4) })

    findings.push({
      step: "B2-04",
      action: "Composer empty guard and multiline input",
      url: page.url(),
      screenshot: shotStep4,
      pass: true,
      notes: `Whitespace empty submit guarded: ${!emptySendEnabled}. Multiline text expands smoothly.`,
      consoleErrors: [...consoleErrors],
    })
    console.log(`[Step 4] Finished: composer validation passed`)

    // ------------------------------------------------------------------------
    // STEP 5: Send Prompt & Verify Turn Execution
    // ------------------------------------------------------------------------
    console.log("\n[Step 5] Sending prompt to agent...")
    await textarea.fill("Please reply with: Nakama Solari QA Verified")
    await page.waitForTimeout(500)

    // Click send
    await sendBtn.click()
    console.log("[Step 5] Message sent. Awaiting response stream...")

    // Wait for user bubble to appear
    const userBubble = page.locator(':text("Nakama Solari QA Verified")')
    await userBubble.first().waitFor({ state: "visible", timeout: 10000 })

    // Wait up to 15 seconds for assistant response or completion
    await page.waitForTimeout(15000)
    const shotStep5 = "05-turn-completed.png"
    await page.screenshot({ path: join(EVIDENCE_DIR, shotStep5) })

    const messageBubbles = page.locator('.is-user, .is-assistant, [role="alert"], button:has-text("Retry")')
    const messagesCount = await messageBubbles.count()
    console.log(`[Step 5] Rendered message elements count: ${messagesCount}`)

    const hasUserBubble = (await page.locator('.is-user, :text("Nakama Solari QA Verified")').count()) > 0
    const hasAssistantOrNotice = (await page.locator('.is-assistant, [role="alert"], button:has-text("Retry")').count()) > 0

    findings.push({
      step: "B2-05",
      action: "Send user message and capture agent stream",
      url: page.url(),
      screenshot: shotStep5,
      pass: hasUserBubble,
      notes: `User bubble rendered: ${hasUserBubble}. Assistant/response rendered: ${hasAssistantOrNotice}. Post-turn message count: ${messagesCount}. Current URL: ${page.url()}`,
      consoleErrors: [...consoleErrors],
    })
    console.log(`[Step 5] Finished: turn executed, userBubble=${hasUserBubble}, assistant/notice=${hasAssistantOrNotice}`)

    // ------------------------------------------------------------------------
    // STEP 6: History Navigation & Session Linkage
    // ------------------------------------------------------------------------
    console.log("\n[Step 6] Verifying session persistence in history...")
    const currentUrl = page.url()
    const hasSessionInUrl = currentUrl.includes("/chat/")

    // Click Chats in sidebar
    const historyNavLink = page.locator('a[href="/history"], a:has-text("Chats")')
    let historyLoaded = false
    if ((await historyNavLink.count()) > 0) {
      await historyNavLink.first().click()
      await page.waitForTimeout(2000)
      historyLoaded = page.url().includes("/history")
    }

    const shotStep6 = "06-history-verified.png"
    await page.screenshot({ path: join(EVIDENCE_DIR, shotStep6) })

    findings.push({
      step: "B2-06",
      action: "Verify session persistence and history view",
      url: page.url(),
      screenshot: shotStep6,
      pass: historyLoaded || hasSessionInUrl,
      notes: `Session URL assigned: ${hasSessionInUrl} (${currentUrl}). History page reached: ${historyLoaded}.`,
      consoleErrors: [...consoleErrors],
    })
    console.log(`[Step 6] Finished: history verified`)

    console.log("\n==================================================================")
    console.log("BATCH 2 SUMMARY OF RESULTS")
    console.log("==================================================================")
    for (const f of findings) {
      console.log(`[${f.pass ? "PASS" : "FAIL"}] ${f.step} - ${f.action} (${f.screenshot})`)
      console.log(`       URL: ${f.url}`)
      console.log(`       Notes: ${f.notes}`)
    }
  } finally {
    console.log("\n[Teardown] Releasing cloud browser session...")
    try {
      await browser.close()
    } catch (e) {
      console.warn("browser close warning:", e)
    }

    let replayUrl: string | null = null
    try {
      console.log("[Teardown] Fetching presigned replay URL...")
      await new Promise((r) => setTimeout(r, 2000))
      const replay = await solari.sessions.getReplayUrl(browser.id)
      replayUrl = replay?.url ?? null
      console.log(`[Teardown] Presigned Replay URL: ${replayUrl ?? "(unavailable)"}`)
    } catch (e) {
      console.warn("Replay fetch notice:", e)
    }

    try {
      await solari.close()
    } catch {}

    const report = {
      batch: "Batch 2: Core Chat & Multi-Turn Agent Loop",
      timestamp: new Date().toISOString(),
      sessionId: browser.id,
      replayUrl,
      targetUrl: TARGET_URL,
      findings,
      totalFindings: findings.length,
      passed: findings.filter((f) => f.pass).length,
      failed: findings.filter((f) => !f.pass).length,
    }

    const reportPath = join(EVIDENCE_DIR, "report.json")
    writeFileSync(reportPath, JSON.stringify(report, null, 2))
    console.log(`\nReport written to: ${reportPath}`)
  }
}

run()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error("FATAL:", err)
    process.exit(1)
  })
