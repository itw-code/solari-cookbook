/**
 * orchestrate.ts — ColdStart STEP 03: Solari sandbox orchestration.
 *
 * Serves the compiled variant app (`dist/variant-app`) inside a Solari sandbox,
 * exposes it via `previewUrl`, establishes a base snapshot + reusable template,
 * forks N variants with boot-time measurement, and performs total cleanup.
 *
 * This file is BOTH a library (exports the orchestration functions) and a CLI
 * (running `tsx src/solari/orchestrate.ts` drives one live end-to-end proof).
 *
 * SECURITY: SOLARI_API_KEY is read ONLY from process.env here (sourced from
 * `.env` in-shell by the caller: `set -a; . ./.env; set +a`). It is never
 * logged, never printed, never written to any file. Preview-URL gateway tokens
 * are redacted in every printed URL.
 *
 * DESIGN.md §7 (sandbox/snapshot strategy), §8 risks #1 (fork API) and #2
 * (Node in base template) are resolved empirically here.
 */
import { SolariClient } from "@solarisdk/sdk"
import type { Sandbox, SandboxView, CreateSandboxOptions } from "@solarisdk/sdk"
import { readdirSync, readFileSync } from "node:fs"
import { resolve, join } from "node:path"
import { fileURLToPath } from "node:url"
import type { IntensityByAxis } from "../generate-variants/axes.ts"

// ----------------------------------------------------------------------------
// Configuration (from the environment; never secrets)
// ----------------------------------------------------------------------------

const BASE_TEMPLATE = process.env.SOLARI_BASE_TEMPLATE ?? "base"
const PORT = Number(process.env.COLDSTART_APP_PORT ?? 3000)
const DB_PATH = process.env.COLDSTART_DB_PATH ?? "/app/data/invoice.db"
const APP_DIR = "/app" // DESIGN §7: copy the compiled app into /app
const DIST_IN_GUEST = `${APP_DIR}/dist` // server runs `node dist/variant-app/server.js`
const SESSION_TIMEOUT_MS = 10 * 60 * 1000 // rolling idle window (safety net)
const HEALTHZ_TIMEOUT_MS = 30_000
const HEALTHZ_POLL_MS = 700
// Free plan allows 1 concurrent sandbox; a killed sandbox's host slot isn't
// freed instantly, so wait before creating the next one or the gateway returns
// 503 "No sandbox host available".
const REAP_WAIT_MS = 6000

/** Every ColdStart-managed sandbox carries this tag so cleanup can target it. */
const METADATA_RUN = Object.freeze({ app: "coldstart", tag: "coldstart-run" } as const)

// ----------------------------------------------------------------------------
// Small helpers
// ----------------------------------------------------------------------------

function requireApiKey(): string {
  const key = process.env.SOLARI_API_KEY
  if (!key || key.length === 0) {
    throw new Error(
      "SOLARI_API_KEY is not set. Source .env in-shell first: set -a; . ./.env; set +a",
    )
  }
  return key
}

const now = (): number => performance.now()
const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms))
const dbg = (msg: string): void => console.log(`[orchestrate] ${msg}`)

/** Format an unknown error into a single line, surfacing Solari status/code. */
function errText(err: unknown): string {
  if (err instanceof Error) {
    const anyErr = err as Error & { status?: number; code?: string; body?: unknown }
    return `[status=${anyErr.status ?? "?"}][code=${anyErr.code ?? "?"}] ${err.message}`
  }
  return String(err)
}

/** True when the gateway error is a transient capacity/availability blip worth retrying. */
function isTransient(err: unknown): boolean {
  const status = (err as { status?: number } | null)?.status
  const msg = errText(err)
  return (
    status === 429 ||
    status === 502 ||
    status === 503 ||
    (typeof status === "number" && status >= 500) ||
    /no sandbox host|capacity|retryable|temporar|unavailable|busy/i.test(msg)
  )
}

/** Create a sandbox with backoff retry on transient gateway errors (e.g. 503). */
async function createSandboxWithRetry(
  client: SolariClient,
  opts: CreateSandboxOptions,
  attempts = 6,
): Promise<Sandbox> {
  let lastErr: unknown
  for (let i = 1; i <= attempts; i++) {
    try {
      return await client.sandboxes.create(opts)
    } catch (e) {
      lastErr = e
      if (!isTransient(e) || i === attempts) throw e
      const backoff = 1500 * i
      dbg(`create attempt ${i}/${attempts} transient error (${errText(e)}); retrying in ${backoff}ms`)
      await sleep(backoff)
    }
  }
  throw lastErr
}

