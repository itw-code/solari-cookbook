/**
 * slop-catcher.ts — Lightweight Vision-Language Model (VLM) design QA module.
 *
 * Evaluates sandbox screenshots for "AI Slop" and design flaws (poor contrast,
 * inconsistent spacing, generic styling) separately from the heavy CUA execution loop.
 *
 * Implements a mockable client pattern (LiveVlm / MockVlm) similar to SolariDriver
 * to allow deterministic offline testing without live network or API keys.
 */

import { getModelConfig } from "../config/model-router.ts"

/** Design QA report produced by the Slop-Catcher VLM evaluation. */
export interface SlopReport {
  /** Score from 0 (flawless modern UI) to 100 (extreme AI slop / design failure). */
  slopScore: number
  /** Specific aesthetic or usability issues flagged during evaluation. */
  flags: string[]
  /** Concrete guidance to remediate the identified design flaws. */
  recommendation: string
}

/** Standard system prompt enforcing persona, inspection rubric, and strict JSON output. */
export const SLOP_SYSTEM_PROMPT =
  "You are a senior UI/UX designer and 'AI Slop' detector. Analyze this screenshot against modern design standards. Look for: 1. Poor contrast ratios, 2. Inconsistent spacing or alignment, 3. Generic 'AI slop' aesthetics (e.g., default Inter font, generic purple gradients, cluttered hierarchy). Return ONLY a valid JSON response matching this structure: { 'slopScore': number, 'flags': string[], 'recommendation': string }."

/** Normalized multimodal payload sent to the VLM client. */
export interface VlmRequest {
  systemPrompt: string
  userPrompt: string
  screenshotBase64: string
}

/** Configuration options for VLM client implementations. */
export interface VlmClientConfig {
  apiKey?: string
  endpoint?: string
  model?: string
  debug?: boolean
  mockResponse?: string | SlopReport
}

/**
 * Common interface for VLM callers (LiveVlmClient vs. MockVlmClient),
 * matching the SolariDriver seam pattern.
 */
export interface VlmClient {
  complete(request: VlmRequest): Promise<string>
  generate?(request: VlmRequest): Promise<string>
  analyze?(request: VlmRequest): Promise<string>
}

/** Offline mock implementation: returns deterministic fixtures without network calls. */
export class MockVlmClient implements VlmClient {
  public responses: Array<string | SlopReport> = []
  public calls: VlmRequest[] = []

  constructor(public readonly config: VlmClientConfig = {}) {
    if (config.mockResponse !== undefined) {
      this.responses.push(config.mockResponse)
    }
  }

  setResponse(response: string | SlopReport): void {
    this.responses = [response]
  }

  addResponse(response: string | SlopReport): void {
    this.responses.push(response)
  }

  async complete(request: VlmRequest): Promise<string> {
    this.calls.push(request)
    if (this.config.debug) {
      console.log("[MockVlmClient] complete call:", request.userPrompt)
    }
    const next = this.responses.shift() ?? this.config.mockResponse
    if (typeof next === "object" && next !== null) {
      return JSON.stringify(next)
    }
    if (typeof next === "string") {
      return next
    }
    return JSON.stringify({
      slopScore: 10,
      flags: [],
      recommendation: "Design passes baseline QA standards.",
    })
  }

  async generate(request: VlmRequest): Promise<string> {
    return this.complete(request)
  }

  async analyze(request: VlmRequest): Promise<string> {
    return this.complete(request)
  }
}

export const MockVlm = MockVlmClient

/** Live implementation: makes real multimodal HTTP requests against an OpenAI- or Gemini-compatible endpoint. */
export class LiveVlmClient implements VlmClient {
  public readonly config: VlmClientConfig

  constructor(config: VlmClientConfig = {}) {
    const perception = getModelConfig("PERCEPTION")
    this.config = {
      apiKey: config.apiKey ?? (perception.apiKey || undefined),
      model: config.model ?? (perception.modelName || undefined),
      ...config,
    }
  }

