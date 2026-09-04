/**
 * server.ts — Demo Target Site for ColdStart + Slop-Catcher.
 *
 * Built on dependency-free `node:http` + `node:sqlite` (same pattern as `src/variant-app/`).
 *
 * Routes:
 *   - GET /                  -> Clean, human-grade design (good contrast, 8px spacing grid, custom font stack).
 *   - GET /?slop=1           -> Intentional "AI slop" design (purple gradient hero, default Inter/Arial,
 *                               low-contrast gray-on-gray button, random margins).
 *   - POST /signup           -> Writes submission to SQLite `signups(id, name, email, created_at)`.
 *   - GET /design-metrics.json -> Deterministic design metrics for the current variant:
 *                               { contrastRatio: 7.2, spacingVariance: 0 } for clean,
 *                               { contrastRatio: 2.1, spacingVariance: 15 } for slop.
 *                               HONESTY (audit B4): these metrics are SELF-REPORTED
 *                               by this app about itself — a circular measurement.
 *                               Any scan that consumes this endpoint is a MOCK / dry-run,
 *                               not an independent audit of the page's rendered CSS.
 *   - GET /healthz           -> Health check probe.
 */

import { createServer, type IncomingMessage, type ServerResponse, type Server } from "node:http"
import { mkdirSync } from "node:fs"
import { dirname, resolve } from "node:path"
import type { AddressInfo } from "node:net"
import { DatabaseSync } from "../sqlite.ts"

export interface SignupRecord {
  id: number
  name: string
  email: string
  created_at: string
}

export interface DesignMetricsResponse {
  contrastRatio: number
  spacingVariance: number
}

export const CLEAN_METRICS: DesignMetricsResponse = {
  contrastRatio: 7.2,
  spacingVariance: 0,
}

export const SLOP_METRICS: DesignMetricsResponse = {
  contrastRatio: 2.1,
  spacingVariance: 15,
}

/** Ensure the signups schema is initialized in the SQLite database. */
export function ensureDemoSchema(db: DatabaseSync): void {
  db.exec(`
    CREATE TABLE IF NOT EXISTS signups (
      id         INTEGER PRIMARY KEY AUTOINCREMENT,
      name       TEXT    NOT NULL,
      email      TEXT    NOT NULL,
      created_at TEXT    NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_signups_email ON signups(email);
  `)
}

/** Open or create a SQLite database for the demo site. Supports ':memory:'. */
export function openDemoDb(dbPath: string = ":memory:"): DatabaseSync {
  if (dbPath !== ":memory:") {
    const dir = dirname(dbPath)
    if (dir && dir !== ".") mkdirSync(dir, { recursive: true })
  }
  const db = new DatabaseSync(dbPath)
  ensureDemoSchema(db)
  return db
}

/** Insert a signup record into the SQLite database. */
export function insertSignup(db: DatabaseSync, name: string, email: string): SignupRecord {
  const created_at = new Date().toISOString()
  const res = db
    .prepare("INSERT INTO signups (name, email, created_at) VALUES (?, ?, ?)")
    .run(name.trim(), email.trim(), created_at)
  const id = Number(res.lastInsertRowid)
  return { id, name: name.trim(), email: email.trim(), created_at }
}

/** List all signups in reverse chronological order. */
export function listSignups(db: DatabaseSync): SignupRecord[] {
  return db.prepare("SELECT id, name, email, created_at FROM signups ORDER BY id DESC").all() as unknown as SignupRecord[]
}

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolvePromise, reject) => {
    const chunks: Buffer[] = []
    req.on("data", (c: Buffer) => chunks.push(c))
    req.on("end", () => resolvePromise(Buffer.concat(chunks).toString("utf8")))
    req.on("error", reject)
  })
}

function parseBody(body: string, contentType: string = ""): { name: string; email: string } {
  if (contentType.includes("application/json")) {
    try {
      const parsed = JSON.parse(body)
      return {
        name: typeof parsed.name === "string" ? parsed.name : "",
        email: typeof parsed.email === "string" ? parsed.email : "",
      }
    } catch {
      return { name: "", email: "" }
    }
  }

  const params = new URLSearchParams(body)
  return {
    name: params.get("name") ?? "",
    email: params.get("email") ?? "",
  }
}

function send(res: ServerResponse, status: number, body: string, contentType = "text/html; charset=utf-8"): void {
  res.writeHead(status, { "content-type": contentType })
  res.end(body)
}