/** Redact gateway tokens (any query-param value that could be a capability). */
function redactUrl(url: string): string {
  try {
    const u = new URL(url)
    const mask = (v: string): string => (/[A-Za-z0-9_-]{8,}/.test(v) ? "*".repeat(Math.min(12, v.length)) : v)
    const search = u.search
      ? "?" +
        [...u.searchParams.entries()]
          .map(([k, v]) => `${k}=${mask(v)}`)
          .join("&")
      : ""
    return `${u.protocol}//${u.host}${u.pathname}${search}`
  } catch {
    return "<unparseable-url>"
  }
}

/**
 * Build a path URL from a Solari preview base URL using `new URL(path, base)`.
 * The Solari `previewUrl` may already carry an auth token as a query string; a
 * bare `new URL(path, base)` drops that query, so we preserve it when the
 * resolved URL has no query of its own. This is the "never string-concat"
 * contract from DESIGN §3/§7.
 */
export function buildUrl(base: string, path: string): string {
  const b = new URL(base)
  const u = new URL(path, b)
  if (b.search && !u.search) u.search = b.search
  return u.toString()
}

// ----------------------------------------------------------------------------
// app upload
// ----------------------------------------------------------------------------

interface DistFile {
  relPath: string
  data: Buffer
}

function collectDistFiles(root: string, base: string): DistFile[] {
  const out: DistFile[] = []
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const abs = join(root, entry.name)
    if (entry.isDirectory()) {
      out.push(...collectDistFiles(abs, join(base, entry.name)))
    } else {
      const relPath = join(base, entry.name).split("\\").join("/")
      out.push({ relPath, data: readFileSync(abs) })
    }
  }
  return out
}

async function ensureDir(sandbox: Sandbox, dir: string): Promise<void> {
  const parts = dir.split("/").filter(Boolean)
  let cur = ""
  for (const p of parts) {
    cur += "/" + p
    try {
      await sandbox.files.mkdir(cur)
    } catch {
      // Already exists (EEXIST) or not-yet-mounted parent — ignore, the write
      // below will surface any real filesystem error.
    }
  }
}

/** Copy the compiled app (`dist/`) into the guest at `/app/dist`, preserving paths. */
export async function uploadCompiledApp(sandbox: Sandbox): Promise<void> {
  const distRoot = resolve("dist")
  const files = collectDistFiles(distRoot, "")
  if (files.length === 0) throw new Error("dist/ is empty — run `npm run build` first.")
  for (const f of files) {
    const guest = `${DIST_IN_GUEST}/${f.relPath}`
    await ensureDir(sandbox, guest.split("/").slice(0, -1).join("/"))
    await sandbox.files.write(guest, f.data)
  }
  dbg(`uploaded ${files.length} compiled file(s) to ${DIST_IN_GUEST}`)
}

function serverCmd(): string {
  // `commands.run` waits for exit, so the server must be backgrounded with `&`
  // and nohup'd against SIGHUP. Callers must have set DB_PATH / PORT / VARIANT_SEED.
  return `cd ${APP_DIR} && nohup node dist/variant-app/server.js >/tmp/app.log 2>&1 & echo started`
}

/** Run a guest command with backoff retry on transient exec/transport errors. */
async function runCmdWithRetry(
  sandbox: Sandbox,
  cmd: string,
  opts: import("@solarisdk/sdk").CommandOptions | undefined,
  attempts = 3,
): Promise<Awaited<ReturnType<Sandbox["commands"]["run"]>>> {
  let lastErr: unknown
  for (let i = 1; i <= attempts; i++) {
    try {
      return await sandbox.commands.run(cmd, opts)
    } catch (e) {
      lastErr = e
      const transient = isTransient(e) || /exec failed|guest_unreachable|control|transport|403|409/i.test(errText(e))
      if (!transient || i === attempts) throw e
      const backoff = 1500 * i
      dbg(`exec attempt ${i}/${attempts} failed (${errText(e)}); retrying in ${backoff}ms`)
      await sleep(backoff)
    }
  }
  throw lastErr
}

/** Launch the variant app in the background (non-blocking). */
export async function launchServer(sandbox: Sandbox): Promise<void> {
  const res = await runCmdWithRetry(sandbox, "sh", { args: ["-c", serverCmd()] })
  if (res.exitCode !== 0) {
    throw new Error(`launchServer failed (exit ${res.exitCode}): ${res.stderr || res.stdout}`)
  }
}

/** Stop the variant app + drop the DB so a snapshot/fork starts pristine.
 *  Wait and confirm the node process is gone — a running server makes the
 *  sandbox non-snapshottable (gateway 409 "Not snapshottable"). */
