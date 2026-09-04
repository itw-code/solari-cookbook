/**
 * axes.ts — the 5 perturbation axes (DESIGN.md §2).
 *
 * Each axis maps an integer intensity k ∈ [0, K_max] to a concrete set of
 * perturbation params. `k = 0` is ALWAYS the canonical baseline (the un-perturbed
 * seed=0 app). Intensity is derived from the seed alone (a pure function), so
 * `sameSeed -> same variant`.
 *
 * Each axis derives its own domain-separated sub-stream via
 * `deriveStream(seed, axisId)`, so axes never interfere (DESIGN.md §2 determinism).
 */

import { deriveStream, pickInt, pick } from "./prng.js"

/** Stable identifiers for the five axes (used for domain separation + variant ids). */
export type AxisKey = "P1_relabel" | "P2_structure" | "P3_field_order" | "P4_nav_order" | "P5_theme"

export interface IntensityByAxis extends Record<AxisKey, number> {}

/** Per-axis maximum intensity (k ranges 0..K_max inclusive). */
export const AXIS_MAX: Record<AxisKey, number> = {
  P1_relabel: 4,
  P2_structure: 3,
  P3_field_order: 4,
  P4_nav_order: 2,
  P5_theme: 3,
}

/** The canonical, un-perturbed baseline intensity vector (seed=0). */
export const BASELINE_INTENSITY: IntensityByAxis = {
  P1_relabel: 0,
  P2_structure: 0,
  P3_field_order: 0,
  P4_nav_order: 0,
  P5_theme: 0,
}

/**
 * Derive the intensity vector from a seed. This is a PURE function: the same
 * seed always yields the same intensities. seed=0 is special-cased to the
 * canonical baseline (all axes k=0), per DESIGN.md §2.
 */
export function deriveIntensities(seed: number): IntensityByAxis {
  if (seed === 0) return { ...BASELINE_INTENSITY }
  const out = {} as IntensityByAxis
  for (const key of Object.keys(AXIS_MAX) as AxisKey[]) {
    const stream = deriveStream(seed, key)
    out[key] = pickInt(stream, AXIS_MAX[key])
  }
  return out
}

// ---------------------------------------------------------------------------
// P1 — Semantic relabeling & copy drift (HARDEST)
// ---------------------------------------------------------------------------

export interface P1LabelSet {
  create: string
  customer: string
  submit: string
  tax: string
  qty: string
  unitPrice: string
  description: string
  confirmation: string
  invoke: string
  listHeading: string
}

/** Each group: option[0] is ALWAYS the canonical baseline; others are synonyms. */
const P1_SYNONYMS: Record<keyof P1LabelSet, readonly string[]> = {
  create: ["Create Invoice", "New Bill", "Generate a Charge", "Record a Sale", "Add Invoice"],
  customer: ["Customer", "Client", "Billed To", "Account", "Bill To"],
  submit: ["Submit", "Confirm", "Record", "Done", "Finalize"],
  tax: ["Tax Rate", "VAT", "Sales Tax", "Tax", "Tax %"],
  qty: ["Qty", "Units", "Quantity", "Items"],
  unitPrice: ["Unit Price", "Rate", "Amount per Unit", "Price"],
  description: ["Description", "Detail", "Memo", "Item"],
  confirmation: ["Invoice Created", "Recorded", "Saved", "Posted!", "Done"],
  invoke: ["New Invoice", "New Bill", "Create New", "Add New", "Record New"],
  listHeading: ["Invoices", "Bills", "Charges", "Sales", "Records"],
}

/** k=0 baseline, k=1 ≈25% … k=K_max ≈100% of labels renamed. */
const P1_FRACTION = [0, 0.25, 0.5, 0.75, 1]

/** Deterministic Fisher-Yates using a stream. */
function shuffle<T>(stream: () => number, input: readonly T[]): T[] {
  const a = [...input]
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(stream() * (i + 1))
    const tmp = a[i]!
    a[i] = a[j]!
    a[j] = tmp
  }
  return a
}

export function buildP1(seed: number, k: number): P1LabelSet {
  const stream = deriveStream(seed, "P1_relabel")
  const groups = Object.keys(P1_SYNONYMS) as (keyof P1LabelSet)[]
  // Start from baseline (option[0] for every group).
  const labels = {} as P1LabelSet
  for (const g of groups) labels[g] = P1_SYNONYMS[g][0]!

  if (k === 0) return labels

  const fraction = P1_FRACTION[Math.min(k, P1_FRACTION.length - 1)] ?? 0
  const target = Math.round(fraction * groups.length)
  const toRename = shuffle(stream, groups).slice(0, target)

  for (const g of toRename) {
    const opts = P1_SYNONYMS[g]
    // Pick a non-baseline synonym: index 1..(len-1).
    labels[g] = pick(stream, opts.slice(1))
  }
  return labels
}

