/**
 * variants.ts — emit the variant matrix as `variants.json`.
 *
 * Runs the seeded variant factory over a curated set of seeds that spans all 5
 * axes at different intensities (plus the canonical baseline seed=0). Every
 * variant is a PURE function of its seed: `sameSeed -> sameVariant`. The whole
 * matrix is deterministic, so re-running the generator on the same seed set
 * yields byte-identical JSON (the Step 02 determinism proof).
 */

import { deriveConfig, deriveIntensities, type PerturbationConfig, type IntensityByAxis } from "./axes.js"
import { deriveTaskSpec, type TaskSpec } from "./task-spec.js"

export interface VariantRecord {
  variant_id: string
  seed: number
  intensity_by_axis: IntensityByAxis
  axis_params: PerturbationConfig
  task_spec: TaskSpec
}

export interface VariantMatrix {
  schema_version: string
  task_app: string
  generator: string
  baseline_seed: number
  variant_count: number
  variants: VariantRecord[]
}

/**
 * Curated seed set. seed=0 MUST be first (it is the canonical un-perturbed
 * baseline). The remaining seeds were chosen so the matrix covers every axis at
 * multiple intensities (P1 0..4, P2 0..3, P3 0..4, P4 0..2, P5 0..3).
 */
export const VARIANT_SEEDS: readonly number[] = [
  0, 17, 7, 13, 31, 2, 8, 21, 9, 3, 29, 12, 6, 24,
]

/** Build the variant id: `inv__s<seed>__P1:<k>__P2:<k>__P3:<k>__P4:<k>__P5:<k>`. */
export function variantId(seed: number, axis: IntensityByAxis): string {
  return (
    `inv__s${seed}__P1:${axis.P1_relabel}__P2:${axis.P2_structure}` +
    `__P3:${axis.P3_field_order}__P4:${axis.P4_nav_order}__P5:${axis.P5_theme}`
  )
}

/** Build one variant record for a seed (pure: same seed -> same record). */
export function buildVariant(seed: number): VariantRecord {
  const axis = deriveIntensities(seed)
  const config = deriveConfig(seed)
  const task = deriveTaskSpec(seed)
  return {
    variant_id: variantId(seed, axis),
    seed,
    intensity_by_axis: axis,
    axis_params: config,
    task_spec: task,
  }
}

/** Build the full variant matrix. Deterministic. */
export function buildVariantMatrix(): VariantMatrix {
  const variants = VARIANT_SEEDS.map(buildVariant)
  return {
    schema_version: "1.0",
    task_app: "create-invoice",
    generator: "coldstart-generate-variants",
    baseline_seed: 0,
    variant_count: variants.length,
    variants,
  }
}

/** Build a single-variant matrix for one seed (used by the --seed CLI mode). */
export function buildSingleVariantMatrix(seed: number): VariantMatrix {
  return {
    schema_version: "1.0",
    task_app: "create-invoice",
    generator: "coldstart-generate-variants",
    baseline_seed: 0,
    variant_count: 1,
    variants: [buildVariant(seed)],
  }
}
