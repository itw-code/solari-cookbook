/**
 * server.ts — the Create-Invoice task app (DESIGN.md §1).
 *
 * Built on `node:http` + `node:sqlite` (zero third-party runtime deps).
 * Routes: `/` (list), `/new` (form), POST `/invoices` (create), `/invoices/:id`
 * (confirmation), `/healthz` (probe). The app reads `VARIANT_SEED` (default 0)
 * and derives the active perturbation axes via the same pure function the
 * generator uses, so `sameSeed -> sameVariant` holds at the app layer too.
 * Listens on `PORT` (default 3000); DB path from `DB_PATH` (default
 * `/app/data/invoice.db`; set `DB_PATH=./data/invoice.db` to run locally).
 */

import { createServer, type IncomingMessage, type ServerResponse } from "node:http"
import { openDb, ensureSchema, createInvoice, getInvoice, getInvoiceItems, listInvoices, resolveDbPath } from "./db.js"
import { parseAndValidate, type InvoiceInput } from "./invoice.js"
import { deriveConfig } from "../generate-variants/axes.js"
import { renderList, renderNew, renderInvoice, renderHealthz } from "./render.js"

const PORT = Number(process.env.PORT ?? 3000)
const SEED = Number(process.env.VARIANT_SEED ?? 0)
const config = deriveConfig(SEED)

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolvePromise, reject) => {
    const chunks: Buffer[] = []
    req.on("data", (c: Buffer) => chunks.push(c))
    req.on("end", () => resolvePromise(Buffer.concat(chunks).toString("utf8")))
    req.on("error", reject)
  })
}

function parseUrlEncoded(body: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [k, v] of new URLSearchParams(body)) {
    out[k] = v
  }
  return out
}

function send(res: ServerResponse, status: number, body: string, contentType = "text/html; charset=utf-8"): void {
  res.writeHead(status, { "content-type": contentType })
  res.end(body)
}

async function handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
  const url = new URL(req.url ?? "/", "http://localhost")
  const path = url.pathname
  const method = req.method ?? "GET"

  if (path === "/healthz") {
    send(res, 200, renderHealthz(), "text/plain; charset=utf-8")
    return
  }

  if (method === "GET" && path === "/") {
    send(res, 200, renderList(config, listInvoices(db)))
    return
  }

  if (method === "GET" && path === "/new") {
    const step = url.searchParams.get("step") === "2" ? "2" : "1"
    const rows = Number(url.searchParams.get("rows") ?? "") || undefined
    const values: Record<string, string> = {}
    for (const k of ["customer", "invoice_date", "due_date"]) {
      const v = url.searchParams.get(k)
      if (v !== null) values[k] = v
    }
    send(res, 200, renderNew(config, { step, values, rows }))
    return
  }

  if (method === "POST" && path === "/invoices") {
    const body = await readBody(req)
    const form = parseUrlEncoded(body)
    const parsed = parseAndValidate(form as unknown as InvoiceInput)
    if (!parsed.ok) {
      send(res, 400, `<h1>Invalid invoice</h1><ul>${parsed.errors.map((e) => `<li>${e}</li>`).join("")}</ul>`)
      return
    }
    const created = createInvoice(db, parsed.value)
    // 302 to the confirmation page.
    res.writeHead(302, { location: `/invoices/${created.id}` })
    res.end()
    return
  }

  const invMatch = path.match(/^\/invoices\/(\d+)$/)
  if (method === "GET" && invMatch) {
    const id = Number(invMatch[1])
    const inv = getInvoice(db, id)
    if (!inv) {
      send(res, 404, `<h1>Invoice not found</h1>`)
      return
    }
    const items = getInvoiceItems(db, id)
    send(res, 200, renderInvoice(config, inv, items))
    return
  }

  send(res, 404, `<h1>Not found</h1>`)
}

const db = openDb(resolveDbPath())
ensureSchema(db)

const server = createServer((req, res) => {
  handle(req, res).catch((err) => {
    console.error("[variant-app] request error:", err)
    if (!res.headersSent) send(res, 500, `<h1>Internal error</h1>`)
  })
})

server.listen(PORT, () => {
  console.log(`[variant-app] listening on :${PORT} (seed=${SEED}, db=${resolveDbPath()})`)
})