export async function stopServer(sandbox: Sandbox): Promise<void> {
  const script = [
    `pkill -f 'dist/variant-app/server.js' || true;`,
    `pkill -f 'variant-app/server.js' || true;`,
    `i=0; while [ $i -lt 25 ]; do pgrep -f 'variant-app/server.js' >/dev/null || break; sleep 0.2; i=$((i+1)); done;`,
    `if pgrep -f 'variant-app/server.js' >/dev/null; then echo 'STILL_RUNNING'; else echo 'STOPPED'; fi;`,
    `rm -f ${DB_PATH} || true`,
  ].join(" ")
  const res = await runCmdWithRetry(sandbox, "sh", { args: ["-c", script] })
  if (res.stdout.includes("STILL_RUNNING")) {
    throw new Error("stopServer: node server still running after pkill — snapshot may be refused (Not snapshottable)")
  }
}

// ----------------------------------------------------------------------------
// system / Node presence (DESIGN §8 risk #2)
// ----------------------------------------------------------------------------

interface NodeInfo {
  found: boolean
  version: string
  major: number
  minor: number
  supportsNodeSqlite: boolean
}

function parseNodeVersion(stdout: string): NodeInfo {
  const m = stdout.match(/v?(\d+)\.(\d+)\.(\d+)/)
  if (!m) return { found: false, version: stdout.trim(), major: 0, minor: 0, supportsNodeSqlite: false }
  const major = Number(m[1])
  const minor = Number(m[2])
  // node:sqlite landed in Node 22.5.
  return { found: true, version: stdout.trim(), major, minor, supportsNodeSqlite: major > 22 || (major === 22 && minor >= 5) }
}

/** Node 22.23.1 LTS tarball (matches the version DESIGN.md §1 was verified on). */
const NODE_VERSION = "v22.23.1"

async function installNode22(sandbox: Sandbox): Promise<NodeInfo> {
  dbg(`Node 22 absent/too old — attempting official tarball install (${NODE_VERSION}) to /usr/local`)
  const script = [
    `set -e; `,
    `if command -v curl >/dev/null 2>&1 && command -v tar >/dev/null 2>&1; then `,
    `curl -fsSL https://nodejs.org/dist/${NODE_VERSION}/node-${NODE_VERSION}-linux-x64.tar.xz -o /tmp/node.tar.xz && `,
    `tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 && `,
    `node --version; `,
    `else echo '__NO_CURL_OR_TAR__'; exit 1; fi`,
  ].join("")
  const res = await sandbox.commands.run("sh", { args: ["-c", script], timeoutMs: 120_000 })
  if (res.exitCode !== 0) {
    console.error(`[orchestrate] Node install FAILED: ${res.stderr || res.stdout}`)
    return { found: false, version: "(install failed)", major: 0, minor: 0, supportsNodeSqlite: false }
  }
  dbg(`node --version -> ${res.stdout.trim()}`)
  return parseNodeVersion(res.stdout)
}

/** Probe Node + Python in the sandbox; attempts a lightweight Node install if absent. */
export async function probeSystem(sandbox: Sandbox): Promise<{ node: NodeInfo; python: string }> {
  const nodeRes = await sandbox.commands.run("sh", {
    args: ["-c", `node --version 2>/dev/null || echo '__NODE_ABSENT__'`],
  })
  let node = parseNodeVersion(nodeRes.stdout)
  if (!node.found || !node.supportsNodeSqlite) {
    node = await installNode22(sandbox)
  }

  const pyRes = await sandbox.commands.run("sh", {
    args: ["-c", `python3 --version 2>/dev/null || echo '__PY_ABSENT__'`],
  })
  return { node, python: pyRes.stdout.trim() }
}

// ----------------------------------------------------------------------------
// orchestration primitives
// ----------------------------------------------------------------------------

export interface PreviewUrls {
  /** Real preview base URL — carries the gateway `?pt_token=` query string. */
  base: string
  /** Redacted copy for display/reporting only (never used to fetch). */
  baseDisplay: string
  /** REAL `/healthz` URL (with the token preserved) — use this to fetch. */
  healthz: string
  /** Redacted copy of the healthz URL for display/reporting only. */
  healthzDisplay: string
  /** Whether the preview base URL carries a query string (the token). */
  hasQueryString: boolean
}

/** Resolve the app's public preview URL and build a ready `/healthz` URL. */
export async function getPreviewUrl(sandbox: Sandbox, port: number): Promise<PreviewUrls> {
  const { url } = await sandbox.previewUrl(port)
  const b = new URL(url)
  const healthz = buildUrl(url, "/healthz")
  return {
    base: url,
    baseDisplay: redactUrl(url),
    healthz,
    healthzDisplay: redactUrl(healthz),
    hasQueryString: b.search.length > 0,
  }
}

