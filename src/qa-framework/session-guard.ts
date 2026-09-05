/**
 * session-guard.ts — Cloud Browser Session Lifecycle & Graceful Replay Fallbacks
 *
 * Prevents Dangling Remote Browser Instances & Unhandled Teardown Crashes:
 * In live cloud environments (Solari), calling `browser.getReplayUrl()` or tearing down
 * sessions can throw unhandled TypeErrors or 404s if the recording is still processing,
 * absent, or unsupported by the tier.
 *
 * This supervisor wraps:
 * 1. Safe launch & connection establishment
 * 2. Unhandled console/pageerror harvesting
 * 3. Guaranteed `browser.close()` and `solari.close()` execution in finally blocks
 * 4. Resilient replay URL fetching with timeout & exponential backoff
 */

export interface SessionGuardConfig {
  apiKey?: string
  recording?: boolean
  viewport?: { width: number; height: number }
  replayTimeoutMs?: number
  replayPollIntervalMs?: number
  debug?: boolean
}

export interface SessionContext {
  browser: any
  page: any
  sessionId: string
  consoleErrors: string[]
  pageErrors: string[]
  networkErrors: string[]
}

export interface SessionTeardownResult {
  sessionId: string
  replayUrl: string | null
  consoleErrors: string[]
  pageErrors: string[]
  networkErrors: string[]
  durationMs: number
}

/**
 * Safely fetches a presigned replay URL from Solari without crashing on 404/TypeError.
 */
export async function safeGetReplayUrl(
  solariInstance: any,
  sessionId: string,
  options: { timeoutMs?: number; pollIntervalMs?: number; debug?: boolean } = {}
): Promise<string | null> {
  const timeoutMs = options.timeoutMs ?? 5000
  const pollIntervalMs = options.pollIntervalMs ?? 1000
  const startTime = Date.now()

  // Wait brief moment for cloud upload propagation
  await new Promise((r) => setTimeout(r, Math.min(1000, timeoutMs)))

  while (Date.now() - startTime < timeoutMs) {
    try {
      if (solariInstance?.sessions && typeof solariInstance.sessions.getReplayUrl === "function") {
        const replay = await solariInstance.sessions.getReplayUrl(sessionId)
        if (replay && typeof replay.url === "string" && replay.url.length > 0) {
          return replay.url
        }
        if (typeof replay === "string" && replay.length > 0) {
          return replay
        }
      }
    } catch (err: any) {
      if (options.debug) {
        console.warn(`[SessionGuard] Replay fetch notice for ${sessionId}: ${err?.message ?? err}`)
      }
      // If error is 404 or missing replay, continue polling until timeout
    }

    await new Promise((r) => setTimeout(r, pollIntervalMs))
  }

  return null
}

/**
 * Executes a test routine inside a protected session sandbox.
 * Guarantees browser/session closure even on test assertion failure or unhandled exceptions.
 */
export async function withSessionGuard<T>(
  solariClient: any,
  config: SessionGuardConfig,
  testFn: (ctx: SessionContext) => Promise<T>
): Promise<{ result: T; teardown: SessionTeardownResult }> {
  const startTime = Date.now()
  const consoleErrors: string[] = []
  const pageErrors: string[] = []
  const networkErrors: string[] = []

  let browser: any = null
  let page: any = null
  let sessionId = "unknown-session"

  try {
    // 1. Launch browser session
    const launchOpts = { recording: config.recording ?? true }
    browser = await solariClient.launch(launchOpts)
    sessionId = browser?.id ?? browser?.sessionId ?? `session-${Date.now()}`

    // 2. Provision default page
    page = await browser.newPage()
    const viewport = config.viewport ?? { width: 1280, height: 800 }
    if (typeof page.setViewportSize === "function") {
      await page.setViewportSize(viewport)
    }

    // 3. Attach defensive event listeners
    if (typeof page.on === "function") {
      page.on("console", (msg: any) => {
        try {
          const type = typeof msg.type === "function" ? msg.type() : msg.type
          const text = typeof msg.text === "function" ? msg.text() : String(msg)
          if (type === "error") consoleErrors.push(text)
        } catch {}
      })

      page.on("pageerror", (err: any) => {
        try {
          pageErrors.push(err?.message ?? String(err))
        } catch {}
      })

      page.on("requestfailed", (req: any) => {
        try {
          const url = typeof req.url === "function" ? req.url() : "unknown"
          const failure = typeof req.failure === "function" ? req.failure()?.errorText : "failed"
          networkErrors.push(`${url} - ${failure}`)
        } catch {}
      })
    }

    const ctx: SessionContext = {
      browser,
      page,
      sessionId,
      consoleErrors,
      pageErrors,
      networkErrors,
    }

    // 4. Run caller's test routine
    const result = await testFn(ctx)

    // 5. Normal teardown
    const teardown = await performTeardown(solariClient, browser, sessionId, {
      consoleErrors,
      pageErrors,
      networkErrors,
      startTime,
      config,
    })

    return { result, teardown }
  } catch (executionError) {
    // Test failed or threw; perform guaranteed emergency teardown
    if (browser) {
      await performTeardown(solariClient, browser, sessionId, {
        consoleErrors,
        pageErrors,
        networkErrors,
        startTime,
        config,
      }).catch((teardownErr) => {
        console.error("[SessionGuard] Error during emergency teardown:", teardownErr)
      })
    }
    throw executionError
  }
}

async function performTeardown(
  solariClient: any,
  browser: any,
  sessionId: string,
  meta: {
    consoleErrors: string[]
    pageErrors: string[]
    networkErrors: string[]
    startTime: number
    config: SessionGuardConfig
  }
): Promise<SessionTeardownResult> {
  // 1. Close browser context safely
  if (browser) {
    try {
      if (typeof browser.close === "function") {
        await browser.close()
      }
    } catch (e: any) {
      console.warn(`[SessionGuard] Browser close notice: ${e?.message ?? e}`)
    }
  }

  // 2. Fetch replay URL with defensive guard
  let replayUrl: string | null = null
  try {
    replayUrl = await safeGetReplayUrl(solariClient, sessionId, {
      timeoutMs: meta.config.replayTimeoutMs ?? 3000,
      pollIntervalMs: meta.config.replayPollIntervalMs ?? 1000,
      debug: meta.config.debug,
    })
  } catch (e: any) {
    console.warn(`[SessionGuard] Replay fetch safely suppressed: ${e?.message ?? e}`)
  }

  // 3. Close Solari driver / loopback proxy
  if (solariClient) {
    try {
      if (typeof solariClient.close === "function") {
        await solariClient.close()
      }
    } catch (e: any) {
      console.warn(`[SessionGuard] Client close notice: ${e?.message ?? e}`)
    }
  }

  return {
    sessionId,
    replayUrl,
    consoleErrors: meta.consoleErrors,
    pageErrors: meta.pageErrors,
    networkErrors: meta.networkErrors,
    durationMs: Date.now() - meta.startTime,
  }
}
