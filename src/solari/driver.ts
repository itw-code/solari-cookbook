/**
 * Solari driver abstraction — interface + two implementations.
 *
 * ┌─────────────────────────────────────────────────────────────────────────┐
 * │  STEP 00 SKELETON — fill in at Step 02/03.                              │
 * │  This file COMPILES ONLY. Method bodies are minimal stubs and the        │
 * │  MockSolari fixtures are placeholders. Real logic lands in later steps. │
 * └─────────────────────────────────────────────────────────────────────────┘
 *
 * Purpose: give the rest of ColdStart a single seam into Solari so that code
 * can run against the live API (LiveSolari) or be developed offline with
 * deterministic fixtures (MockSolari) before a live run.
 *
 * Security: SOLARI_API_KEY is read ONLY from process.env here. It is never
 * hardcoded, never logged, and never written to any file.
 */
import { Solari as BrowserSolari } from "@solarisdk/browser"
import type { SolariOptions as BrowserSolariOptions, LaunchOptions, BrowserSession } from "@solarisdk/browser"
import { SolariClient } from "@solarisdk/sdk"
import type { CreateSandboxOptions, Sandbox } from "@solarisdk/sdk"

/** Credential + endpoint options shared by both implementations. */
export interface DriverConfig {
  /** Enables log-mode (LiveSolari logs nothing sensitive; MockSolari logs its calls). */
  debug?: boolean
}

/** Options handed to `launchBrowser`. A superset of the SDK's `LaunchOptions`. */
export type BrowserLaunchOptions = LaunchOptions

/** Options handed to `createSandbox`. A superset of the SDK's `CreateSandboxOptions`. */
export type SandboxCreateOptions = CreateSandboxOptions

/**
 * The single seam the rest of the project uses to talk to Solari.
 * Implemented by LiveSolari (network) and MockSolari (offline fixtures).
 */
export interface SolariDriver {
  /** Launch a cloud browser session and return a connected Playwright browser. */
  launchBrowser(opts?: BrowserLaunchOptions): Promise<BrowserSession>
  /** Create a sandbox microVM session. */
  createSandbox(opts?: SandboxCreateOptions): Promise<Sandbox>
  /** Tear down any held local clients / proxies. Idempotent. */
  shutdown(): Promise<void>
}

/** Build a SolariDriver from the environment. Reads SOLARI_API_KEY from process.env. */
export function createDriver(kind: "live" | "mock" = "live", config: DriverConfig = {}): SolariDriver {
  return kind === "live" ? new LiveSolari(config) : new MockSolari(config)
}

/** Reads the key from process.env (never from a literal). Throws if absent. */
function requireApiKey(): string {
  const key = process.env.SOLARI_API_KEY
  if (!key || key.length === 0) {
    throw new Error("SOLARI_API_KEY is not set. Source .env before constructing LiveSolari.")
  }
  return key
}

/** Live implementation: real network calls against api.getsolari.com. */
export class LiveSolari implements SolariDriver {
  private readonly browser: BrowserSolari
  private readonly client: SolariClient

  constructor(public readonly config: DriverConfig = {}) {
    const apiKey = requireApiKey()
    // NOTE: the key is handed to the SDK constructors ONLY. It is never logged.
    this.browser = new BrowserSolari({ apiKey } satisfies BrowserSolariOptions)
    this.client = new SolariClient({ apiKey })
  }

  async launchBrowser(opts?: BrowserLaunchOptions): Promise<BrowserSession> {
    if (this.config.debug) console.log("[LiveSolari] launchBrowser", opts)
    // STEP 00: delegated directly. Wire retries / proxy / stealth at Step 02/03.
    return this.browser.launch(opts)
  }

  async createSandbox(opts?: SandboxCreateOptions): Promise<Sandbox> {
    if (this.config.debug) console.log("[LiveSolari] createSandbox", opts)
    // STEP 00: delegated directly. Wire templates / volumes at Step 02/03.
    return this.client.sandboxes.create(opts)
  }

  async shutdown(): Promise<void> {
    if (this.config.debug) console.log("[LiveSolari] shutdown")
    // STEP 00: close the browser client's loopback proxy. Add client/sandbox
    // cleanup at Step 02/03. This is idempotent.
    await this.browser.close()
  }
}

/** Offline implementation: no network; deterministic fixtures + log-mode. */
export class MockSolari implements SolariDriver {
  constructor(public readonly config: DriverConfig = {}) {}

  async launchBrowser(opts?: BrowserLaunchOptions): Promise<BrowserSession> {
    if (this.config.debug) console.log("[MockSolari] launchBrowser", opts)
    // STEP 00: fixture only. Real fixture will come back at Step 02/03.
    return {
      id: "mock-browser-session-slot-1",
    } as unknown as BrowserSession
  }

  async createSandbox(opts?: SandboxCreateOptions): Promise<Sandbox> {
    if (this.config.debug) console.log("[MockSolari] createSandbox", opts)
    // STEP 00: fixture only.
    return {
      sandboxId: "mock-sandbox-0001",
    } as unknown as Sandbox
  }

  async shutdown(): Promise<void> {
    if (this.config.debug) console.log("[MockSolari] shutdown")
  }
}