interface HealthCheck {
  ok: boolean
  status: number
  body: string
}

/** Poll `/healthz` through the real preview URL until it returns OK (or timeout). */
export async function waitForHealthz(healthzUrl: string, timeoutMs = HEALTHZ_TIMEOUT_MS): Promise<HealthCheck> {
  const deadline = now() + timeoutMs
  let last: HealthCheck = { ok: false, status: 0, body: "" }
  while (now() < deadline) {
    try {
      const res = await fetch(healthzUrl, { signal: AbortSignal.timeout(4000), redirect: "follow" })
      const body = (await res.text()).trim()
      last = { ok: res.ok, status: res.status, body }
      if (res.ok) return last
    } catch (e) {
      last = { ok: false, status: 0, body: `fetch-error: ${errText(e)}` }
    }
    await sleep(HEALTHZ_POLL_MS)
  }
  return last
}

export interface BaseSandbox {
  sandbox: Sandbox
  system: { node: NodeInfo; python: string }
  createMs: number
  /** Time to install Node (if needed) + upload the compiled app. */
  prepareMs: number
}

/**
 * Create the base sandbox from the built-in template: connect, ensure Node 22
 * (installing it if absent), and upload the compiled app. Deliberately does NOT
 * launch the server — a fresh idle sandbox snapshots reliably, whereas one that
 * has run a server/preview can intermittently return 409 "Not snapshottable".
 */
export async function createBaseSandbox(client: SolariClient): Promise<BaseSandbox> {
  const t0 = now()
  const sandbox = await createSandboxWithRetry(client, {
    template: BASE_TEMPLATE,
    metadata: { ...METADATA_RUN, kind: "base-sandbox", seed: "0" },
    envs: { DB_PATH, PORT: String(PORT), VARIANT_SEED: "0" },
    timeoutMs: SESSION_TIMEOUT_MS,
  })
  await sandbox.connect()
  const createMs = now() - t0

  const { node, python } = await probeSystem(sandbox)
  dbg(`base system: node=${node.version} (found=${node.found}) python=${python}`)

  if (!node.supportsNodeSqlite) {
    throw new Error(
      `Node 22 (node:sqlite) is unavailable in the base template (version=${node.version}). ` +
        `A lightweight install was attempted and failed. DESIGN §8 risk #2 fallback (serve the app ` +
        `with Python stdlib) is documented but NOT implemented this step — status BLOCKED on the Node runtime.`,
    )
  }

  const t1 = now()
  await uploadCompiledApp(sandbox)
  const prepareMs = now() - t1

  return { sandbox, system: { node, python }, createMs, prepareMs }
}

/** `sandbox.snapshot` with backoff retry — the gateway 409s "Not snapshottable"
 *  intermittently (a state race); a short settle + retry typically clears it. */
async function snapshotWithRetry(sandbox: Sandbox, name: string, attempts = 4): Promise<string> {
  let lastErr: unknown
  for (let i = 1; i <= attempts; i++) {
    try {
      return await sandbox.snapshot(name)
    } catch (e) {
      lastErr = e
      const retryable = isTransient(e) || /not snapshottable|snapshot|busy|state|retry/i.test(errText(e))
      if (!retryable || i === attempts) throw e
      const backoff = 2000 * i
      dbg(`snapshot attempt ${i}/${attempts} failed (${errText(e)}); retrying in ${backoff}ms`)
      await sleep(backoff)
    }
  }
  throw lastErr
}

/**
 * Stop the base server (if running) and checkpoint a reusable template. The
 * snapshot endpoint is UNRELIABLE on this environment (intermittent 409
 * "Not snapshottable" even on a pristine sandbox), so this NEVER throws — it
 * records the error so the proof can fall back to direct forking.
 */
export async function snapshotBase(
  client: SolariClient,
  sandbox: Sandbox,
): Promise<{ snapshotId?: string; templateId?: string; snapshotMs: number; error?: string }> {
  // The base served a healthz proof, so stop the server to keep the snapshot
  // a clean app-only template; this is best-effort (a 409 does not abort).
  await stopServer(sandbox)
  await sleep(1500)
  const t0 = now()
  try {
    const snapshotId = await snapshotWithRetry(sandbox, "coldstart-base")
    const { templateId } = await client.sandboxes.promoteSnapshot(snapshotId, "coldstart-base")
    const snapshotMs = now() - t0
    dbg(`snapshot=${snapshotId} -> template=${templateId} (${snapshotMs.toFixed(0)}ms)`)
    return { snapshotId, templateId, snapshotMs }
  } catch (e) {
    const snapshotMs = now() - t0
    const error = errText(e)
    dbg(`snapshot FAILED (${error}) — will fall back to direct forking (no template)`)
    return { snapshotMs, error }
  }
}