function renderCleanPage(): string {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Request Early Access</title>
  <style>
    /* Clean Human-Grade Design System: 8px grid, high contrast, custom font stack */
    :root {
      --bg: #ffffff;
      --card-bg: #f8fafc;
      --text-main: #0f172a;
      --text-muted: #475569;
      --primary: #0284c7;
      --primary-hover: #0369a1;
      --primary-text: #ffffff;
      --border: #cbd5e1;
      --radius: 8px;
    }
    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background-color: var(--bg);
      color: var(--text-main);
      line-height: 1.5;
      display: flex;
      justify-content: center;
      align-items: center;
      min-height: 100vh;
      padding: 24px;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 32px;
      max-width: 440px;
      width: 100%;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }
    .badge {
      display: inline-block;
      font-size: 12px;
      font-weight: 600;
      color: var(--primary);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 8px;
    }
    h1 {
      font-size: 24px;
      font-weight: 700;
      color: var(--text-main);
      margin-bottom: 8px;
    }
    p.subtitle {
      font-size: 14px;
      color: var(--text-muted);
      margin-bottom: 24px;
    }
    .form-group {
      margin-bottom: 16px;
    }
    label {
      display: block;
      font-size: 14px;
      font-weight: 600;
      color: var(--text-main);
      margin-bottom: 8px;
    }
    input[type="text"], input[type="email"] {
      width: 100%;
      padding: 12px 16px;
      font-size: 14px;
      color: var(--text-main);
      background: #ffffff;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      outline: none;
      transition: border-color 0.15s ease;
    }
    input[type="text"]:focus, input[type="email"]:focus {
      border-color: var(--primary);
      box-shadow: 0 0 0 3px rgba(2, 132, 199, 0.15);
    }
    .btn-submit {
      width: 100%;
      padding: 12px 24px;
      font-size: 14px;
      font-weight: 600;
      background-color: var(--primary);
      color: var(--primary-text);
      border: none;
      border-radius: var(--radius);
      cursor: pointer;
      margin-top: 8px;
      transition: background-color 0.15s ease;
    }
    .btn-submit:hover {
      background-color: var(--primary-hover);
    }
  </style>
</head>
<body data-variant="clean">
  <div class="card clean-card">
    <span class="badge">Preview Release</span>
    <h1>Request Early Access</h1>
    <p class="subtitle">Experience high-craft tooling designed with intentional typography and 8px grid discipline.</p>
    <form action="/signup" method="POST" id="access-form">
      <div class="form-group">
        <label for="name">Full Name</label>
        <input type="text" id="name" name="name" placeholder="Alex Rivera" required />
      </div>
      <div class="form-group">
        <label for="email">Work Email</label>
        <input type="email" id="email" name="email" placeholder="alex@company.com" required />
      </div>
      <button type="submit" id="submit-btn" class="btn-submit">Request Early Access</button>
    </form>
  </div>
</body>
</html>`
}

function renderSlopPage(): string {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Request Early Access (AI-Generated)</title>
  <style>
    /* Intentional AI Slop Design: purple gradient hero, default Inter/Arial, low-contrast gray-on-gray, random off-grid margins */
    * {
      box-sizing: border-box;
    }
    body {
      font-family: 'Inter', Arial, sans-serif;
      background: #fafafa;
      color: #333333;
      margin: 0;
      padding: 0;
    }
    .purple-hero {
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: #ffffff;
      padding: 43px 21px 57px 19px; /* off-grid random padding */
      text-align: center;
    }
    .purple-hero h1 {
      font-size: 29px; /* un-tuned font size */
      margin-top: 13px; /* off-grid random margin */
      margin-bottom: 27px; /* off-grid random margin */
      font-weight: 700;
    }
    .purple-hero p {
      font-size: 15px;
      margin-left: 9px;
      margin-right: 17px;
      opacity: 0.9;
    }
    .container {
      max-width: 463px; /* off-grid width */
      margin: -23px auto 39px auto; /* off-grid negative overlap */
      background: #ffffff;
      border: 1px solid #d4d4d4;
      padding: 29px 19px 33px 21px; /* random margins and padding */
    }
    .form-group {
      margin-top: 11px;
      margin-bottom: 23px; /* off-grid spacing variance */
    }
    label {
      display: block;
      font-size: 13px;
      color: #666666;
      margin-bottom: 7px;
    }
    input[type="text"], input[type="email"] {
      width: 100%;
      padding: 9px 11px; /* irregular padding */
      font-size: 13px;
      border: 1px solid #cccccc;
    }
    /* Low-contrast gray-on-gray button (intentional WCAG violation, contrast ~ 2.1:1) */
    .btn-slop-submit {
      width: 100%;
      background-color: #888888;
      color: #777777;
      border: 1px solid #777777;
      padding: 7px 19px;
      font-size: 13px;
      margin-top: 17px;
      margin-bottom: 11px;
      cursor: pointer;
    }
  </style>
</head>
<body data-variant="slop">
  <div class="purple-hero">
    <h1>Supercharge Autonomous Intelligence</h1>
    <p>Leverage synergistic paradigm-shifting cognitive architecture for scalable AI transformation.</p>
  </div>
  <div class="container slop-container">
    <form action="/signup" method="POST" id="access-form">
      <div class="form-group">
        <label for="name">Name</label>
        <input type="text" id="name" name="name" placeholder="Enter name" required />
      </div>
      <div class="form-group">
        <label for="email">Email</label>
        <input type="email" id="email" name="email" placeholder="Enter email" required />
      </div>
      <button type="submit" id="submit-btn" class="btn-slop-submit">Request Early Access</button>
    </form>
  </div>
</body>
</html>`
}

