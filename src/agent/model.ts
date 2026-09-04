/**
 * model.ts — multimodal caller for the vision-first agent (DESIGN.md §3).
 *
 * Reads `LLM_API_KEY` / `LLM_ENDPOINT` / `LLM_MODEL` from `process.env` ONLY
 * (sourced from `.env` in-shell by the caller). The key is injected into the
 * agent process (loop.ts) and never reaches the variant app, the verifier, or
 * any file.
 *
 * Input per turn: { task, image (base64 PNG), history: Action[], step }.
 * Output: `{ action: Action, rationale?: string }`. Because the endpoint may
 * not support structured output, we emit a strict JSON envelope and parse it
 * ROBUSTLY here (find the first {...} block), with a ONE-SHOT repair re-ask on a
 * parse failure.
 *
 * Contamination guards: the model sees only the task instruction (channel 2)
 * + the screenshot (channel 1) + the compact prior-action history (channel 3).
 * It never sees the variant seed, the axis intensities, the expected DB values,
 * or the verifier's checks.
 */
import type { Action } from "./action.ts"
import { isActionKind } from "./action.ts"
import { getModelConfig } from "../config/model-router.ts"

// ---------------------------------------------------------------------------
// Environment (secrets never logged / written)
// ---------------------------------------------------------------------------

function requireEnv(name: string): string {
  const v = process.env[name]
  if (!v || v.length === 0) throw new Error(`${name} is not set — source .env in-shell first`)
  return v
}

// ---------------------------------------------------------------------------
// Model contract (dependency injection so the loop is testable without a key)
// ---------------------------------------------------------------------------

export interface ModelTurnInput {
  /** The seed-derived natural-language task instruction (channel 2). */
  task: string
  /** base64 PNG bytes (no `data:` prefix). */
  imageBase64: string
  /** Prior actions, chronological (channel 3 — never DOM text). */
  history: Action[]
  /** Current turn number (1-based). */
  step: number
  /** Hard step cap, so the model can `done`/`abort` with awareness of budget. */
  maxSteps: number
}

export interface ModelDecision {
  action: Action
  rationale?: string
}

export interface ModelCaller {
  decide(input: ModelTurnInput): Promise<ModelDecision>
}

// ---------------------------------------------------------------------------
// Prompt (doctrine, kept constant — no seed / axis / expected values)
// ---------------------------------------------------------------------------

const SYSTEM_PROMPT = `You are a vision-first computer-use agent operating a browser with a keyboard and a mouse.

DOCTRINE (non-negotiable):
- You act ONLY from the screenshot and the task instruction. You never read the DOM, never use selectors, innerText, locators, accessibility trees, or element bounding boxes.
- The screenshot is the full viewport, 1280 wide by 800 tall. Click coordinates are integer CSS pixels in that space (x: 0..1280, y: 0..800).

ACTION UNION (the ONLY things you may do). Output ONE JSON object, nothing else:
{"action": {...}, "rationale": "short reason"}

  - click: {"kind":"click","x":<int>,"y":<int>}   -> click at viewport coordinates
  - type:  {"kind":"type","text":"<string>"}      -> type into the CURRENTLY FOCUSED field
  - press: {"kind":"press","keys":"<string>"}     -> press a key ("Enter","Tab","Escape",...)
  - nav:   {"kind":"nav","url":"<path>"}          -> go to a same-origin page path (e.g. "/new")
  - done:  {"kind":"done"}                        -> the task is complete (you submitted and reached the confirmation page)
  - abort: {"kind":"abort","reason":"<string>"}   -> you are stuck / cannot proceed

HOW TO FILL A FORM FIELD (strict discipline — follow EXACTLY):
  For each field do EXACTLY TWO actions: (1) click the input to focus it, then (2) type the field's value into the now-focused field.
  RULES:
    - NEVER emit two "click" actions in a row on the same field. If you just clicked a field, your IMMEDIATE next action MUST be "type" (or "press") for that field.
    - Do NOT click a field you already focused, or an already-filled field. Move ONWARD through the form (top-to-bottom / left-to-right).
    - Never revisit a field you already filled; if you typed a value, do not click it again.
    - Do NOT click the top navigation / menu links ("Invoices", "New Invoice", "Reports", or any header/menu link). Clicking them navigates away and resets the form. STAY ON THE FORM.
    - NEVER use the "nav" action during this task — you are already on the correct form. Do not navigate anywhere.
    - Do NOT use keyboard shortcuts (e.g. Ctrl+A / Control+a / select-all). Type each value plainly with "type".
    - After ALL required fields are filled (Customer, dates, tax, and the one line item), your next action MUST be to click the submit/create button — not a field, not a nav link.
    - The screenshot shows the full form; read the TASK for each field's value and fill every required field before submitting.
  When ALL fields are filled, click the submit/create button, then confirm you reached the confirmation page.

Terminal conditions:
  - Say "done" ONLY after you have submitted the form AND you can see the confirmation page for the created invoice.
  - Say "abort" with a reason ONLY if the task genuinely cannot be completed (do NOT use it while fields remain).
  - Otherwise always choose the single best NEXT action.

Respond with ONLY the JSON object. No prose, no markdown fences.`