// ---------------------------------------------------------------------------
// P2 — Structure & flow reorder (VERY HARD)
// ---------------------------------------------------------------------------

export interface P2Config {
  /** Form shape: a single page, a two-step wizard, or a wizard + inline + add-row. */
  layout: "single" | "wizard" | "wizard_inline_addrows"
  /** Confirmation as a separate page vs. an inline success block. */
  confirmation: "page" | "inline"
  /** Where the create entry point lives in the page. */
  entryPosition: "topbar" | "sidebar" | "fab" | "midbody"
}

const P2_LAYOUT_BY_K: P2Config["layout"][] = ["single", "single", "wizard", "wizard_inline_addrows"]
const P2_CONFIRM_BY_K: P2Config["confirmation"][] = ["page", "page", "page", "inline"]
const P2_ENTRY_BY_K: P2Config["entryPosition"][] = ["topbar", "midbody", "topbar", "fab"]

export function buildP2(seed: number, k: number): P2Config {
  // k=0 baseline (defined explicitly), then structured per intensity with a
  // stream tie-break so that ties still resolve deterministically.
  const base: P2Config = { layout: "single", confirmation: "page", entryPosition: "topbar" }
  if (k === 0) return base
  const stream = deriveStream(seed, "P2_structure")
  const idx = Math.min(k, P2_LAYOUT_BY_K.length - 1)
  return {
    layout: P2_LAYOUT_BY_K[idx]!,
    confirmation: P2_CONFIRM_BY_K[idx]!,
    // Mid intensity (k=1) may choose among a couple of entry positions.
    entryPosition:
      k === 1 ? (stream() < 0.5 ? "midbody" : "sidebar") : P2_ENTRY_BY_K[idx]!,
  }
}

// ---------------------------------------------------------------------------
// P3 — Form field-order & density (HARD)
// ---------------------------------------------------------------------------

export type MetaField = "customer" | "invoice_date" | "due_date" | "tax_rate"
export type ItemField = "description" | "qty" | "unit_price"
export type OptionalField = "po_number" | "reference" | "notes"

export interface P3Config {
  metaOrder: MetaField[]
  itemOrder: ItemField[]
  optionalFields: OptionalField[]
  taxControl: "input" | "preset"
  datePrefill: "blank" | "today"
  defaultRows: number
}

const BASE_META: MetaField[] = ["customer", "invoice_date", "due_date", "tax_rate"]
const BASE_ITEM: ItemField[] = ["description", "qty", "unit_price"]

export function buildP3(seed: number, k: number): P3Config {
  const stream = deriveStream(seed, "P3_field_order")
  let metaOrder: MetaField[] = [...BASE_META]
  let itemOrder: ItemField[] = [...BASE_ITEM]
  let optionalFields: OptionalField[] = []
  let taxControl: P3Config["taxControl"] = "input"
  let datePrefill: P3Config["datePrefill"] = "blank"
  let defaultRows = 1

  if (k >= 1) {
    // Swap the first two meta fields (customer <-> invoice_date).
    metaOrder = [...metaOrder]
    if (stream() < 0.5) {
      const [a, b] = [metaOrder[0], metaOrder[1]]
      metaOrder[0] = b!
      metaOrder[1] = a!
    }
  }
  if (k >= 2) {
    metaOrder = shuffle(stream, metaOrder as MetaField[])
    itemOrder = shuffle(stream, itemOrder as ItemField[])
    optionalFields = optionalFields.concat(optionalFields.length === 0 ? ["po_number"] : [])
  }
  if (k >= 3) {
    optionalFields = ["po_number", "reference"]
    taxControl = "preset"
  }
  if (k >= 4) {
    optionalFields = ["po_number", "reference"]
    taxControl = "preset"
    datePrefill = "today"
    defaultRows = 2
  }
  return { metaOrder, itemOrder, optionalFields, taxControl, datePrefill, defaultRows }
}

// ---------------------------------------------------------------------------
// P4 — Navigation order & grouping (MODERATE)
// ---------------------------------------------------------------------------

