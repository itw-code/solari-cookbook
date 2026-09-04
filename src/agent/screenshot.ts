/**
 * screenshot.ts — capture the full-viewport PNG and encode it for the model.
 *
 * DESIGN.md §3: the ONE legitimate observation channel is `page.screenshot()`
 * → PNG bytes. We pin a fixed viewport (default 1280×800, no device scale) and
 * clip to the full viewport so the model's `(x,y)` stays stable. No DOM access.
 */

export interface Viewport {
  width: number
  height: number
}

export const DEFAULT_VIEWPORT: Viewport = { width: 1280, height: 800 }

export interface ScreenshotClip {
  x: number
  y: number
  width: number
  height: number
}

/** The screenshot-capable subset of the browser page. */
export interface ScreenshotPage {
  screenshot(opts?: { clip?: ScreenshotClip; type?: "png" | "jpeg"; quality?: number }): Promise<Buffer | string>
}

// Full-fidelity PNG for crisp coordinate grounding (VLM spatial precision).
export const SCREENSHOT_MIME = "image/png"
export const SCREENSHOT_QUALITY = 100

/** Capture the full viewport as PNG bytes (max fidelity for click precision). */
export async function captureScreenshot(page: ScreenshotPage, viewport: Viewport = DEFAULT_VIEWPORT): Promise<Buffer> {
  const clip: ScreenshotClip = { x: 0, y: 0, width: viewport.width, height: viewport.height }
  const out = await page.screenshot({ clip, type: "png" })
  // Playwright returns Buffer for image/* by default; be defensive about path strings.
  return Buffer.isBuffer(out) ? out : Buffer.from(out, "base64")
}

/** Base64-encode PNG bytes for the multimodal request (no data: prefix). */
export function toBase64(png: Buffer): string {
  return png.toString("base64")
}
