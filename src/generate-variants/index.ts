/**
 * index.ts — CLI entrypoint for the variant factory.
 *
 * Usage:
 *   tsx src/generate-variants/index.ts [outPath]
 *
 * Writes the variant matrix as JSON. The default output path is `variants.json`
 * at the repo root; override with an optional CLI arg or the VARIANTS_OUT env
 * var (used by the Step 02 determinism proof to emit two files).
 */

import { writeFileSync } from "node:fs"
import { buildVariantMatrix, buildSingleVariantMatrix } from "./variants.js"

function main(): void {
  const args = process.argv.slice(2)
  let outPath = process.env.VARIANTS_OUT ?? "variants.json"
  let seedFilter: number | null = null
  for (let i = 0; i < args.length; i++) {
    const a = args[i]!
    if (a === "--seed") {
      seedFilter = Number(args[++i])
      continue
    }
    if (a.startsWith("--")) continue
    outPath = a
  }

  const matrix = seedFilter === null ? buildVariantMatrix() : buildSingleVariantMatrix(seedFilter)
  const json = `${JSON.stringify(matrix, null, 2)}\n`
  writeFileSync(outPath, json)
  console.log(`[generate-variants] wrote ${matrix.variant_count} variant(s) -> ${outPath}`)
}

main()