  async complete(request: VlmRequest): Promise<string> {
    const perception = getModelConfig("PERCEPTION")
    const apiKey =
      this.config.apiKey ??
      (perception.apiKey || undefined) ??
      process.env.VLM_MODEL_API_KEY ??
      process.env.VLM_API_KEY ??
      process.env.LLM_API_KEY ??
      process.env.GEMINI_API_KEY

    if (!apiKey || apiKey.length === 0) {
      throw new Error("VLM_MODEL_API_KEY, VLM_API_KEY, LLM_API_KEY, or GEMINI_API_KEY is not set. Source .env first.")
    }

    const endpoint =
      this.config.endpoint ??
      process.env.VLM_ENDPOINT ??
      process.env.LLM_ENDPOINT ??
      "https://api.openai.com/v1/chat/completions"

    const model =
      this.config.model ??
      (perception.modelName || undefined) ??
      process.env.VLM_MODEL_NAME ??
      process.env.VLM_MODEL ??
      process.env.LLM_MODEL ??
      "gemini-1.5-flash"

    const cleanBase64 = request.screenshotBase64.replace(/^data:image\/[a-zA-Z]+;base64,/, "")

    const messages = [
      { role: "system", content: request.systemPrompt },
      {
        role: "user",
        content: [
          { type: "text", text: request.userPrompt },
          { type: "image_url", image_url: { url: `data:image/png;base64,${cleanBase64}` } },
        ],
      },
    ]

    const res = await fetch(endpoint, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model,
        messages,
        temperature: 0.1,
      }),
    })

    if (!res.ok) {
      const errBody = await res.text().catch(() => "")
      throw new Error(`VLM request failed: HTTP ${res.status} ${errBody.slice(0, 200)}`)
    }

    const data = (await res.json()) as {
      choices?: Array<{ message?: { content?: unknown } }>
    }
    const content = data?.choices?.[0]?.message?.content
    if (typeof content !== "string") {
      throw new Error("VLM response missing string content")
    }
    return content
  }

  async generate(request: VlmRequest): Promise<string> {
    return this.complete(request)
  }

  async analyze(request: VlmRequest): Promise<string> {
    return this.complete(request)
  }
}

export const LiveVlm = LiveVlmClient

/** Factory to create either a live or mock VLM client. Defaults to mock for safe offline operation. */
export function createVlmClient(
  kind: "live" | "mock" = process.env.VLM_MODE === "live" ? "live" : "mock",
  config: VlmClientConfig = {}
): VlmClient {
  const perception = getModelConfig("PERCEPTION")
  const resolvedConfig: VlmClientConfig = {
    apiKey: config.apiKey ?? (perception.apiKey || undefined),
    model: config.model ?? (perception.modelName || undefined),
    ...config,
  }
  return kind === "live" ? new LiveVlmClient(resolvedConfig) : new MockVlmClient(resolvedConfig)
}

let defaultVlmClient: VlmClient = new MockVlmClient()
// HONESTY (audit B4): the default VLM client is ALWAYS MockVlmClient — no live
// VLM call has ever executed unless a caller explicitly wires setVlmClient(new
// LiveVlmClient(...)) or VLM_MODE=live. Every slop score produced through this
// default is a fixture value, not a model judgment; scan surfaces must label it
// MOCK (see scan-url.ts SCAN_MOCK_DISCLOSURE).

/** Override the module-level VLM client instance. */
export function setVlmClient(client: VlmClient): void {
  defaultVlmClient = client
}

/** Get the active module-level VLM client. */
export function getVlmClient(): VlmClient {
  return defaultVlmClient
}

/** Reset the module-level VLM client to a fresh default mock client. */
export function resetVlmClient(): void {
  defaultVlmClient = new MockVlmClient()
}

