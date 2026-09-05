/**
 * action.ts — the closed Action union + the single reducer to the browser.
 *
 * DESIGN.md §3 doctrine: the agent is **pixels in, coordinates out**. It may act
 * ONLY through this bounded action set and observe ONLY screenshots. This module
 * is the ONE place that touches the browser page. The model never receives DOM
 * data, selectors, accessibility nodes, or element boxes. The harness does use a
 * small `page.evaluate` grounding step to snap an imprecise pixel click to the
 * nearest visible interactive element; that DOM access is harness-only and is
 * never exposed to the model.
 *
 * `type` targets the CURRENTLY FOCUSED element (the agent must `click` a field
 * first to focus it), mirroring real computer-use.
 */

/** The closed action union (DESIGN.md §3). */
export type Action =
  | { kind: "click"; x: number; y: number } // click at viewport CSS coords
  | { kind: "type"; text: string } // keystrokes into the CURRENTLY FOCUSED element
  | { kind: "press"; keys: string } // e.g. "Enter" | "Tab" | "Escape"
  | { kind: "nav"; url: string } // page navigation (same-origin; see buildNavUrl)
  | { kind: "done" } // agent believes the task is complete (NOT success)
  | { kind: "abort"; reason: string } // give up / stuck / cost ceiling

/** True when `kind` names a member of the closed union. */
export function isActionKind(kind: unknown): kind is Action["kind"] {
  return (
    kind === "click" ||
    kind === "type" ||
    kind === "press" ||
    kind === "nav" ||
    kind === "done" ||
    kind === "abort"
  )
}

/** The subset of the browser page the reducer is allowed to drive. */
export interface BrowserPage {
  mouse: { click(x: number, y: number): Promise<void> }
  keyboard: { type(text: string): Promise<void>; press(keys: string): Promise<void> }
  goto(url: string): Promise<unknown>
  /** Harness-side DOM evaluate. Used ONLY to snap clicks to real elements (hybrid grounding); never exposed to the model. */
  evaluate<A, R>(fn: (arg: A) => R, arg: A): Promise<R>
}

// Hybrid grounding: the model still outputs pixel coordinates (vision-first), but
// the HARNESS snaps an imprecise click to the nearest real interactive element
// (input/textbox/button/select/link) so the click actually lands. The model never
// sees the DOM — this runs purely on the harness side. DESIGN.md §3 doctrine is
// preserved for what the model observes (pixels only); this only fixes click precision.
const INTERACTIVE_SELECTOR =
  'input, textarea, select, button, a, [role="button"], [role="textbox"], [contenteditable="true"], [tabindex]:not([tabindex="-1"])'
const SNAP_MAX_RADIUS = 170

/** Snap an (x,y) to the nearest visible interactive element's center, else keep (x,y). */
async function snapToInteractive(page: BrowserPage, x: number, y: number): Promise<{ x: number; y: number }> {
  try {
    const res = await page.evaluate(
      (args: { x: number; y: number; maxRadius: number; sel: string }) => {
        const x = args.x
        const y = args.y
        let best: { cx: number; cy: number } | null = null
        let bestD = Infinity
        for (const e of Array.from(document.querySelectorAll<HTMLElement>(args.sel))) {
          const r = e.getBoundingClientRect()
          if (r.width < 1 || r.height < 1) continue
          const cx = r.left + r.width / 2
          const cy = r.top + r.height / 2
          const d = Math.hypot(cx - x, cy - y)
          if (d < bestD) {
            bestD = d
            best = { cx, cy }
          }
        }
        if (best && bestD <= args.maxRadius) return { x: Math.round(best.cx), y: Math.round(best.cy) }
        return null
      },
      { x, y, maxRadius: SNAP_MAX_RADIUS, sel: INTERACTIVE_SELECTOR },
    )
    if (res) return res
  } catch {
    // Grounding unavailable (e.g. mock page) -> use raw coordinates.
  }
  return { x, y }
}

/**
 * Build a path URL from a Solari `previewUrl` base using `new URL(path, base)`,
 * PRESERVING the base's query string when the path has none. The Solari
 * `previewUrl` may already carry a gateway auth token (`?pt_token=…`); a bare
 * `new URL(path, base)` drops it (DESIGN.md §3/§7 — never string-concat). This
 * mirrors `buildUrl` in orchestrate.ts, kept local so the agent is self-contained
 * and free of orchestration/SDK coupling.
 */
export function buildNavUrl(base: string, path: string): string {
  const b = new URL(base)
  const u = new URL(path, b)
  if (b.search && !u.search) u.search = b.search
  return u.toString()
}

/**
 * Execute an action against the browser. `click→mouse.click(x,y)`,
 * `type→keyboard.type(text)`, `press→keyboard.press(keys)`,
 * `nav→goto(new URL(path, base).href)`. `done`/`abort` are handled by the loop
 * (they stop it) — the reducer treats them as no-ops here.
 */
export async function executeAction(page: BrowserPage, action: Action, baseUrl: string): Promise<void> {
  switch (action.kind) {
    case "click": {
      const p = await snapToInteractive(page, action.x, action.y)
      await page.mouse.click(p.x, p.y)
      break
    }
    case "type":
      await page.keyboard.type(action.text)
      break
    case "press":
      await page.keyboard.press(action.keys)
      break
    case "nav":
      await page.goto(buildNavUrl(baseUrl, action.url))
      break
    case "done":
    case "abort":
      // Loop terminal conditions; nothing to execute on the browser.
      break
  }
}
