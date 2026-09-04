/**
 * slop-catcher.test.ts — Unit tests for the Slop-Catcher VLM design QA module.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import {
  evaluateDesignQuality,
  parseSlopReport,
  createVlmClient,
  setVlmClient,
  resetVlmClient,
  MockVlmClient,
  SLOP_SYSTEM_PROMPT,
  type SlopReport,
  type VlmClient,
} from "../src/design-qa/slop-catcher.ts"

describe("Slop-Catcher VLM Design QA", () => {
  const sampleScreenshot = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

  beforeEach(() => {
    resetVlmClient()
  })

  afterEach(() => {
    resetVlmClient()
    vi.restoreAllMocks()
  })

  it("has the exact expected system prompt", () => {
    const expected =
      "You are a senior UI/UX designer and 'AI Slop' detector. Analyze this screenshot against modern design standards. Look for: 1. Poor contrast ratios, 2. Inconsistent spacing or alignment, 3. Generic 'AI slop' aesthetics (e.g., default Inter font, generic purple gradients, cluttered hierarchy). Return ONLY a valid JSON response matching this structure: { 'slopScore': number, 'flags': string[], 'recommendation': string }."
    expect(SLOP_SYSTEM_PROMPT).toBe(expected)
  })

  it("correctly parses mock VLM JSON response and returns SlopReport without network calls", async () => {
    const samplePayload: SlopReport = {
      slopScore: 85,
      flags: ["Low contrast on submit button", "Generic gradient background"],
      recommendation: "Increase contrast on primary action buttons and replace generic gradients with a clean neutral background.",
    }

    const mockClient = new MockVlmClient({
      mockResponse: samplePayload,
    })

    const report = await evaluateDesignQuality(sampleScreenshot, undefined, mockClient)

    expect(report.slopScore).toBe(85)
    expect(report.flags).toEqual([
      "Low contrast on submit button",
      "Generic gradient background",
    ])
    expect(report.recommendation).toBe(
      "Increase contrast on primary action buttons and replace generic gradients with a clean neutral background."
    )

    // Verify mock client received the call and inspected parameters
    expect(mockClient.calls).toHaveLength(1)
    expect(mockClient.calls[0]?.systemPrompt).toBe(SLOP_SYSTEM_PROMPT)
    expect(mockClient.calls[0]?.screenshotBase64).toBe(sampleScreenshot)
  })

  it("passes designSystemContext to the VLM user prompt when provided", async () => {
    const samplePayload = JSON.stringify({
      slopScore: 40,
      flags: ["Off-brand accent color"],
      recommendation: "Use brand primary teal.",
    })

    const mockClient = new MockVlmClient({ mockResponse: samplePayload })
    const context = "Our design system specifies 8px border radius, strict slate-900 typography, and brand teal (#00B4D8)."

    const report = await evaluateDesignQuality(sampleScreenshot, context, mockClient)

    expect(report.slopScore).toBe(40)
    expect(mockClient.calls).toHaveLength(1)
    expect(mockClient.calls[0]?.userPrompt).toContain(context)
  })

  it("supports passing options object with designSystemContext and client", async () => {
    const mockClient = new MockVlmClient({
      mockResponse: {
        slopScore: 20,
        flags: ["Slight margin asymmetry"],
        recommendation: "Center the container horizontally.",
      },
    })

    const report = await evaluateDesignQuality(sampleScreenshot, {
      designSystemContext: "Design token v2",
      client: mockClient,
    })

    expect(report.slopScore).toBe(20)
    expect(report.flags).toEqual(["Slight margin asymmetry"])
    expect(mockClient.calls[0]?.userPrompt).toContain("Design token v2")
  })

  it("supports passing client as second argument directly", async () => {
    const mockClient = new MockVlmClient({
      mockResponse: {
        slopScore: 15,
        flags: ["Minor: small font size on helper text"],
        recommendation: "Bump helper text from 10px to 12px.",
      },
    })

    const report = await evaluateDesignQuality(sampleScreenshot, mockClient)

    expect(report.slopScore).toBe(15)
    expect(report.flags).toEqual(["Minor: small font size on helper text"])
    expect(mockClient.calls).toHaveLength(1)
  })

  it("executes offline with default mock client when no client is provided", async () => {
    const report = await evaluateDesignQuality(sampleScreenshot)

    expect(typeof report.slopScore).toBe("number")
    expect(report.slopScore).toBeGreaterThanOrEqual(0)
    expect(report.slopScore).toBeLessThanOrEqual(100)
    expect(Array.isArray(report.flags)).toBe(true)
    expect(typeof report.recommendation).toBe("string")
  })

  it("respects setVlmClient and resetVlmClient", async () => {
    const customClient: VlmClient = {
      complete: vi.fn().mockResolvedValue(
        JSON.stringify({
          slopScore: 92,
          flags: ["Excessive neon glow", "Unreadable font"],
          recommendation: "Strip glow and restore standard font.",
        })
      ),
    }

    setVlmClient(customClient)
    const report = await evaluateDesignQuality(sampleScreenshot)

    expect(report.slopScore).toBe(92)
    expect(customClient.complete).toHaveBeenCalledTimes(1)

    resetVlmClient()
    const defaultReport = await evaluateDesignQuality(sampleScreenshot)
    expect(defaultReport.slopScore).not.toBe(92)
  })

  it("extracts JSON enclosed in markdown code fences", () => {
    const responseWithFences = "```json\n{\n  \"slopScore\": 75,\n  \"flags\": [\"Inconsistent padding\"],\n  \"recommendation\": \"Use 16px padding\"\n}\n```"
    const parsed = parseSlopReport(responseWithFences)
    expect(parsed.slopScore).toBe(75)
    expect(parsed.flags).toEqual(["Inconsistent padding"])
    expect(parsed.recommendation).toBe("Use 16px padding")
  })

  it("extracts JSON embedded in conversational prose", () => {
    const conversational = "Here is my evaluation:\n{\"slopScore\": 60, \"flags\": [\"Default Inter font\"], \"recommendation\": \"Use custom brand font\"}\nHope this helps!"
    const parsed = parseSlopReport(conversational)
    expect(parsed.slopScore).toBe(60)
    expect(parsed.flags).toEqual(["Default Inter font"])
    expect(parsed.recommendation).toBe("Use custom brand font")
  })

  it("clamps and rounds slopScore to 0..100", () => {
    const over100 = parseSlopReport(
      JSON.stringify({
        slopScore: 125.8,
        flags: ["Fatal contrast"],
        recommendation: "Redo theme",
      })
    )
    expect(over100.slopScore).toBe(100)

    const under0 = parseSlopReport(
      JSON.stringify({
        slopScore: -15,
        flags: [],
        recommendation: "Perfect",
      })
    )
    expect(under0.slopScore).toBe(0)
  })

  it("throws descriptive errors on malformed JSON or invalid schema", () => {
    expect(() => parseSlopReport("")).toThrow("Empty VLM response")
    expect(() => parseSlopReport("no json here at all")).toThrow("No JSON object found")
    expect(() => parseSlopReport(JSON.stringify({ flags: ["test"], recommendation: "fix" }))).toThrow("Missing or invalid slopScore")
    expect(() => parseSlopReport(JSON.stringify({ slopScore: 50, flags: 123, recommendation: "fix" }))).toThrow("Missing or invalid flags array")
    expect(() => parseSlopReport(JSON.stringify({ slopScore: 50, flags: ["test"], recommendation: 456 }))).toThrow("Missing or invalid recommendation")
  })

  it("createVlmClient creates mock client by default and live client on demand", () => {
    const mock = createVlmClient("mock")
    expect(mock).toBeInstanceOf(MockVlmClient)

    const live = createVlmClient("live", { apiKey: "test-key" })
    expect(live).toBeDefined()
    expect(typeof live.complete).toBe("function")
  })
})
