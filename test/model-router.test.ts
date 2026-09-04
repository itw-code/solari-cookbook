/**
 * model-router.test.ts — Unit tests for the Multi-Model Router configuration.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { getModelConfig } from "../src/config/model-router.ts"

describe("Multi-Model Router (getModelConfig)", () => {
  const originalEnv = { ...process.env }

  beforeEach(() => {
    // Reset process.env before each test
    process.env = { ...originalEnv }
    delete process.env.ACTION_MODEL_PROVIDER
    delete process.env.ACTION_MODEL_NAME
    delete process.env.ACTION_MODEL_API_KEY
    delete process.env.VLM_MODEL_PROVIDER
    delete process.env.VLM_MODEL_NAME
    delete process.env.VLM_MODEL_API_KEY
    delete process.env.LLM_API_KEY
    delete process.env.LLM_MODEL
    delete process.env.LLM_ENDPOINT
    delete process.env.OPENAI_API_KEY
    delete process.env.GEMINI_API_KEY
    delete process.env.VLM_API_KEY
    delete process.env.VLM_MODEL
  })

  afterEach(() => {
    process.env = originalEnv
  })

  it("correctly returns the VLM config when role: 'PERCEPTION' is passed with new env vars", () => {
    process.env.VLM_MODEL_PROVIDER = "google"
    process.env.VLM_MODEL_NAME = "gemini-1.5-flash"
    process.env.VLM_MODEL_API_KEY = "test-vlm-api-key"

    const config = getModelConfig("PERCEPTION")

    expect(config).toEqual({
      provider: "google",
      modelName: "gemini-1.5-flash",
      apiKey: "test-vlm-api-key",
    })
  })

  it("correctly returns the Action config when role: 'ACTION' is passed with new env vars", () => {
    process.env.ACTION_MODEL_PROVIDER = "openai"
    process.env.ACTION_MODEL_NAME = "gpt-5.6-luna"
    process.env.ACTION_MODEL_API_KEY = "test-action-api-key"

    const config = getModelConfig("ACTION")

    expect(config).toEqual({
      provider: "openai",
      modelName: "gpt-5.6-luna",
      apiKey: "test-action-api-key",
    })
  })

  it("gracefully falls back to legacy VLM / Gemini / LLM variables for PERCEPTION role", () => {
    // New variables omitted; set legacy variables
    process.env.GEMINI_API_KEY = "legacy-gemini-key"
    process.env.VLM_MODEL = "gemini-1.5-pro"

    const config = getModelConfig("PERCEPTION")

    expect(config.provider).toBe("google")
    expect(config.modelName).toBe("gemini-1.5-pro")
    expect(config.apiKey).toBe("legacy-gemini-key")
  })

  it("gracefully falls back to LLM_API_KEY and LLM_MODEL for ACTION role", () => {
    // New variables omitted; set legacy single-model variables
    process.env.LLM_API_KEY = "sk-legacy-openai-key"
    process.env.LLM_MODEL = "gpt-4o"

    const config = getModelConfig("ACTION")

    expect(config.provider).toBe("openai")
    expect(config.modelName).toBe("gpt-4o")
    expect(config.apiKey).toBe("sk-legacy-openai-key")
  })

  it("does not crash and returns sensible default structure when no env vars are defined", () => {
    const perception = getModelConfig("PERCEPTION")
    expect(perception.provider).toBeDefined()
    expect(perception.modelName).toBe("gemini-1.5-flash")
    expect(perception.apiKey).toBe("")

    const action = getModelConfig("ACTION")
    expect(action.provider).toBe("openai")
    expect(action.modelName).toBe("gpt-5.6-luna")
    expect(action.apiKey).toBe("")
  })

  it("resolves the live agent path through the router: postChat uses the ACTION chain (W10)", async () => {
    // Wire-through test: postChat must resolve its model via getModelConfig("ACTION").
    // LLM_MODEL is deliberately UNSET — only ACTION_MODEL_NAME provides the model —
    // so the pre-wiring code (requireEnv("LLM_MODEL")) throws before any network
    // call, while the wired code sends the routed model name to the endpoint.
    delete process.env.LLM_MODEL
    process.env.ACTION_MODEL_NAME = "routed-action-model"
    process.env.LLM_API_KEY = "test-key"
    process.env.LLM_ENDPOINT = "http://127.0.0.1:1/unreachable" // fails fast (connection refused)

    const fetchSpy = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("connection refused"))
    try {
      const { createModelCaller } = await import("../src/agent/model.ts")
      const caller = createModelCaller()

      // The call fails (unreachable endpoint) — but only AFTER the model was
      // resolved through the router.
      await expect(
        caller.decide({ task: "t", imageBase64: "img", history: [], step: 1, maxSteps: 5 }),
      ).rejects.toThrow()

      expect(fetchSpy).toHaveBeenCalledTimes(1)
      const body = JSON.parse((fetchSpy.mock.calls[0]![1] as RequestInit).body as string) as { model: string }
      expect(body.model).toBe("routed-action-model")
    } finally {
      fetchSpy.mockRestore()
    }
  })
})
