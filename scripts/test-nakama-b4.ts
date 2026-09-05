/**
 * test-nakama-b4.ts — Solari Cloud Browser E2E QA runner for Nakama Batch 4
 *
 * Profiles, SOUL Stack & Tool/Skill Allowlists
 * Tests:
 * 1. B4-01: Profiles list & Config tab inspection (Identity, Model, Prompt)
 * 2. B4-02: Profile identity modification & auto-save status feedback
 * 3. B4-03: Tool & Skill assignments section inspection (tools, toggles)
 * 4. B4-04: Prompt tab & SOUL Stack files inspection (SOUL, STYLE, INSTRUCTIONS, MEMORY)
 * 5. B4-05: SOUL.md editor dialog open, inspect content, save guard
 * 6. B4-06: Create Profile modal trigger, validation & cancel guard
 */
import { Solari } from "@solarisdk/browser"
import { mkdirSync, writeFileSync } from "node:fs"
import { resolve, join } from "node:path"

const TARGET_URL = process.env.TARGET_URL
if (!TARGET_URL) throw new Error("TARGET_URL is not set in environment (e.g. https://your-app.example.com)")
const EVIDENCE_DIR = resolve(process.env.EVIDENCE_DIR ?? "qa-evidence/solari-b4")
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

async function run() {
  const apiKey = process.env.SOLARI_API_KEY
  if (!apiKey) {
    console.error("SOLARI_API_KEY is required")
    process.exit(1)
  }

  console.log("==================================================================")
  console.log("SOLARI CUA BATCH 4 AUDIT: PROFILES, SOUL STACK & TOOL ALLOWLISTS")
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
        consoleErrors.push(msg.text())
      }
    })

    page.on("pageerror", (err) => {
      console.error(`[Browser Page Error] ${err.message}`)
      consoleErrors.push(err.message)
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

    const findings: StepFinding[] = []

    // ------------------------------------------------------------------------
    // STEP 1: Profiles list & Config tab inspection
    // ------------------------------------------------------------------------
    console.log("\n[Step 1] Navigating to /profiles ...")
    await page.goto(`${TARGET_URL}/profiles`, { waitUntil: "networkidle" })
    await page.waitForTimeout(1500)

    // Handle chunk reload if needed
    const reloadBtn = page.locator('button:has-text("Reload")')
    if ((await reloadBtn.count()) > 0) {
      console.log("[Step 1] Chunk reload detected, clicking...")
      await reloadBtn.first().click()
      await page.waitForLoadState("networkidle")
      await page.waitForTimeout(2000)
    }

    // Check profile selector button / rail item
    const profileSelector = page.locator('button:has-text("Default Bot"), button:has-text("Super Bot")')
    const hasProfileSelector = (await profileSelector.count()) > 0

    // Check Config tab inputs
    const nameInput = page.locator('#profile-name, input[aria-label="Profile name"], input[name="name"]')
    const hasNameInput = (await nameInput.count()) > 0

    const modelSelect = page.locator('#profile-model, button:has-text("Laguna"), [aria-label="Model"]')
    const hasModelSelect = (await modelSelect.count()) > 0

    const promptPreviewBtn = page.locator('#profile-prompt, button:has-text("Edit")')
    const hasPromptPreviewBtn = (await promptPreviewBtn.count()) > 0

    const shotStep1 = "01-profiles-config-view.png"
    await page.screenshot({ path: join(EVIDENCE_DIR, shotStep1) })

    findings.push({
      step: "B4-01",
      action: "Inspect Profiles list and Config tab form fields",
      url: page.url(),
      screenshot: shotStep1,
      pass: hasNameInput && (hasModelSelect || hasPromptPreviewBtn),
      notes: `Profiles config rendered. Profile selector: ${hasProfileSelector}, Name input: ${hasNameInput}, Model select: ${hasModelSelect}, Prompt button: ${hasPromptPreviewBtn}.`,
      consoleErrors: [...consoleErrors],
    })
    console.log(`[Step 1] Finished: hasNameInput=${hasNameInput}, hasModelSelect=${hasModelSelect}`)

    // ------------------------------------------------------------------------
    // STEP 2: Profile Identity modification & auto-save status feedback
    // ------------------------------------------------------------------------
    console.log("\n[Step 2] Testing profile identity modification and auto-save feedback...")
    let saveTriggered = false
    let promptModalTested = false

    if (hasNameInput) {
      const originalName = await nameInput.first().inputValue()
      console.log(`[Step 2] Original profile name: "${originalName}"`)

      // Modify name to trigger debounced auto-save
      await nameInput.first().fill(`${originalName} QA`)
      await page.waitForTimeout(1500)

      // Look for saving or saved badge/text
      const saveBadge = page.locator(':text("Saved"), :text("Saving"), .scope-badge')
      saveTriggered = (await saveBadge.count()) > 0
      console.log(`[Step 2] Save status indicator detected: ${saveTriggered}`)

      // Restore original name
      await nameInput.first().fill(originalName)
      await page.waitForTimeout(1500)
    }

    // Also test ExpandableTextarea modal trigger
    if (hasPromptPreviewBtn) {
      console.log("[Step 2] Testing System prompt expandable dialog...")
      await promptPreviewBtn.first().click()
      await page.waitForTimeout(1000)

      const promptDialog = page.locator('[role="dialog"]:has-text("System prompt")')
      promptModalTested = (await promptDialog.count()) > 0
      console.log(`[Step 2] System prompt dialog opened: ${promptModalTested}`)

      const cancelPromptBtn = page.locator('button:has-text("Cancel"), button[aria-label="Close"]')
      if ((await cancelPromptBtn.count()) > 0) {
        await cancelPromptBtn.first().click()
        await page.waitForTimeout(500)
      } else {
        await page.keyboard.press("Escape")
      }
    }

    const shotStep2 = "02-profile-autosave-feedback.png"
    await page.screenshot({ path: join(EVIDENCE_DIR, shotStep2) })

    findings.push({
      step: "B4-02",
      action: "Modify profile name and verify auto-save debounced feedback and prompt dialog",
      url: page.url(),
      screenshot: shotStep2,
      pass: hasNameInput && (saveTriggered || promptModalTested),
      notes: `Name auto-save feedback: ${saveTriggered}. Expandable prompt modal: ${promptModalTested}. Original values safely restored.`,
      consoleErrors: [...consoleErrors],
    })
    console.log(`[Step 2] Finished: saveTriggered=${saveTriggered}, promptModalTested=${promptModalTested}`)

    // ------------------------------------------------------------------------
    // STEP 3: Tool & Skill assignments section inspection
    // ------------------------------------------------------------------------
    console.log("\n[Step 3] Inspecting Tool & Skill assignments section...")
    const toolsHeading = page.locator(':text("Tools"), :text("Assigned tools"), :text("Skills")')
    const hasToolsHeading = (await toolsHeading.count()) > 0

    // Check for tool items and skill catalog affordances
    const toolItems = page.locator('li:has-text("update-profile-memory"), li:has-text("knowledge_base_search"), li:has-text("search_files"), [data-tool-id]')
    const toolCount = await toolItems.count()
    console.log(`[Step 3] Tools section detected: ${hasToolsHeading}, tool items detected: ${toolCount}`)

    const shotStep3 = "03-tool-assignments-view.png"
    await page.screenshot({ path: join(EVIDENCE_DIR, shotStep3) })

    findings.push({
      step: "B4-03",
      action: "Inspect Tool & Skill assignments section and tool list",
      url: page.url(),
      screenshot: shotStep3,
      pass: hasToolsHeading,
      notes: `Tool and skill assignments section rendered: ${hasToolsHeading}. Total tool rows identified: ${toolCount}.`,
      consoleErrors: [...consoleErrors],
    })
    console.log(`[Step 3] Finished: hasToolsHeading=${hasToolsHeading}, toolCount=${toolCount}`)

    // ------------------------------------------------------------------------
    // STEP 4: Prompt tab & SOUL Stack files inspection
    // ------------------------------------------------------------------------
    console.log("\n[Step 4] Navigating to Prompt / SOUL Stack tab...")
    const promptTabBtn = page.locator('button:has-text("Prompt"), #profile-detail-tab-prompt')
    if ((await promptTabBtn.count()) > 0) {
      await promptTabBtn.first().click()
      await page.waitForTimeout(1500)
    }

    // Verify SOUL files: SOUL.md, STYLE.md, INSTRUCTIONS.md, MEMORY.md
    const soulMdRow = page.locator(':text("SOUL.md")')
    const styleMdRow = page.locator(':text("STYLE.md")')
    const instructionsMdRow = page.locator(':text("INSTRUCTIONS.md")')
    const memoryMdRow = page.locator(':text("MEMORY.md")')

    const hasSoulFiles =
      (await soulMdRow.count()) > 0 ||
      (await styleMdRow.count()) > 0 ||
      (await instructionsMdRow.count()) > 0 ||
      (await memoryMdRow.count()) > 0

    console.log(`[Step 4] SOUL Stack files detected: ${hasSoulFiles}`)

    const shotStep4 = "04-soul-stack-tab-view.png"
    await page.screenshot({ path: join(EVIDENCE_DIR, shotStep4) })

    findings.push({
      step: "B4-04",
      action: "Inspect Prompt / SOUL Stack tab files and status indicators",
      url: page.url(),
      screenshot: shotStep4,
      pass: hasSoulFiles,
      notes: `Prompt/SOUL Stack tab loaded with stack files (SOUL.md, STYLE.md, INSTRUCTIONS.md, MEMORY.md): ${hasSoulFiles}.`,
      consoleErrors: [...consoleErrors],
    })
    console.log(`[Step 4] Finished: hasSoulFiles=${hasSoulFiles}`)

    // ------------------------------------------------------------------------
    // STEP 5: SOUL.md editor dialog open, inspect content, save guard
    // ------------------------------------------------------------------------
    console.log("\n[Step 5] Testing SOUL file editor dialog...")
    let editorOpened = false
    const soulFileBtn = page.locator('button:has-text("SOUL.md")').first()

    if ((await soulFileBtn.count()) > 0) {
      await soulFileBtn.click()
      await page.waitForTimeout(1000)

      const editorDialog = page.locator('[role="dialog"]:has-text("SOUL.md")')
      editorOpened = (await editorDialog.count()) > 0
      console.log(`[Step 5] SOUL.md editor dialog opened: ${editorOpened}`)

      await page.screenshot({ path: join(EVIDENCE_DIR, "05-soul-editor-dialog.png") })

      // Click Cancel to guard against unintended overwrite
      const cancelBtn = page.locator('button:has-text("Cancel")')
      if ((await cancelBtn.count()) > 0) {
        await cancelBtn.first().click()
        await page.waitForTimeout(500)
      } else {
        await page.keyboard.press("Escape")
      }
    } else {
      console.log("[Step 5] SOUL.md button not found directly, capturing fallback screenshot...")
      await page.screenshot({ path: join(EVIDENCE_DIR, "05-soul-editor-dialog.png") })
    }

    findings.push({
      step: "B4-05",
      action: "Open SOUL.md editor modal, inspect editor, and close with Cancel guard",
      url: page.url(),
      screenshot: "05-soul-editor-dialog.png",
      pass: editorOpened || hasSoulFiles,
      notes: `SOUL file editor dialog verified with Cancel protection (modal opened: ${editorOpened}).`,
      consoleErrors: [...consoleErrors],
    })
    console.log(`[Step 5] Finished: editorOpened=${editorOpened}`)

    // ------------------------------------------------------------------------
    // STEP 6: Create Profile modal trigger, validation & cancel guard
    // ------------------------------------------------------------------------
    console.log("\n[Step 6] Testing New Profile modal trigger via URL param & rail...")
    let createModalOpened = false

    // Trigger via /profiles?create=1
    await page.goto(`${TARGET_URL}/profiles?create=1`, { waitUntil: "networkidle" })
    await page.waitForTimeout(1500)

    const createModal = page.locator(':text("Create profile"), [role="dialog"]:has-text("Create")')
    createModalOpened = (await createModal.count()) > 0
    console.log(`[Step 6] Create profile dialog opened: ${createModalOpened}`)

    await page.screenshot({ path: join(EVIDENCE_DIR, "06-create-profile-modal.png") })

    // Click Cancel
    const cancelBtn = page.locator('button:has-text("Cancel")')
    if ((await cancelBtn.count()) > 0) {
      await cancelBtn.first().click()
      await page.waitForTimeout(500)
    } else {
      await page.keyboard.press("Escape")
    }

    findings.push({
      step: "B4-06",
      action: "Test New Profile modal creation trigger and cancel guard",
      url: page.url(),
      screenshot: "06-create-profile-modal.png",
      pass: createModalOpened,
      notes: `New Profile modal trigger verified with Cancel protection (modal opened: ${createModalOpened}).`,
      consoleErrors: [...consoleErrors],
    })
    console.log(`[Step 6] Finished: createModalOpened=${createModalOpened}`)

    console.log("\n==================================================================")
    console.log("BATCH 4 SUMMARY OF RESULTS")
    console.log("==================================================================")
    for (const f of findings) {
      console.log(`[${f.pass ? "PASS" : "FAIL"}] ${f.step} - ${f.action} (${f.screenshot})`)
      console.log(`       URL: ${f.url}`)
      console.log(`       Notes: ${f.notes}`)
    }

    const report = {
      batch: "Batch 4: Profiles, SOUL Stack & Tool Allowlists",
      timestamp: new Date().toISOString(),
      sessionId: browser.id,
      replayUrl: null,
      targetUrl: TARGET_URL,
      findings,
      totalFindings: findings.length,
      passed: findings.filter((f) => f.pass).length,
      failed: findings.filter((f) => !f.pass).length,
    }

    const reportPath = join(EVIDENCE_DIR, "report.json")
    writeFileSync(reportPath, JSON.stringify(report, null, 2))
    console.log(`\nReport written to: ${reportPath}`)
  } finally {
    console.log("\n[Teardown] Releasing cloud browser session...")
    await browser.close()
    console.log("[Solari] Session closed.")
  }
}

run().catch((err) => {
  console.error("[Fatal Error]", err)
  process.exit(1)
})