export interface P4Config {
  order: ("invoices" | "new" | "reports")[]
  grouped: boolean
  navPosition: "top" | "side"
}

const BASE_NAV: P4Config["order"] = ["invoices", "new", "reports"]

export function buildP4(seed: number, k: number): P4Config {
  const stream = deriveStream(seed, "P4_nav_order")
  if (k === 0) return { order: [...BASE_NAV], grouped: false, navPosition: "top" }
  if (k === 1) return { order: shuffle(stream, BASE_NAV), grouped: false, navPosition: stream() < 0.5 ? "side" : "top" }
  return { order: shuffle(stream, BASE_NAV), grouped: true, navPosition: "side" }
}

// ---------------------------------------------------------------------------
// P5 — Theme / CSS skin (EASIEST — the control axis)
// ---------------------------------------------------------------------------

export interface P5Config {
  bg: string
  text: string
  muted: string
  accent: string
  accentText: string
  border: string
  font: string
  buttonStyle: "solid" | "outline" | "pill"
  radius: string
  dark: boolean
}

const P5_THEMES: P5Config[] = [
  // k=0 — canonical light baseline.
  { bg: "#ffffff", text: "#1f2937", muted: "#6b7280", accent: "#2563eb", accentText: "#ffffff", border: "#d1d5db", font: "system-ui, sans-serif", buttonStyle: "solid", radius: "6px", dark: false },
  // k=1 — hue shift (teal/green) + outline buttons.
  { bg: "#f5fbf9", text: "#134e4a", muted: "#52807a", accent: "#0f766e", accentText: "#ffffff", border: "#a7d3cf", font: "system-ui, sans-serif", buttonStyle: "outline", radius: "4px", dark: false },
  // k=2 — dark theme.
  { bg: "#0f172a", text: "#e2e8f0", muted: "#94a3b8", accent: "#f59e0b", accentText: "#1f2937", border: "#334155", font: "system-ui, sans-serif", buttonStyle: "solid", radius: "8px", dark: true },
  // k=3 — full re-theme (dark, serif, pill buttons, purple accent).
  { bg: "#1c1024", text: "#f3e8ff", muted: "#c4b5fd", accent: "#a855f7", accentText: "#ffffff", border: "#4c1d95", font: "Georgia, 'Times New Roman', serif", buttonStyle: "pill", radius: "999px", dark: true },
]

export function buildP5(_seed: number, k: number): P5Config {
  // k=0 baseline is explicit; deeper intensities pull from the palette.
  if (k === 0) return { ...P5_THEMES[0]! }
  return { ...P5_THEMES[Math.min(k, P5_THEMES.length - 1)]! }
}

// ---------------------------------------------------------------------------
// Consolidated config
// ---------------------------------------------------------------------------

export interface PerturbationConfig {
  /** The full intensity vector used to build this config. */
  axis: IntensityByAxis
  P1: P1LabelSet
  P2: P2Config
  P3: P3Config
  P4: P4Config
  P5: P5Config
}

/**
 * Pure function: seed -> full perturbation config. Consumed by the render layer
 * of the variant app and by the generator. `sameSeed -> sameConfig`.
 */
export function deriveConfig(seed: number): PerturbationConfig {
  const axis = deriveIntensities(seed)
  return {
    axis,
    P1: buildP1(seed, axis.P1_relabel),
    P2: buildP2(seed, axis.P2_structure),
    P3: buildP3(seed, axis.P3_field_order),
    P4: buildP4(seed, axis.P4_nav_order),
    P5: buildP5(seed, axis.P5_theme),
  }
}

/**
 * Build a perturbation config from an EXPLICIT intensity vector (not derived
 * from a seed). Used for axis-ISOLATED runs (COLDSTART_AXES): the harness
 * renders a single-axis-perturbed app with a constant task, so ONLY the one
 * active axis varies and the finding is causal.
 *
 * `seed` is used only for domain-separated sub-streams inside each axis build
 * (so a given intensity still resolves deterministically to the same concrete
 * params); the returned `axis` vector is exactly the given `intensities`.
 */
export function deriveConfigFromIntensities(intensities: IntensityByAxis, seed = 0): PerturbationConfig {
  return {
    axis: { ...intensities },
    P1: buildP1(seed, intensities.P1_relabel),
    P2: buildP2(seed, intensities.P2_structure),
    P3: buildP3(seed, intensities.P3_field_order),
    P4: buildP4(seed, intensities.P4_nav_order),
    P5: buildP5(seed, intensities.P5_theme),
  }
}