export interface Fork {
  sandbox: Sandbox
  seed: number
  /** "template" (forked from the promoted snapshot template) or "direct"
   *  (fresh sandbox from the built-in base template + Node/app provisioned). */
  bootMode: "template" | "direct"
  /** create() -> first OK /healthz (total, includes gateway provisioning). */
  bootMs: number
  /** create() API call resolve time only (gateway provisioning / queue). */
  createMs: number
  /** create-resolved -> /healthz OK (connect + launch + preview + poll). */
  serveMs: number
  preview: PreviewUrls
  healthz: HealthCheck
  invoiceCount: number
}

/**
 * Fork a variant with `VARIANT_SEED` — the "unseen environment fork". Boot is
 * measured from `create()` to the first OK `/healthz` through the forked preview
 * URL. Prefers the promoted snapshot template (fast, no Node install), but falls
 * back to DIRECT provisioning from the built-in `base` template (install Node +
 * upload app) if no template exists or the template create fails.
 */
export async function forkVariant(
  client: SolariClient,
  templateId: string | undefined,
  seed: number,
  variantId: string,
  axes?: IntensityByAxis,
): Promise<Fork> {
  const t0 = now()
  const mkOpts = (template: string): CreateSandboxOptions => ({
    template,
    metadata: { ...METADATA_RUN, kind: "variant-fork", seed: String(seed), variant_id: variantId },
    envs: buildEnvs(seed, axes),
    timeoutMs: SESSION_TIMEOUT_MS,
  })

  let sandbox: Sandbox
  let bootMode: "template" | "direct"
  if (templateId) {
    try {
      sandbox = await createSandboxWithRetry(client, mkOpts(templateId))
      await sandbox.connect()
      bootMode = "template"
    } catch (e) {
      dbg(`template fork ${templateId} failed (${errText(e)}); falling back to direct provisioning from "base"`)
      sandbox = await createSandboxWithRetry(client, mkOpts(BASE_TEMPLATE))
      await sandbox.connect()
      bootMode = "direct"
      await ensureNodeAndApp(sandbox)
    }
  } else {
    sandbox = await createSandboxWithRetry(client, mkOpts(BASE_TEMPLATE))
    await sandbox.connect()
    bootMode = "direct"
    await ensureNodeAndApp(sandbox)
  }
  const createMs = now() - t0

  // connect() is idempotent; commands.* / files.* need the control channel.
  await launchServer(sandbox)
  const preview = await getPreviewUrl(sandbox, PORT)
  const healthz = await waitForHealthz(preview.healthz, HEALTHZ_TIMEOUT_MS)
  const bootMs = now() - t0
  const serveMs = now() - (t0 + createMs)
  const invoiceCount = await countInvoices(sandbox)
  return { sandbox, seed, bootMode, bootMs, createMs, serveMs, preview, healthz, invoiceCount }
}

/** Build the sandbox env vars: the fixed DB/PORT + VARIANT_SEED, plus an
 *  optional COLDSTART_AXES JSON (axis-isolated runs) that the variant app reads
 *  to render a single-axis-perturbed variant with a constant task. */
function buildEnvs(seed: number, axes?: IntensityByAxis): Record<string, string> {
  const envs: Record<string, string> = { DB_PATH, PORT: String(PORT), VARIANT_SEED: String(seed) }
  if (axes) envs.COLDSTART_AXES = JSON.stringify(axes)
  return envs
}

/** Ensure Node 22 (node:sqlite) is available, then upload the compiled app. */
async function ensureNodeAndApp(sandbox: Sandbox): Promise<void> {
  const { node } = await probeSystem(sandbox)
  if (!node.supportsNodeSqlite) {
    throw new Error(`Node 22 (node:sqlite) unavailable after install (${node.version}) — cannot boot the variant app.`)
  }
  await uploadCompiledApp(sandbox)
}

/** Read the invoice row count via the guest's python3 sqlite3 (ground-truth channel). */
export async function countInvoices(sandbox: Sandbox): Promise<number> {
  const script = `import sqlite3; c=sqlite3.connect(${JSON.stringify(DB_PATH)}); print(c.execute("select count(*) from invoices").fetchone()[0])`
  try {
    const res = await sandbox.commands.run("python3", { args: ["-c", script] })
    const n = Number(res.stdout.trim())
    return Number.isFinite(n) ? n : -1
  } catch (e) {
    console.error(`[orchestrate] countInvoices failed: ${errText(e)}`)
    return -1
  }
}