function buildUserText(input: ModelTurnInput): string {
  const historyText = JSON.stringify(input.history)
  return [
    `TASK:`,
    input.task,
    ``,
    `PRIOR ACTIONS (chronological; compact):`,
    historyText || "(none yet)",
    ``,
    `STEP ${input.step} of ${input.maxSteps}.`,
    `Decide the NEXT action based on the screenshot and the task.`,
    `If you already see the confirmation page, use {"action":{"kind":"done"}}.`,
    `If you are stuck, use {"action":{"kind":"abort","reason":"..."}}. Otherwise choose the single best next action.`,
    `Respond with ONLY the JSON object: {"action":{...},"rationale":"..."}`,
  ].join("\n")
}

function buildContent(input: ModelTurnInput): Array<{ type: "text"; text: string } | { type: "image_url"; image_url: { url: string } }> {
  return [
    { type: "text", text: buildUserText(input) },
    { type: "image_url", image_url: { url: `data:image/png;base64,${input.imageBase64}` } },
  ]
}

const REPAIR_USER_TEXT = `Your previous response was not a single valid JSON object. Re-do it now. Reply with ONLY one valid JSON object and nothing else: {"action":{...},"rationale":"..."} for the NEXT action.`

// ---------------------------------------------------------------------------
// Robust JSON extraction + normalization
// ---------------------------------------------------------------------------

/** Parse the model content, tolerating JSON buried in prose or code fences. */
export function parseJsonFlexibly(content: string): unknown {
  const trimmed = content.trim()
  if (!trimmed) throw new Error("empty model content")
  try {
    return JSON.parse(trimmed)
  } catch {
    // fall through to brace-scan
  }
  const start = trimmed.indexOf("{")
  const end = trimmed.lastIndexOf("}")
  if (start === -1 || end === -1 || end <= start) {
    throw new Error(`no JSON object in model response`)
  }
  try {
    return JSON.parse(trimmed.slice(start, end + 1))
  } catch {
    throw new Error("JSON object is malformed")
  }
}

/** Coerce/validate an unknown value into a closed-union `Action`. */
export function normalizeAction(raw: unknown): Action {
  if (typeof raw !== "object" || raw === null) throw new Error("action is not an object")
  const o = raw as Record<string, unknown>
  const kind = o.kind
  if (!isActionKind(kind)) throw new Error(`unknown action kind: ${String(kind)}`)
  switch (kind) {
    case "click": {
      const x = Number(o.x)
      const y = Number(o.y)
      if (!Number.isFinite(x) || !Number.isFinite(y)) throw new Error("click requires numeric x,y")
      return { kind, x: Math.round(x), y: Math.round(y) }
    }
    case "type": {
      const text = String(o.text ?? "")
      if (!text) throw new Error("type requires non-empty text")
      return { kind, text }
    }
    case "press": {
      const keys = String(o.keys ?? "")
      if (!keys) throw new Error("press requires keys")
      return { kind, keys }
    }
    case "nav": {
      const url = String(o.url ?? "")
      if (!url) throw new Error("nav requires url")
      return { kind, url }
    }
    case "done":
      return { kind }
    case "abort": {
      const reason = String(o.reason ?? "")
      return { kind, reason }
    }
  }
}

/** Parse a model response into a validated `ModelDecision`. */
export function extractDecision(content: string): ModelDecision {
  const obj = parseJsonFlexibly(content)
  if (typeof obj !== "object" || obj === null) throw new Error("decision is not an object")
  const o = obj as Record<string, unknown>
  const action = normalizeAction(o.action)
  const rationale = typeof o.rationale === "string" ? o.rationale : undefined
  return { action, rationale }
}

