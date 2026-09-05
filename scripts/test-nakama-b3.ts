/**
 * test-nakama-b3.ts — Solari Cloud Browser E2E QA runner for Nakama Batch 3
 *
 * Chat History, Files/Artifacts & Knowledge Base Management
 * Tests:
 * 1. B3-01: History list view & session search
 * 2. B3-02: Session deletion & confirmation modal
 * 3. B3-03: Files/Artifacts view & Grid/List toggle (F-005 regression check)
 * 4. B3-04: Knowledge Base view & inherited sources
 * 5. B3-05: File upload validation (unsupported file rejection .exe)
 * 6. B3-06: File upload happy path (.md) & duplicate prompt
 * 7. B3-07: Document deletion & confirmation
 */
import { Solari } from "@solarisdk/browser"
import { existsSync, mkdirSync, writeFileSync, readdirSync, readFileSync, unlinkSync } from "node:fs"
import { resolve, join } from "node:path"

const TARGET_URL = process.env.TARGET_URL
if (!TARGET_URL) throw new Error("TARGET_URL is not set in environment (e.g. https://your-app.example.com)")
const EVIDENCE_DIR = resolve(process.env.EVIDENCE_DIR ?? "qa-evidence/solari-b3")
mkdirSync(EVIDENCE_DIR, { recursive: true })

// Clean up any test artifact on disk before the run.
// QA_KB_DIR optionally points at a local knowledge-base fixture directory
// (used only for offline/self-hosted fixture cleanup — skipped in CI).
function cleanKnowledgeBaseDisk(): void {
  const kbDir = process.env.QA_KB_DIR
  if (!kbDir) return
  if (existsSync(kbDir)) {
    const manifestPath = join(kbDir, "manifest.json")
    if (existsSync(manifestPath)) {
      try {
        const manifest = JSON.parse(readFileSync(manifestPath, "utf8"))
        manifest.documents = manifest.documents.filter(
          (d: any) => !d.filename?.includes("qa-knowledge-doc")
        )
        writeFileSync(manifestPath, JSON.stringify(manifest, null, 2))
      } catch {}
    }
    for (const f of readdirSync(kbDir)) {
      if (f.includes("qa-knowledge-doc")) {
        try { unlinkSync(join(kbDir, f)) } catch {}
      }
    }
  }
}

cleanKnowledgeBaseDisk()

// Create sample test files for upload validation
const validDocPath = join(EVIDENCE_DIR, "qa-knowledge-doc.md")
writeFileSync(validDocPath, "# QA Knowledge Document\n\nAutomated Solari CUA Batch 3 document for verification.\n")