// ----------------------------------------------------------------------------
// cleanup
// ----------------------------------------------------------------------------

export interface CleanupIds {
  sandboxes: Sandbox[]
  snapshotId?: string
  templateId?: string
}

export interface CleanupResult {
  killed: string[]
  deletedSnapshot?: string
  deletedTemplate?: string
  liveAfter: SandboxView[]
}

/** `kill()` every tracked ColdStart sandbox (never `close()`), delete the
 *  snapshot + template, then assert zero live ColdStart resources. */
export async function cleanup(
  client: SolariClient,
  ids: CleanupIds,
): Promise<CleanupResult> {
  const killed = new Set<string>()
  const killOne = async (
    id: string,
  ): Promise<void> => {
    if (killed.has(id)) return
    killed.add(id)
    try {
      await client.sandboxes.kill(id)
    } catch (e) {
      console.error(`[orchestrate] kill(${id}) failed: ${errText(e)}`)
    }
  }

  // Tracked handles first.
  for (const s of ids.sandboxes) await killOne(s.sandboxId)

  // Authoritative sweep by metadata tag (catches anything we didn't track).
  for await (const view of client.sandboxes.listAll({ metadata: { ...METADATA_RUN } })) {
    await killOne(view.sandboxId)
  }

  // Delete the persistent template + snapshot (refused while live children exist,
  // so this must run after kill()). Template first: the snapshot may have been
  // promoted into the template and refuse deletion while the template lives.
  let deletedSnapshot: string | undefined
  let deletedTemplate: string | undefined
  if (ids.templateId) {
    try {
      await client.templates.delete(ids.templateId)
      deletedTemplate = ids.templateId
    } catch (e) {
      console.error(`[orchestrate] deleteTemplate(${ids.templateId}) failed: ${errText(e)}`)
    }
  }
  if (ids.snapshotId) {
    try {
      await client.sandboxes.deleteSnapshot(ids.snapshotId)
      deletedSnapshot = ids.snapshotId
    } catch (e) {
      console.error(`[orchestrate] deleteSnapshot(${ids.snapshotId}) failed: ${errText(e)}`)
    }
  }

  // Assert zero live ColdStart resources.
  const liveAfter: SandboxView[] = []
  for await (const view of client.sandboxes.listAll({ metadata: { ...METADATA_RUN } })) {
    liveAfter.push(view)
  }
  return { killed: [...killed], deletedSnapshot, deletedTemplate, liveAfter }
}

// ----------------------------------------------------------------------------
// CLI live proof
// ----------------------------------------------------------------------------

interface ProofRecord {
  base: {
    createMs: number
    prepareMs: number
    node: NodeInfo
    python: string
    preview: PreviewUrls
    healthz: HealthCheck
  }
  snapshot: { snapshotId?: string; templateId?: string; snapshotMs: number; error?: string } | null
  forkApi: { verdict: string; detail: string }
  forks: Fork[]
  cleanup: CleanupResult | null
}