/** Robustly parses raw model text into a validated SlopReport. */
export function parseSlopReport(content: string): SlopReport {
  const trimmed = content.trim()
  if (!trimmed) {
    throw new Error("Empty VLM response")
  }

  let parsed: unknown
  try {
    parsed = JSON.parse(trimmed)
  } catch {
    // Attempt markdown code block extraction
    const jsonMatch = trimmed.match(/```(?:json)?\s*([\s\S]*?)\s*```/i)
    if (jsonMatch && jsonMatch[1]) {
      try {
        parsed = JSON.parse(jsonMatch[1].trim())
      } catch {
        // Fall through to brace scan
      }
    }
    if (!parsed) {
      const start = trimmed.indexOf("{")
      const end = trimmed.lastIndexOf("}")
      if (start === -1 || end === -1 || end <= start) {
        throw new Error("No JSON object found in VLM response")
      }
      const slice = trimmed.slice(start, end + 1)
      try {
        parsed = JSON.parse(slice)
      } catch {
        // Relax single quotes if encountered
        try {
          const relaxed = slice.replace(/'/g, '"')
          parsed = JSON.parse(relaxed)
        } catch {
          throw new Error("Malformed JSON object in VLM response")
        }
      }
    }
  }

  if (typeof parsed !== "object" || parsed === null) {
    throw new Error("VLM response is not an object")
  }

  const obj = parsed as Record<string, unknown>

  const rawScore = obj.slopScore
  const numScore = Number(rawScore)
  if (rawScore === undefined || rawScore === null || !Number.isFinite(numScore)) {
    throw new Error("Missing or invalid slopScore in VLM response")
  }
  const slopScore = Math.max(0, Math.min(100, Math.round(numScore)))

  let flags: string[] = []
  if (Array.isArray(obj.flags)) {
    flags = obj.flags.map((f) => String(f).trim()).filter((f) => f.length > 0)
  } else if (typeof obj.flags === "string") {
    flags = [obj.flags.trim()].filter((f) => f.length > 0)
  } else {
    throw new Error("Missing or invalid flags array in VLM response")
  }

  const rawRec = obj.recommendation
  if (typeof rawRec !== "string") {
    throw new Error("Missing or invalid recommendation in VLM response")
  }
  const recommendation = rawRec.trim()

  return {
    slopScore,
    flags,
    recommendation,
  }
}

/** Options object for evaluateDesignQuality. */
export interface EvaluateDesignQualityOptions {
  designSystemContext?: string
  client?: VlmClient
}

function isVlmClient(val: unknown): val is VlmClient {
  return typeof val === "object" && val !== null && typeof (val as VlmClient).complete === "function"
}

/**
 * Evaluates sandbox screenshot quality and flags AI slop aesthetics using a lightweight VLM.
 *
 * @param screenshotBase64 Base64-encoded PNG/JPEG screenshot (with or without data URI scheme).
 * @param designSystemContext Optional design system guidelines, tokens, or options object.
 * @param clientOverride Optional VlmClient to use for this specific call (defaults to module or mock client).
 * @returns Parsed SlopReport containing slopScore, flags, and actionable recommendation.
 */
export async function evaluateDesignQuality(
  screenshotBase64: string,
  designSystemContext?: string | EvaluateDesignQualityOptions | VlmClient,
  clientOverride?: VlmClient
): Promise<SlopReport> {
  let context: string | undefined
  let client: VlmClient | undefined

  if (isVlmClient(designSystemContext)) {
    client = designSystemContext
  } else if (typeof designSystemContext === "object" && designSystemContext !== null) {
    context = designSystemContext.designSystemContext
    client = designSystemContext.client
  } else if (typeof designSystemContext === "string") {
    context = designSystemContext
  }

  if (clientOverride) {
    client = clientOverride
  }

  const activeClient = client ?? defaultVlmClient

  let userPrompt = "Analyze this screenshot against modern design standards for AI slop and UI flaws."
  if (context && context.trim().length > 0) {
    userPrompt = `Design system context:\n${context.trim()}\n\nAnalyze this screenshot against this design system context and modern design standards for AI slop and UI flaws.`
  }

  const rawResponse = await activeClient.complete({
    systemPrompt: SLOP_SYSTEM_PROMPT,
    userPrompt,
    screenshotBase64,
  })

  return parseSlopReport(rawResponse)
}
