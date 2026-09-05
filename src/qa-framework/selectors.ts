/**
 * selectors.ts — Normalized Accessibility Selectors & Fuzzy Role Locators
 *
 * Prevents Loose Locator Fragility & Copy Drift:
 * Literal text matching (e.g. searching for "Logs:" with a colon while the actual
 * element renders "automation worker logs") causes brittle false negatives.
 *
 * This module standardizes semantic ARIA role matching, regex normalization,
 * whitespace collapsing, and punctuation tolerance.
 */

import type { MinimalLocator, MinimalPage } from "./assertions.js"

export interface AccessibleLocatorOptions {
  /** ARIA role: 'button' | 'dialog' | 'tab' | 'heading' | 'link' | 'textbox' etc. */
  role?: string
  /** Accessible name, label, or text pattern (string or RegExp). */
  name?: string | RegExp
  /** Fallback search by aria-label. */
  label?: string | RegExp
  /** Fallback placeholder text for inputs. */
  placeholder?: string | RegExp
  /** Exact or prefix data-testid. */
  testId?: string
  /** Strictness: whether to enforce single element match. */
  exact?: boolean
}

/**
 * Normalizes an arbitrary text string or pattern into a resilient, case-insensitive RegExp:
 * - Trims extraneous whitespace
 * - Strips trailing colons, semicolons, and punctuation commonly altered by UI design polish
 * - Escapes regex control characters if input was a plain string
 */
export function normalizePattern(input: string | RegExp): RegExp {
  if (input instanceof RegExp) {
    // Ensure case-insensitivity flag 'i' is present
    const flags = input.flags.includes("i") ? input.flags : input.flags + "i"
    return new RegExp(input.source, flags)
  }

  // Clean raw string: strip trailing punctuation like ":" or "..."
  const trimmed = input.trim().replace(/[:.,;!?]+$/, "")

  // Escape special regex characters
  const escaped = trimmed.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")

  // Replace whitespace sequences with flexible whitespace matcher
  const withFlexibleWhitespace = escaped.replace(/\s+/g, "\\s+")

  return new RegExp(withFlexibleWhitespace, "i")
}

/**
 * Creates an accessible locator using standard Playwright getByRole with normalized regex name.
 * Falls back to fuzzy label or selector queries if role is unavailable.
 */
export function fuzzyRoleLocator(
  page: MinimalPage,
  role: string,
  namePattern: string | RegExp,
  options: { exact?: boolean } = {}
): MinimalLocator {
  const pattern = normalizePattern(namePattern)

  if (typeof page.getByRole === "function") {
    return page.getByRole(role, { name: pattern, exact: options.exact ?? false })
  }

  // Fallback for custom page interfaces: attribute-based selector
  return page.locator(`[role="${role}"]:has-text("${namePattern}")`)
}

/**
 * Standardized helper for accessible buttons with copy-drift tolerance.
 * Example: `accessibleButton(page, /replace/i)` or `accessibleButton(page, "Replace")`
 */
export function accessibleButton(page: MinimalPage, namePattern: string | RegExp): MinimalLocator {
  return fuzzyRoleLocator(page, "button", namePattern)
}

/**
 * Standardized helper for accessible dialogs / modals.
 * Example: `accessibleDialog(page, /logs/i)` (matches "worker logs", "Logs: 12", etc.)
 */
export function accessibleDialog(page: MinimalPage, namePattern: string | RegExp): MinimalLocator {
  return fuzzyRoleLocator(page, "dialog", namePattern)
}

/**
 * Standardized helper for tabs.
 */
export function accessibleTab(page: MinimalPage, namePattern: string | RegExp): MinimalLocator {
  return fuzzyRoleLocator(page, "tab", namePattern)
}

/**
 * Unified selector factory that prioritizes semantic accessibility over brittle CSS.
 */
export function resolveAccessibleLocator(
  page: MinimalPage,
  options: AccessibleLocatorOptions
): MinimalLocator {
  if (options.role && options.name) {
    return fuzzyRoleLocator(page, options.role, options.name, { exact: options.exact })
  }

  if (options.label) {
    const pattern = normalizePattern(options.label)
    return page.locator(`[aria-label*="${pattern.source}" i]`)
  }

  if (options.placeholder) {
    const pattern = normalizePattern(options.placeholder)
    return page.locator(`input[placeholder*="${pattern.source}" i], textarea[placeholder*="${pattern.source}" i]`)
  }

  if (options.testId) {
    return page.locator(`[data-testid="${options.testId}"]`)
  }

  if (options.name) {
    const pattern = normalizePattern(options.name)
    return page.locator(`:text-matches("${pattern.source}", "i")`)
  }

  throw new Error(
    "resolveAccessibleLocator requires at least one selector criterion (role+name, label, placeholder, or testId)."
  )
}