function renderSignupSuccess(name: string, email: string): string {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Access Requested</title>
  <style>
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      display: flex;
      justify-content: center;
      align-items: center;
      min-height: 100vh;
      margin: 0;
      background: #f8fafc;
      color: #0f172a;
    }
    .card {
      background: #ffffff;
      border: 1px solid #e2e8f0;
      border-radius: 8px;
      padding: 32px;
      max-width: 440px;
      text-align: center;
    }
    h1 {
      font-size: 20px;
      color: #0284c7;
      margin-bottom: 12px;
    }
    p {
      font-size: 14px;
      color: #475569;
    }
  </style>
</head>
<body>
  <div class="card">
    <h1 id="confirmation-header">Access Requested</h1>
    <p id="confirmation-message">Thank you, <strong>${escapeHtml(name)}</strong>! Your early access request for <code>${escapeHtml(email)}</code> has been recorded.</p>
  </div>
</body>
</html>`
}

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;")
}

export interface DemoServerOptions {
  port?: number
  dbPath?: string
  db?: DatabaseSync
}

export interface DemoServerInstance {
  server: Server
  port: number
  baseUrl: string
  db: DatabaseSync
  close(): Promise<void>
}

/**
 * Creates the HTTP request handler and wires the SQLite database.
 */
export function createDemoServer(options: DemoServerOptions = {}): { server: Server; db: DatabaseSync } {
  const db = options.db ?? openDemoDb(options.dbPath ?? process.env.DEMO_DB_PATH ?? ":memory:")

  const server = createServer(async (req, res) => {
    try {
      const url = new URL(req.url ?? "/", `http://${req.headers.host ?? "localhost"}`)
      const path = url.pathname
      const method = req.method ?? "GET"

      if (path === "/healthz") {
        send(res, 200, "OK", "text/plain; charset=utf-8")
        return
      }

      if (method === "GET" && path === "/") {
        const isSlop = url.searchParams.get("slop") === "1"
        const html = isSlop ? renderSlopPage() : renderCleanPage()
        send(res, 200, html)
        return
      }

      if (method === "GET" && path === "/design-metrics.json") {
        // HONESTY (audit B4): these metrics are hardcoded constants served by the
        // app ABOUT ITSELF. A Slop-Catcher scan that reads them is measuring a
        // self-report, not the rendered page — such scans must be labeled MOCK / dry-run.
        const isSlop = url.searchParams.get("slop") === "1"
        const metrics = isSlop ? SLOP_METRICS : CLEAN_METRICS
        send(res, 200, JSON.stringify(metrics, null, 2), "application/json; charset=utf-8")
        return
      }

      if (method === "POST" && path === "/signup") {
        const rawBody = await readBody(req)
        const contentType = req.headers["content-type"] ?? ""
        const { name, email } = parseBody(rawBody, contentType)

        if (!name.trim() || !email.trim()) {
          send(res, 400, "<h1>Bad Request</h1><p>Both name and email are required.</p>")
          return
        }

        const record = insertSignup(db, name, email)

        const accept = req.headers["accept"] ?? ""
        if (accept.includes("application/json")) {
          send(res, 200, JSON.stringify({ ok: true, signup: record }), "application/json; charset=utf-8")
          return
        }

        send(res, 200, renderSignupSuccess(record.name, record.email))
        return
      }

      send(res, 404, "<h1>404 Not Found</h1>")
    } catch (err) {
      console.error("[demo-site] Error processing request:", err)
      if (!res.headersSent) {
        send(res, 500, "<h1>500 Internal Server Error</h1>")
      }
    }
  })

  return { server, db }
}

/**
 * Boots the demo site server on the specified port (default: ephemeral port 0).
 */
export async function startDemoServer(options: DemoServerOptions = {}): Promise<DemoServerInstance> {
  const { server, db } = createDemoServer(options)
  const requestedPort = options.port ?? 0

  await new Promise<void>((resolvePromise, reject) => {
    server.listen(requestedPort, () => resolvePromise())
    server.on("error", reject)
  })

  const addr = server.address() as AddressInfo
  const port = addr.port
  const baseUrl = `http://localhost:${port}`

  const close = async (): Promise<void> => {
    await new Promise<void>((resolveClose) => {
      server.close(() => resolveClose())
    })
    try {
      db.close()
    } catch {
      // Ignore if already closed
    }
  }

  return {
    server,
    port,
    baseUrl,
    db,
    close,
  }
}

// CLI entry point if run directly
if (process.argv[1] && resolve(process.argv[1]) === resolve(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"))) {
  const port = Number(process.env.PORT ?? 3000)
  startDemoServer({ port }).then((inst) => {
    console.log(`[demo-site] Running at ${inst.baseUrl}`)
  }).catch((err) => {
    console.error("[demo-site] Fatal start error:", err)
    process.exit(1)
  })
}