// ---------------------------------------------------------------------------
// Network call (OpenAI-compatible chat completions)
// ---------------------------------------------------------------------------

interface ChatMessage {
  role: "system" | "user" | "assistant"
  content: unknown
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

// Transient statuses we retry with backoff (rate limit / gateway hiccups).
const RETRYABLE_STATUS = new Set([429, 502, 503, 504])
const MAX_LLM_ATTEMPTS = 6
const MAX_BACKOFF_MS = 15000

async function postChat(messages: ChatMessage[]): Promise<string> {
  // W10: the ACTION model config is resolved through the Multi-Model Router
  // (src/config/model-router.ts), NOT read directly from LLM_* here. The router
  // prefers ACTION_MODEL_PROVIDER / ACTION_MODEL_NAME / ACTION_MODEL_API_KEY and
  // falls back to the legacy LLM_* variables, so existing .env setups keep
  // working unchanged — but the ACTION chain is now the single source of truth
  // for the agent path, matching the documented router behavior.
  //
  // Endpoint: the router carries no endpoint field, so the endpoint still comes
  // from LLM_ENDPOINT (an [OI]-compatible chat-completions URL).
  const action = getModelConfig("ACTION")
  const key = action.apiKey || requireEnv("LLM_API_KEY")
  const endpoint = requireEnv("LLM_ENDPOINT")
  const model = action.modelName || requireEnv("LLM_MODEL")

  let lastStatus = 0
  let lastBody = ""
  for (let attempt = 0; attempt < MAX_LLM_ATTEMPTS; attempt++) {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
      body: JSON.stringify({ model, messages, temperature: 0 }),
    })

    if (res.ok) {
      const data = (await res.json()) as {
        choices?: Array<{ message?: { content?: unknown } }>
      }
      const content = data?.choices?.[0]?.message?.content
      if (typeof content !== "string") throw new Error("LLM response has no string content")
      return content
    }

    if (!RETRYABLE_STATUS.has(res.status)) {
      const body = await res.text().catch(() => "")
      throw new Error(`LLM request failed: HTTP ${res.status} ${body.slice(0, 200)}`)
    }

    // Transient: honor Retry-After when present, else exponential backoff + jitter.
    lastStatus = res.status
    lastBody = (await res.text().catch(() => "")).slice(0, 120)
    const raRaw = res.headers.get("retry-after")
    const raMs = raRaw ? Number(raRaw) * 1000 : 0
    const delay = Math.min(Math.max(raMs, 0) || (1000 * 2 ** attempt + Math.floor(Math.random() * 400)), MAX_BACKOFF_MS)
    console.warn(`[model] LLM HTTP ${res.status} (${lastBody}); retrying in ${Math.round(delay)}ms (attempt ${attempt + 1}/${MAX_LLM_ATTEMPTS})`)
    await sleep(delay)
  }

  throw new Error(`LLM request failed after ${MAX_LLM_ATTEMPTS} attempts (last HTTP ${lastStatus}): ${lastBody}`)
}

/**
 * Ask the model for the next action, with a ONE-SHOT repair on a parse failure.
 * Never sends the seed / axis intensities / expected / verifier info.
 */
async function decideWithRepair(input: ModelTurnInput): Promise<ModelDecision> {
  const messages: ChatMessage[] = [
    { role: "system", content: SYSTEM_PROMPT },
    { role: "user", content: buildContent(input) },
  ]
  const first = await postChat(messages)
  try {
    return extractDecision(first)
  } catch (e) {
    // ONE-SHOT repair: re-ask once, keeping the screenshot visible.
    const repairMessages: ChatMessage[] = [
      { role: "system", content: SYSTEM_PROMPT },
      { role: "user", content: buildContent(input) },
      { role: "assistant", content: first },
      { role: "user", content: [{ type: "text", text: REPAIR_USER_TEXT }] },
    ]
    const second = await postChat(repairMessages)
    // If the repair also fails, we propagate the parse error (honest fail).
    return extractDecision(second)
  }
}

// ---------------------------------------------------------------------------
// Real caller factory
// ---------------------------------------------------------------------------

/** Build a live `ModelCaller` bound to the LLM_* environment. */
export function createModelCaller(): ModelCaller {
  return {
    async decide(input: ModelTurnInput): Promise<ModelDecision> {
      return decideWithRepair(input)
    },
  }
}
