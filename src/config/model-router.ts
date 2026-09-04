/**
 * model-router.ts — Multi-Model Router configuration.
 *
 * Decouples the heavy Computer-Use Agent (ACTION role) from the lightweight
 * Vision-Language Model (PERCEPTION role / Slop-Catcher).
 *
 * Supports role-based configuration with graceful backwards compatibility
 * falling back to single-model environment variables (OPENAI_API_KEY, LLM_API_KEY, etc.).
 *
 * Consumption (audit W10): the ACTION chain is consumed by the live agent path
 * (src/agent/model.ts postChat resolves via getModelConfig("ACTION")); the
 * PERCEPTION chain is consumed by the VLM clients (src/design-qa/slop-catcher.ts).
 * Both roles are wired into running code — not config scaffolding.
 */

export type ModelRole = "ACTION" | "PERCEPTION"

export interface ModelConfig {
  provider: string
  modelName: string
  apiKey: string
}

/**
 * Resolves the configuration for a given model role (ACTION or PERCEPTION).
 * Reads from process.env with fallbacks to legacy environment variables.
 *
 * @param role 'ACTION' for heavy CUA execution or 'PERCEPTION' for lightweight VLM design audits.
 * @returns ModelConfig containing provider, modelName, and apiKey.
 */
export function getModelConfig(role: "ACTION" | "PERCEPTION"): ModelConfig {
  if (role === "ACTION") {
    const provider =
      process.env.ACTION_MODEL_PROVIDER ??
      process.env.LLM_PROVIDER ??
      process.env.MODEL_PROVIDER ??
      "openai"

    const modelName =
      process.env.ACTION_MODEL_NAME ??
      process.env.LLM_MODEL ??
      process.env.MODEL_NAME ??
      "gpt-5.6-luna"

    const apiKey =
      process.env.ACTION_MODEL_API_KEY ??
      process.env.LLM_API_KEY ??
      process.env.OPENAI_API_KEY ??
      ""

    return { provider, modelName, apiKey }
  }

  // PERCEPTION role (VLM / Slop-Catcher)
  const provider =
    process.env.VLM_MODEL_PROVIDER ??
    process.env.VLM_PROVIDER ??
    (process.env.GEMINI_API_KEY ? "google" : undefined) ??
    process.env.LLM_PROVIDER ??
    "google"

  const modelName =
    process.env.VLM_MODEL_NAME ??
    process.env.VLM_MODEL ??
    process.env.LLM_MODEL ??
    process.env.MODEL_NAME ??
    "gemini-1.5-flash"

  const apiKey =
    process.env.VLM_MODEL_API_KEY ??
    process.env.VLM_API_KEY ??
    process.env.GEMINI_API_KEY ??
    process.env.LLM_API_KEY ??
    process.env.OPENAI_API_KEY ??
    ""

  return { provider, modelName, apiKey }
}