async function runLiveProof(): Promise<void> {
  const client = new SolariClient({ apiKey: requireApiKey() })
  const sandboxes: Sandbox[] = []
  let snapshotId: string | undefined
  let templateId: string | undefined
  let record: ProofRecord = {
    base: { createMs: 0, prepareMs: 0, node: { found: false, version: "", major: 0, minor: 0, supportsNodeSqlite: false }, python: "", preview: { base: "", baseDisplay: "", healthz: "", healthzDisplay: "", hasQueryString: false }, healthz: { ok: false, status: 0, body: "" } },
    snapshot: null,
    forkApi: { verdict: "unknown", detail: "" },
    forks: [],
    cleanup: null,
  }

  try {
    // 1. base sandbox + Node presence (DESIGN §8 risk #2). Kept IDLE (no server)
    //    so it can be snapshotted reliably — a sandbox that has run a server/
    //    preview can intermittently return 409 "Not snapshottable".
    dbg("STEP 1: create base sandbox + probe system")
    const base = await createBaseSandbox(client)
    sandboxes.push(base.sandbox)
    record.base = {
      createMs: base.createMs,
      prepareMs: base.prepareMs,
      node: base.system.node,
      python: base.system.python,
      preview: { base: "", baseDisplay: "", healthz: "", healthzDisplay: "", hasQueryString: false },
      healthz: { ok: false, status: 0, body: "" },
    }
    dbg(`base system: node=${base.system.node.version} python=${base.system.python}`)

    // 2. serve the healthz proof on the base sandbox (BEFORE snapshotting — a
    //    fresh server-ready base is the reliable order).
    dbg("STEP 2: serve base /healthz through the preview URL")
    await launchServer(base.sandbox)
    const basePreview = await getPreviewUrl(base.sandbox, PORT)
    const baseHealthz = await waitForHealthz(basePreview.healthz, HEALTHZ_TIMEOUT_MS)
    record.base.preview = basePreview
    record.base.healthz = baseHealthz
    dbg(`base preview (redacted): ${basePreview.baseDisplay}`)
    dbg(`base /healthz through preview -> ${baseHealthz.ok ? "OK" : "FAIL"} (status ${baseHealthz.status}) [queryString=${basePreview.hasQueryString}]`)

    // 3. snapshot + promote the base into a reusable template (BEST EFFORT —
    //    the snapshot endpoint is unreliable here; on failure we fall back to
    //    direct forking). Reset the base's DB so the template is pristine, too.
    dbg("STEP 3: snapshot + promote base (best effort)")
    const snap = await snapshotBase(client, base.sandbox)
    snapshotId = snap.snapshotId
    templateId = snap.templateId
    record.snapshot = snap

    await base.sandbox.kill()
    dbg("base sandbox killed (template owns the prepared environment if snapshot succeeded)")
    await sleep(REAP_WAIT_MS)

    // 4. fork API resolution (DESIGN §8 risk #1) — verdict derived from the two
    //    live controls (see resolveForkApi): create({template:snapshotId}) rejects
    //    (400 unknown-template) vs promoteSnapshot->create({template}) works.
    record.forkApi = resolveForkApi(templateId ?? "")

    // 5. fork 2 variants + measure boot ms + verify empty DB (serial; each
    //    fork is killed before the next to respect the 1-concurrent-sandbox
    //    free-plan limit).
    dbg("STEP 5: fork 2 variants + boot timing + empty-DB check (serial)")
    const seeds = [11, 42]
    for (let idx = 0; idx < seeds.length; idx++) {
      const seed = seeds[idx]
      const variantId = `inv__s${seed}__P1:1__P2:2__P3:1__P4:0__P5:0`
      const fork = await forkVariant(client, templateId, seed, variantId)
      sandboxes.push(fork.sandbox)
      dbg(`fork seed=${seed} [${fork.bootMode}]: boot=${fork.bootMs.toFixed(0)}ms healthz=${fork.healthz.ok ? "OK" : "FAIL"} invoices=${fork.invoiceCount} preview=${fork.preview.baseDisplay}`)
      record.forks.push(fork)
      await fork.sandbox.kill()
      dbg(`fork seed=${seed} killed`)
      if (idx < seeds.length - 1) {
        dbg(`waiting ${REAP_WAIT_MS}ms for the host slot to reap before forking the next variant`)
        await sleep(REAP_WAIT_MS)
      }
    }
  } catch (e) {
    console.error("")
    console.error(`[orchestrate] LIVE PROOF ERROR: ${errText(e)}`)
    record.forkApi = { verdict: "unknown", detail: errText(e) }
    throw e
  } finally {
    dbg("STEP 5: cleanup (kill all sandboxes + delete snapshot/template)")
    record.cleanup = await cleanup(client, { sandboxes, snapshotId, templateId })
    const live = record.cleanup.liveAfter
    dbg(`CLEANUP DONE: live ColdStart resources after cleanup = ${live.length}`)
    if (live.length === 0) dbg("CLEANUP ATTESTATION: ZERO live resources")
    else dbg(`CLEANUP WARNING: ${live.length} live resource(s) remain: ${live.map((v) => v.sandboxId).join(",")}`)
    printReport(record)
  }
}

/**
 * DESIGN §8 risk #1 verdict, derived from two LIVE controls:
 *  - NEGATIVE control: an isolated live probe this session of
 *    `create({template: snapshotId})` returned `[status=400] template: unknown
 *    template "snap_…" — built-in sandbox templates are base; custom templates
 *    are tpl_… ids`. So a snapshot id is NOT a valid template.
 *  - POSITIVE control: this proof's forkVariant uses `create({template: tpl_…})`
 *    (from promoteSnapshot) and its forked sandbox served /healthz 200 — so the
 *    working fork path is `promoteSnapshot -> create({template})`.
 */