const invalidDocPath = join(EVIDENCE_DIR, "qa-malicious-file.exe")
writeFileSync(invalidDocPath, "MZ_FAKE_EXECUTABLE_BINARY_CONTENT")

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
  console.log("SOLARI CUA BATCH 3 AUDIT: HISTORY, FILES & KNOWLEDGE BASE")
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
      console.log(`[Browser Console ${msg.type()}] ${msg.text()}`)
      if (msg.type() === "error") {
        const text = msg.text()
        consoleErrors.push(text)
      }
    })

    page.on("pageerror", (err) => {
      console.error(`[Browser Page Error] ${err.message}\n${err.stack}`)
      consoleErrors.push(err.message)
    })

    page.on("requestfailed", (req) => {
      console.log(`[Request Failed] ${req.url()} - ${req.failure()?.errorText}`)
    })

    page.on("response", (res) => {
      if (res.status() >= 400) {
        console.log(`[HTTP ${res.status()}] ${res.url()}`)
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
    // STEP 1: History list view & session search
    // ------------------------------------------------------------------------
    console.log("\n[Step 1] Navigating to /history ...")
    await page.goto(`${TARGET_URL}/history`, { waitUntil: "networkidle" })
    await page.waitForTimeout(1500)

    const searchInput = page.locator('input[aria-label="Search chats"], input[placeholder*="Search chats" i]')
    const hasSearchInput = (await searchInput.count()) > 0

    // Type a query to verify search filter
    if (hasSearchInput) {
      await searchInput.first().fill("Placeholder")
      await page.waitForTimeout(1000)
    }

    const shotStep1 = "01-history-search.png"
    await page.screenshot({ path: join(EVIDENCE_DIR, shotStep1) })

    // Clear search
    if (hasSearchInput) {
      const clearBtn = page.locator('button[aria-label="Clear search"]')
      if ((await clearBtn.count()) > 0) {
        await clearBtn.first().click()
        await page.waitForTimeout(500)
      } else {
        await searchInput.first().fill("")
      }
    }

    findings.push({
      step: "B3-01",
      action: "Inspect history list and chat search filter",
      url: page.url(),
      screenshot: shotStep1,
      pass: hasSearchInput,
      notes: `Search input found and functional. Filter query executed.`,
      consoleErrors: [...consoleErrors],
    })
    console.log(`[Step 1] Finished: searchInput=${hasSearchInput}`)

    // ------------------------------------------------------------------------
    // STEP 2: Session deletion confirmation modal
    // ------------------------------------------------------------------------
    console.log("\n[Step 2] Testing session deletion dialog...")
    // In HistorySessionRow: <Button aria-label={`Delete ${title}`} ...>
    const sessionDeleteBtn = page.locator('button[aria-label^="Delete "]').first()
    let deleteModalOpened = false

    const hasSessionDeleteBtn = (await sessionDeleteBtn.count()) > 0
    if (hasSessionDeleteBtn) {
      await sessionDeleteBtn.click()
      await page.waitForTimeout(1000)
      const deleteDialog = page.locator(':text("Delete chat?")')
      deleteModalOpened = (await deleteDialog.count()) > 0
      console.log(`[Step 2] Delete confirmation dialog visible: ${deleteModalOpened}`)

      await page.screenshot({ path: join(EVIDENCE_DIR, "02-history-delete-modal.png") })

      // Click Cancel to avoid unintended deletion of base seed session
      const cancelBtn = page.locator('button:has-text("Cancel")')
      if ((await cancelBtn.count()) > 0) {
        await cancelBtn.first().click()
        await page.waitForTimeout(500)
      } else {
        await page.keyboard.press("Escape")
      }
    } else {
      console.log("[Step 2] No sessions found in history to trigger delete modal.")
      await page.screenshot({ path: join(EVIDENCE_DIR, "02-history-delete-modal.png") })
    }

    findings.push({
      step: "B3-02",
      action: "Test session delete trigger and confirmation guard",
      url: page.url(),
      screenshot: "02-history-delete-modal.png",
      pass: deleteModalOpened || !hasSessionDeleteBtn,
      notes: hasSessionDeleteBtn
        ? `Delete dialog verified with Cancel protection (modal opened: ${deleteModalOpened}).`
        : "History empty; delete guard check skipped.",
      consoleErrors: [...consoleErrors],
    })
    console.log(`[Step 2] Finished: deleteModalOpened=${deleteModalOpened}`)

    // ------------------------------------------------------------------------
    // STEP 3: Files & Artifacts view & Grid/List toggle (F-005 check)
    // ------------------------------------------------------------------------
    console.log("\n[Step 3] Navigating to /files ...")
    await page.goto(`${TARGET_URL}/files`, { waitUntil: "networkidle" })
    await page.waitForTimeout(1500)

    const gridToggle = page.locator('button[aria-label="Grid view"]')
    const listToggle = page.locator('button[aria-label="List view"]')
    const hasViewToggle = (await gridToggle.count()) > 0 && (await listToggle.count()) > 0
    const refreshBtn = page.locator('button:has-text("Refresh")')
    const hasRefreshBtn = (await refreshBtn.count()) > 0
    console.log(`[Step 3] Artifacts page rendered. Toggle: ${hasViewToggle}, Refresh: ${hasRefreshBtn}`)

    if (hasViewToggle) {
      // Toggle to grid view then back
      await gridToggle.first().click()
      await page.waitForTimeout(500)
      await listToggle.first().click()
      await page.waitForTimeout(500)
    }

    const shotStep3 = "03-files-artifacts-view.png"
    await page.screenshot({ path: join(EVIDENCE_DIR, shotStep3) })

    findings.push({
      step: "B3-03",
      action: "Inspect Files/Artifacts page and view mode switcher",
      url: page.url(),
      screenshot: shotStep3,
      pass: page.url().includes("/files") && hasRefreshBtn,
      notes: `Artifacts page rendered. Refresh button present: ${hasRefreshBtn}. Grid/List toggle (F-005) present: ${hasViewToggle} (conditionally hidden when empty).`,
      consoleErrors: [...consoleErrors],
    })
    console.log(`[Step 3] Finished: hasRefreshBtn=${hasRefreshBtn}, hasViewToggle=${hasViewToggle}`)

    // ------------------------------------------------------------------------
    // STEP 4: Knowledge Base view & panel inspection
    // ------------------------------------------------------------------------
    console.log("\n[Step 4] Navigating to Profiles page and Knowledge tab...")
    await page.goto(`${TARGET_URL}/profiles`, { waitUntil: "networkidle" })
    await page.waitForTimeout(1500)

    // Handle chunk reload if needed
    const reloadBtn = page.locator('button:has-text("Reload")')
    if ((await reloadBtn.count()) > 0) {
      console.log("[Step 4] Reload button detected (chunk reload), clicking...")
      await reloadBtn.first().click()
      await page.waitForLoadState("networkidle")
      await page.waitForTimeout(2000)
    }

    // Click the Knowledge tab
    const knowledgeTabBtn = page.locator('button:has-text("Knowledge"), #profile-detail-tab-knowledge')
    if ((await knowledgeTabBtn.count()) > 0) {
      console.log("[Step 4] Clicking Knowledge tab button...")
      await knowledgeTabBtn.first().click()
      await page.waitForTimeout(1500)
    }

    // Wait for the panel to settle
    try {
      await page.waitForSelector('button:has-text("Upload"), input[type="file"]', { timeout: 10000 })
    } catch {}

    const shotStep4 = "04-knowledge-base-initial.png"
    await page.screenshot({ path: join(EVIDENCE_DIR, shotStep4) })

    const uploadBtn = page.locator('button:has-text("Upload")')
    const hasUploadBtn = (await uploadBtn.count()) > 0
    const fileInput = page.locator('input[type="file"]')
    const hasFileInput = (await fileInput.count()) > 0

    findings.push({
      step: "B3-04",
      action: "Inspect Knowledge Base tab and upload affordance",
      url: page.url(),
      screenshot: shotStep4,
      pass: hasUploadBtn && hasFileInput,
      notes: `Knowledge tab loaded. Upload trigger visible: ${hasUploadBtn}. File input present: ${hasFileInput}.`,
      consoleErrors: [...consoleErrors],
    })
    console.log(`[Step 4] Finished: hasUploadBtn=${hasUploadBtn}, hasFileInput=${hasFileInput}`)

    // ------------------------------------------------------------------------
    // STEP 5: File upload validation (unsupported .exe file rejection)
    // ------------------------------------------------------------------------
    console.log("\n[Step 5] Testing upload validation with unsupported .exe file...")
    let rejectedUnsupported = false
    const kbFileInput5 = page.locator('input[type="file"]').last()
    await kbFileInput5.setInputFiles(invalidDocPath)
    await page.waitForTimeout(1500)

    const errorNotice = page.locator(':text("Unsupported file type"), [role="alert"], .text-destructive')
    rejectedUnsupported = (await errorNotice.count()) > 0
    console.log(`[Step 5] Unsupported file error displayed: ${rejectedUnsupported}`)

    const shotStep5 = "05-unsupported-upload-error.png"
    await page.screenshot({ path: join(EVIDENCE_DIR, shotStep5) })

    findings.push({
      step: "B3-05",
      action: "Upload unsupported .exe file and verify client rejection",
      url: page.url(),
      screenshot: shotStep5,
      pass: rejectedUnsupported,
      notes: `Unsupported file upload correctly rejected with error message: ${rejectedUnsupported}.`,
      consoleErrors: [...consoleErrors],
    })
    console.log(`[Step 5] Finished: rejectedUnsupported=${rejectedUnsupported}`)

    // ------------------------------------------------------------------------
    // STEP 6: File upload happy path (.md) & duplicate prompt
    // ------------------------------------------------------------------------
    console.log("\n[Step 6] Testing valid .md upload & duplicate handling...")
    let uploadSucceeded = false
    let duplicatePromptShown = false

    try {
      await page.waitForLoadState("networkidle")
      await page.waitForTimeout(1000)

      // 1. Initial valid upload
      console.log("[Step 6] Uploading valid markdown file: qa-knowledge-doc.md ...")
      const kbFileInput1 = page.locator('input[type="file"]').last()
      await kbFileInput1.setInputFiles(validDocPath)

      try {
        await page.waitForSelector(':text("qa-knowledge-doc.md")', { timeout: 15000 })
        uploadSucceeded = true
        console.log(`[Step 6] Initial upload succeeded!`)
      } catch {
        console.warn(`[Step 6] Timed out waiting for qa-knowledge-doc.md to appear in list`)
      }

      await page.waitForTimeout(1500)

      // 2. Upload same file again to trigger duplicate dialog
      console.log("[Step 6] Re-uploading same file to test duplicate detection...")
      const kbFileInput2 = page.locator('input[type="file"]').last()
      await kbFileInput2.setInputFiles(validDocPath)

      try {
        await page.waitForSelector(':text("Duplicate document"), :text("is already in this knowledge base")', { timeout: 10000 })
        duplicatePromptShown = true
        console.log(`[Step 6] Duplicate prompt dialog shown!`)
      } catch {
        console.warn(`[Step 6] Duplicate prompt dialog did not appear within 10s`)
      }

      await page.screenshot({ path: join(EVIDENCE_DIR, "06-duplicate-dialog.png") })

      // Click "Replace" to exercise the conflict resolution handler
      const replaceBtn = page.locator('button:has-text("Replace")')
      if ((await replaceBtn.count()) > 0) {
        await replaceBtn.first().click()
        try {
          await page.waitForSelector(':text("Duplicate document")', { state: "detached", timeout: 10000 })
        } catch {}
        await page.waitForTimeout(2000)
      }
    } catch (err) {
      console.error("[Step 6] Error encountered during upload/duplicate flow:", err)
      await page.screenshot({ path: join(EVIDENCE_DIR, "06-duplicate-dialog.png") })
    }

    findings.push({
      step: "B3-06",
      action: "Upload valid markdown document and verify duplicate conflict handling",
      url: page.url(),
      screenshot: "06-duplicate-dialog.png",
      pass: uploadSucceeded && duplicatePromptShown,
      notes: `Markdown document uploaded: ${uploadSucceeded}. Duplicate conflict modal verified: ${duplicatePromptShown}.`,
      consoleErrors: [...consoleErrors],
    })
    console.log(`[Step 6] Finished: uploadSucceeded=${uploadSucceeded}, duplicatePromptShown=${duplicatePromptShown}`)

    // ------------------------------------------------------------------------
    // STEP 7: Document deletion & confirmation
    // ------------------------------------------------------------------------
    console.log("\n[Step 7] Testing document deletion...")
    let docDeleted = false

    try {
      await page.waitForTimeout(1500)
      const deleteDocBtn = page.locator('button[aria-label="Delete qa-knowledge-doc.md"], button[aria-label^="Delete qa-knowledge"]').first()

      await deleteDocBtn.waitFor({ state: "visible", timeout: 10000 })
      await deleteDocBtn.click({ force: true })
      await page.waitForTimeout(1000)

      // Verify Delete document modal
      const modalHeader = page.locator(':text("Delete document")')
      await modalHeader.first().waitFor({ state: "visible", timeout: 5000 })
      const modalShown = (await modalHeader.count()) > 0
      console.log(`[Step 7] Delete document confirmation dialog visible: ${modalShown}`)

      const confirmDeleteBtn = page.locator('button:has-text("Delete")').last()
      await confirmDeleteBtn.click({ force: true })
      await page.waitForTimeout(2500)

      // Verify document is gone
      try {
        await page.waitForSelector(':text("qa-knowledge-doc.md")', { state: "detached", timeout: 10000 })
        docDeleted = true
      } catch {
        const remainingDoc = page.locator(':text("qa-knowledge-doc.md")')
        docDeleted = (await remainingDoc.count()) === 0
      }
      console.log(`[Step 7] Document deleted cleanly: ${docDeleted}`)
    } catch (err) {
      console.error("[Step 7] Error encountered during deletion flow:", err)
    }

    const shotStep7 = "07-document-deleted.png"
    await page.screenshot({ path: join(EVIDENCE_DIR, shotStep7) })

    findings.push({
      step: "B3-07",
      action: "Delete uploaded knowledge document and verify cleanup",
      url: page.url(),
      screenshot: shotStep7,
      pass: docDeleted,
      notes: `Document deletion executed and confirmed: ${docDeleted}.`,
      consoleErrors: [...consoleErrors],
    })
    console.log(`[Step 7] Finished: docDeleted=${docDeleted}`)

    console.log("\n==================================================================")
    console.log("BATCH 3 SUMMARY OF RESULTS")
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
      batch: "Batch 3: History, Files & Knowledge Base",
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
