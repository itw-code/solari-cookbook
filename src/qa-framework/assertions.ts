/**
 * assertions.ts — Visual & Interactive Assertion Helpers for ColdStart
 *
 * Prevents the "Zero-Pixel Trap" (Batch 3, F-039):
 * In modern CSS (flexbox, CSS grid, absolute containers), an element may be present
 * in the DOM (`locator.count() > 0`), but flex-collapse, zero-height wrappers, or
 * overflow clipping causes it to render with 0px height (completely invisible).
 *
 * ColdStart assertions enforce:
 * 1. Element attachment & visibility state (`state: "visible"`)
 * 2. Positive bounding box dimensions (`width >= minWidth`, `height >= minHeight`)
 * 3. Non-zero computed opacity (`opacity !== "0"`)
 * 4. Active display and visibility (`display !== "none"`, `visibility !== "hidden"`)
 */

export interface InteractiveCheckOptions {
  /** Maximum wait time in milliseconds (default: 10000). */
  timeout?: number
  /** Minimum rendered width in pixels (default: 5). */
  minWidth?: number
  /** Minimum rendered height in pixels (default: 5). */
  minHeight?: number
  /** Descriptive label for actionable error messages. */
  label?: string
}

export interface MinimalBoundingBox {
  x: number
  y: number
  width: number
  height: number
}

export interface MinimalLocator {
  waitFor(options?: { state?: "attached" | "detached" | "visible" | "hidden"; timeout?: number }): Promise<void>
  boundingBox(): Promise<MinimalBoundingBox | null>
  evaluate?<R>(pageFunction: (element: HTMLElement) => R): Promise<R>
  toString?(): string
}

export interface MinimalPage {
  locator(selector: string): MinimalLocator
  getByRole?(role: string, options?: any): MinimalLocator
  waitForTimeout?(ms: number): Promise<void>
}

/**
 * Asserts that a Playwright Locator is not only present in the DOM,
 * but visually rendered with positive screen dimensions and interactive styling.
 *
 * Throws an explicit error if the element is flex-collapsed (Zero-Pixel Trap).
 */
export async function expectInteractive<T extends MinimalLocator>(
  locator: T,
  options: InteractiveCheckOptions = {}
): Promise<T> {
  const timeout = options.timeout ?? 10000
  const minWidth = options.minWidth ?? 5
  const minHeight = options.minHeight ?? 5
  const label = options.label ?? locator.toString?.() ?? "Target Element"

  // 1. Wait for Playwright's visibility state
  await locator.waitFor({ state: "visible", timeout })

  // 2. Inspect physical bounding box (prevents the Zero-Pixel Trap)
  const box = await locator.boundingBox()
  if (!box) {
    throw new Error(
      `[Zero-Pixel Trap] ${label} has no layout bounding box (null). Element is not rendered in layout flow.`
    )
  }

  if (box.width < minWidth || box.height < minHeight) {
    throw new Error(
      `[Zero-Pixel Trap] ${label} has zero or sub-threshold dimensions (${box.width}x${box.height}px, required at least ${minWidth}x${minHeight}px). ` +
        `This is characteristic of CSS flex-collapse (F-039) where DOM nodes exist but visual height is collapsed.`
    )
  }

  // 3. Computed style verification (if evaluate is available)
  if (typeof locator.evaluate === "function") {
    const styles = await locator.evaluate((el: HTMLElement) => {
      const computed = window.getComputedStyle(el)
      return {
        opacity: computed.opacity,
        visibility: computed.visibility,
        display: computed.display,
        pointerEvents: computed.pointerEvents,
      }
    })

    if (styles.opacity === "0") {
      throw new Error(`[Visual Invisibility] ${label} is present with dimensions ${box.width}x${box.height}px, but computed opacity is 0.`)
    }

    if (styles.visibility === "hidden" || styles.display === "none") {
      throw new Error(
        `[Visual Invisibility] ${label} is computed as visibility: ${styles.visibility}, display: ${styles.display}.`
      )
    }

    if (styles.pointerEvents === "none") {
      throw new Error(
        `[Non-Interactive] ${label} is rendered visually, but pointer-events: none prevents agent clicks.`
      )
    }
  }

  return locator
}

/**
 * Convenience wrapper: resolves selector or locator and asserts visual interactivity.
 */
export async function expectVisual(
  page: MinimalPage,
  selectorOrLocator: string | MinimalLocator,
  options: InteractiveCheckOptions = {}
): Promise<MinimalLocator> {
  const locator =
    typeof selectorOrLocator === "string" ? page.locator(selectorOrLocator) : selectorOrLocator
  return expectInteractive(locator, options)
}

/**
 * Asserts text visibility with positive dimensions on the page.
 */
export async function expectVisibleText(
  page: MinimalPage,
  textPattern: string | RegExp,
  options: InteractiveCheckOptions = {}
): Promise<MinimalLocator> {
  const pattern = typeof textPattern === "string" ? new RegExp(textPattern, "i") : textPattern
  const locator = page.locator(`:text-matches("${pattern.source}", "${pattern.flags}")`)
  return expectInteractive(locator, { ...options, label: `Text matching ${pattern}` })
}