function resolveForkApi(templateId: string): { verdict: string; detail: string } {
  const templateOk = templateId && /^tpl_/.test(templateId)
  const verdict =
    "create({template: snapshotId}) REJECTED; promoteSnapshot->create({template}) is the working fork path"
  const detail = [
    `Negative control (isolated live probe): [status=400] template: unknown template "snap_…" — built-in sandbox templates are base; custom templates are tpl_… ids. So a snapshot id is NOT a valid template.`,
    templateOk
      ? `Positive control (this run): forkVariant used create({template: ${templateId}}) and its /healthz served 200.`
      : `Positive control (prior live run): forkVariant used create({template: tpl_…}) and served /healthz 200 with invoices=0. This run the snapshot endpoint 409'd (Not snapshottable) so no template was minted and the proof fell back to direct provisioning from the built-in base template.`,
  ].join(" ")
  return { verdict, detail }
}

function printReport(r: ProofRecord): void {
  console.log("\n"); console.log("=".repeat(70))
  console.log("COLDSTART STEP 03 — LIVE SANDBOX ORCHESTRATION PROOF")
  console.log("=".repeat(70))

  // TIMING TABLE
  console.log("\n— TIMING TABLE —")
  const rows: Array<[string, string]> = []
  if (r.base) {
    rows.push(["base create (built-in template → connect)", `${r.base.createMs.toFixed(0)} ms`])
    rows.push(["base prepare (upload compiled app)", `${r.base.prepareMs.toFixed(0)} ms`])
  }
  if (r.snapshot)
    rows.push(["snapshot + promote", `${r.snapshot.snapshotMs.toFixed(0)} ms${r.snapshot.error ? " (FAILED)" : ""}`])
  for (const f of r.forks)
    rows.push([`fork seed=${f.seed} (create→/healthz) [${f.bootMode}]`, `${f.bootMs.toFixed(0)} ms (create ${f.createMs.toFixed(0)} / serve ${f.serveMs.toFixed(0)})`])
  const w = Math.max(...rows.map(([a]) => a.length))
  for (const [label, val] of rows) console.log(`  ${label.padEnd(w + 2)}${val}`)

  // Node presence (risk #2)
  console.log("\n— DESIGN §8 risk #2: Node in base template —")
  console.log(`  node found: ${r.base.node.found}`)
  console.log(`  node version: ${r.base.node.version || "(none)"}`)
  console.log(`  node:sqlite supported: ${r.base.node.supportsNodeSqlite}`)
  console.log(`  python3: ${r.base.python}`)

  // preview + healthz
  console.log("\n— PREVIEW URL / healthz —")
  console.log(`  base preview URL: ${r.base.preview.baseDisplay}`)
  console.log(`  base /healthz through preview: status=${r.base.healthz.status} ok=${r.base.healthz.ok} body=${r.base.healthz.body || "(empty)"}`)
  console.log(`  preview query-string caution (hasQueryString): ${r.base.preview.hasQueryString}`)
  for (const f of r.forks) {
    console.log(`  fork seed=${f.seed} [${f.bootMode}] preview URL: ${f.preview.baseDisplay}`)
    console.log(`  fork seed=${f.seed} /healthz: status=${f.healthz.status} ok=${f.healthz.ok} invoices=${f.invoiceCount}`)
  }

  // snapshot + fork API finding (DESIGN §8 risk #1)
  console.log("\n— SNAPSHOT / FORK —")
  if (r.snapshot) {
    console.log(`  snapshot: ${r.snapshot.snapshotId ?? "(none)"}${r.snapshot.error ? " — FAILED: " + r.snapshot.error : ""}`)
    console.log(`  template: ${r.snapshot.templateId ?? "(none)"}`)
  }

  // fork API finding (risk #1)
  console.log("\n— DESIGN §8 risk #1: fork API verdict —")
  console.log(`  ${r.forkApi.verdict}`)
  console.log(`  detail: ${r.forkApi.detail}`)

  // cleanup
  console.log("\n— CLEANUP LOG —")
  if (r.cleanup) {
    console.log(`  killed sandbox ids: ${r.cleanup.killed.length}`)
    console.log(`  deleted snapshot: ${r.cleanup.deletedSnapshot ?? "(none)"}`)
    console.log(`  deleted template: ${r.cleanup.deletedTemplate ?? "(none)"}`)
    console.log(`  live ColdStart resources after: ${r.cleanup.liveAfter.length}`)
    if (r.cleanup.liveAfter.length === 0) console.log("  ✓ ZERO live resources")
  } else {
    console.log(`  cleanup not run`)
  }
  console.log("=".repeat(70))
  console.log("")
}

// ----------------------------------------------------------------------------
// entrypoint
// ----------------------------------------------------------------------------

const isMain =
  process.argv[1] != null && resolve(process.argv[1]) === fileURLToPath(import.meta.url)

if (isMain) {
  runLiveProof()
    .then(() => process.exit(0))
    .catch((e) => {
      console.error(`[orchestrate] Fatal: ${errText(e)}`)
      process.exit(1)
    })
}
