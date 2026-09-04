/**
 * sqlite.ts — Node's built-in `node:sqlite` accessor.
 *
 * Why this exists: `node:sqlite` is an experimental Node builtin (Node >= 22.5)
 * that is NOT listed in Node's `builtinModules`. Vite/Vitest therefore does not
 * recognize it and, when a module statically does `import ... from "node:sqlite"`,
 * it strips the `node:` prefix, tries to resolve a bare "sqlite" package (which
 * does not exist) and fails with "Failed to load url sqlite".
 *
 * We load it at runtime via `createRequire("node:sqlite")` instead of a static
 * ESM `import`. This keeps the same real Node `DatabaseSync` (single source of
 * truth) while avoiding Vite's static import analysis, so the verifier runs
 * offline under vitest. `node:module` and `node:url` ARE recognized builtins and
 * are externalized by Vite normally.
 *
 * Both the variant app (`src/variant-app/db.ts`) and the verifier
 * (`src/verify/verifier.ts`) import `DatabaseSync` from here.
 */

import { createRequire } from "node:module"

// `createRequire` needs the current module's URL as the resolution base.
const require = createRequire(import.meta.url)

// `typeof import("node:sqlite")` is a TYPE (erased at compile time) — no runtime
// import. The require() call is a runtime function call Vite never analyzes.
const mod = require("node:sqlite") as typeof import("node:sqlite")

// Value (the class) + instance type (for `db: DatabaseSync` annotations).
export const DatabaseSync = mod.DatabaseSync
export type DatabaseSync = InstanceType<typeof mod.DatabaseSync>
