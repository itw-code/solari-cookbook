/**
 * render.ts — server-rendered HTML templates for the Create-Invoice app.
 *
 * Every template accepts the active perturbation config (P1–P5) and varies the
 * HTML accordingly: labels (P1), page structure/flow (P2), field order &
 * density (P3), nav grouping (P4), and theme/CSS (P5). The FORM FIELD NAMES the
 * client submits are always the canonical contract (customer, invoice_date,
 * due_date, tax_rate, description, qty, unit_price) — perturbation never changes
 * the wire contract, only the presentation (DESIGN.md §1).
 *
 * No client JS. Overrides P2's wizard by using GET-steps + hidden fields.
 */

import type { PerturbationConfig } from "../generate-variants/axes.js"
import type { Invoice, InvoiceItem } from "./db.js"

// --- tiny helpers -----------------------------------------------------------

function esc(s: unknown): string {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;")
}

function money(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`
}

function themeCss(cfg: PerturbationConfig): string {
  const p5 = cfg.P5
  const btnBase = `.btn{display:inline-block;padding:.55rem 1.1rem;font-weight:600;cursor:pointer;border:1px solid ${p5.accent};border-radius:${p5.radius};text-decoration:none;font-family:inherit;font-size:1rem}`
  const btnStyle =
    p5.buttonStyle === "outline"
      ? `.btn{background:transparent;color:${p5.accent}}`
      : p5.buttonStyle === "pill"
        ? `.btn{background:${p5.accent};color:${p5.accentText};border-radius:999px}`
        : `.btn{background:${p5.accent};color:${p5.accentText}}`
  return `
:root{--bg:${p5.bg};--text:${p5.text};--muted:${p5.muted};--accent:${p5.accent};--accent-text:${p5.accentText};--border:${p5.border};--radius:${p5.radius}}
*{box-sizing:border-box}
body{margin:0;font-family:${p5.font};background:var(--bg);color:var(--text);line-height:1.5}
a{color:var(--accent)}
h1,h2{font-weight:650}
.container{max-width:820px;margin:0 auto;padding:1.5rem}
.card{background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);padding:1.25rem;margin:1rem 0}
input,select,textarea{font-family:inherit;font-size:1rem;padding:.5rem .6rem;border:1px solid var(--border);border-radius:var(--radius);width:100%;background:var(--bg);color:var(--text)}
label{display:block;font-weight:600;margin:.6rem 0 .2rem;color:${cfg.P5.dark ? "" : "var(--text)"}}
.row{display:flex;gap:1rem;flex-wrap:wrap}
.row>div{flex:1;min-width:150px}
table{width:100%;border-collapse:collapse}
th,td{text-align:left;padding:.5rem;border-bottom:1px solid var(--border)}
.muted{color:var(--muted)}
.badge{display:inline-block;padding:.15rem .5rem;border-radius:var(--radius);font-size:.85rem;background:var(--accent);color:var(--accent-text)}
.fab{position:fixed;right:1.5rem;bottom:1.5rem;z-index:10}
.alert{background:${p5.accent};color:${p5.accentText};padding:.6rem 1rem;border-radius:var(--radius);margin:.5rem 0}
${btnBase}
${btnStyle}
`
}

function navHtml(cfg: PerturbationConfig): string {
  const p4 = cfg.P4
  const p1 = cfg.P1
  const labels: Record<string, string> = { invoices: p1.listHeading, new: p1.invoke, reports: "Reports" }
  const hrefs: Record<string, string> = { invoices: "/", new: "/new", reports: "/" }
  const items = p4.order.map((k) => `<li><a href="${hrefs[k]}">${esc(labels[k])}</a></li>`).join("")
  const list = p4.grouped ? `<li><details><summary>${esc(p1.listHeading)}</summary><ul>${items}</ul></details></li>` : items
  const style =
    p4.navPosition === "side"
      ? `nav{background:var(--bg);border-right:1px solid var(--border);min-height:100vh;padding:1rem;width:200px;float:left}nav ul{list-style:none;padding:0;margin:0}nav li{margin:.4rem 0}`
      : `nav{background:var(--bg);border-bottom:1px solid var(--border);padding:.6rem 1.5rem}nav ul{list-style:none;padding:0;margin:0;display:flex;gap:1.25rem}`
  return `<nav><ul>${list}</ul></nav><style>${style}</style>`
}

function shell(cfg: PerturbationConfig, title: string, body: string): string {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)}</title>
<style>${themeCss(cfg)}</style>
</head>
<body>
${navHtml(cfg)}
<div class="container">
${body}
</div>
</body>
</html>`
}

// --- routes -----------------------------------------------------------------

/** `/` — invoice list page with the create entry point. */
export function renderList(cfg: PerturbationConfig, invoices: Invoice[]): string {
  const p1 = cfg.P1
  const topBarNew = cfg.P2.entryPosition === "topbar"
  const midBodyNew = cfg.P2.entryPosition === "midbody"

  let entryButtons = ""
  if (topBarNew || midBodyNew) {
    entryButtons = `<p><a class="btn" href="/new">${esc(p1.create)}</a></p>`
  }

  const rows =
    invoices.length === 0
      ? `<tr><td colspan="4" class="muted">No invoices yet.</td></tr>`
      : invoices
          .map(
            (inv) =>
              `<tr><td><a href="/invoices/${inv.id}">${esc(inv.invoice_no)}</a></td><td>${esc(inv.customer)}</td><td>${esc(inv.status)}</td><td>${money(inv.total_cents)}</td></tr>`,
          )
          .join("")

  const fab = cfg.P2.entryPosition === "fab" ? `<a class="btn fab" href="/new">+ ${esc(p1.invoke)}</a>` : ""
  const sidebarNew = cfg.P2.entryPosition === "sidebar" ? `<p><a class="btn" href="/new">${esc(p1.create)}</a></p>` : ""

  const body = `${entryButtons}${sidebarNew}
<h1>${esc(p1.listHeading)}</h1>
<table><thead><tr><th>Invoice</th><th>Customer</th><th>Status</th><th>Total</th></tr></thead><tbody>${rows}</tbody></table>
${fab}`
  return shell(cfg, p1.listHeading, body)
}

export interface RenderNewInput {
  step?: "1" | "2"
  /** Values carried from step 1 to step 2 (wizard) via the query string. */
  values?: Record<string, string>
  /** Number of line-item rows to render (>=1). */
  rows?: number
}

/** `/new` — the create-invoice form. Shape varies by P2 (single vs wizard). */
export function renderNew(cfg: PerturbationConfig, input: RenderNewInput = {}): string {
  const p1 = cfg.P1
  const p2 = cfg.P2
  const rows = Math.max(1, input.rows ?? cfg.P3.defaultRows)
  const isWizard = p2.layout === "wizard" || p2.layout === "wizard_inline_addrows"
  const step = isWizard ? input.step ?? "1" : "1"

  const metaNameToLabel: Record<string, string> = {
    customer: p1.customer,
    invoice_date: "Invoice Date",
    due_date: "Due Date",
    tax_rate: p1.tax,
  }

  const metaFields = cfg.P3.metaOrder.map((name) => {
    const label = metaNameToLabel[name]
    const value = input.values?.[name] ?? ""
    const attr = name === "customer" ? `value="${esc(value)}"` : ""
    const nameAttr = isWizard && step === "1" ? `name="${name}"` : `name="${name}"`
    if (name === "tax_rate") {
      return `<div><label>${esc(label)}</label>${taxControl(cfg, "tax_rate", value)}</div>`
    }
    return `<div><label>${esc(label)}</label><input type="text" ${nameAttr} ${attr}></div>`
  })

  const optionalFields = cfg.P3.optionalFields
    .map((name) => {
      const labelMap: Record<string, string> = { po_number: "PO Number", reference: "Reference", notes: "Notes" }
      return `<div><label>${esc(labelMap[name])} <span class="muted">(optional)</span></label><input type="text" name="${name}"></div>`
    })
    .join("")

  const itemNameToLabel: Record<string, string> = { description: p1.description, qty: p1.qty, unit_price: p1.unitPrice }

  const itemRow = (_rowIdx: number, nameSuffix = "") => {
    const l = itemNameToLabel
    const order = cfg.P3.itemOrder.map((f) => `<div><label>${esc(l[f])}</label><input type="text" name="${f}${nameSuffix}"></div>`).join("")
    return `<div class="row">${order}</div>`
  }

  const addRowControl =
    p2.layout === "wizard_inline_addrows"
      ? `<p><a class="btn" href="/new?step=${step}&rows=${rows + 1}">+ Add row</a></p>`
      : ""

  // Wizard: step 1 posts (GET) to step 2 carrying customer/date values.
  const hiddenCarry = Object.entries(input.values ?? {})
    .map(([k, v]) => `<input type="hidden" name="${esc(k)}" value="${esc(v)}">`)
    .join("")

  if (isWizard && step === "1") {
    // Step 1: customer + dates only.
    const body = `<h1>${esc(p1.create)} <span class="muted">· Step 1 of 2</span></h1>
<form method="get" action="/new">
  <input type="hidden" name="step" value="2">
  <div class="card"><div class="row">${metaFields}</div></div>
  ${optionalFields}
  <p><button class="btn" type="submit">Next</button></p>
</form>`
    return shell(cfg, p1.create, body)
  }

  const metaHtmlWizardStep2 = cfg.P3.metaOrder
    .map((name) => {
      const value = input.values?.[name] ?? ""
      // In step 2 the metadata is carried as hidden fields (already typed).
      return `<input type="hidden" name="${name}" value="${esc(value)}">`
    })
    .join("")

  const metaHtml = isWizard ? metaHtmlWizardStep2 : `<div class="card"><div class="row">${metaFields}</div></div>`

  const itemFields = Array.from({ length: rows }, (_, i) => itemRow(i, i === 0 ? "" : `_${i + 1}`)).join("")

  const confirmText = p2.confirmation === "inline" ? `${p1.confirmation} — press ${esc(p1.submit)}` : ""
  const body = `<h1>${esc(p1.create)}${isWizard ? ` <span class="muted">· Step 2 of 2</span>` : ""}</h1>
<form method="post" action="/invoices">
  ${isWizard ? hiddenCarry : ""}
  ${metaHtml}
  <div class="card">
    <h2>Line items</h2>
    ${itemFields}
    ${addRowControl}
  </div>
  ${optionalFields}
  ${confirmText ? `<p class="muted">${esc(confirmText)}</p>` : ""}
  <p><button class="btn" type="submit">${esc(p1.submit)}</button></p>
</form>
${isWizard && step === "2" ? `<p><a href="/new">${esc("Back")}</a></p>` : ""}`
  return shell(cfg, p1.create, body)
}

function taxControl(cfg: PerturbationConfig, name: string, value: string): string {
  if (cfg.P3.taxControl === "preset") {
    const opts = [7.5, 8, 10, 12.5, 15].map((v) => `<option value="${v}"${String(v) === value ? " selected" : ""}>${v}%</option>`).join("")
    return `<select name="${name}">${opts}</select>`
  }
  return `<input type="text" name="${name}" value="${esc(value)}">`
}

/** `/invoices/:id` — confirmation page. */
export function renderInvoice(cfg: PerturbationConfig, inv: Invoice, items: InvoiceItem[]): string {
  const p1 = cfg.P1
  const p2 = cfg.P2
  const itemRows = items
    .map((it) => `<tr><td>${esc(it.description)}</td><td>${it.qty}</td><td>${money(it.unit_price_cents)}</td><td>${money(it.line_total_cents)}</td></tr>`)
    .join("")

  const details = `<div class="card">
<h2>${esc(inv.invoice_no)}</h2>
<p><strong>${esc(p1.customer)}:</strong> ${esc(inv.customer)}</p>
<p><strong>Invoice date:</strong> ${esc(inv.invoice_date)} &nbsp; <strong>Due date:</strong> ${esc(inv.due_date)}</p>
<table><thead><tr><th>${esc(p1.description)}</th><th>${esc(p1.qty)}</th><th>${esc(p1.unitPrice)}</th><th>Line total</th></tr></thead><tbody>${itemRows}</tbody></table>
<p><strong>Subtotal:</strong> ${money(inv.subtotal_cents)} &nbsp; <strong>${esc(p1.tax)}:</strong> ${money(inv.tax_cents)} &nbsp; <strong>Total:</strong> ${money(inv.total_cents)}</p>
<p><span class="badge">${esc(inv.status)}</span></p>
</div>`

  const banner = p2.confirmation === "inline" ? `<div class="alert">✓ ${esc(p1.confirmation)}</div>` : ""
  const heading = `<h1>${esc(p1.confirmation)}</h1>`
  const body = `${banner}${heading}${details}<p><a href="/">${esc("Back to list")}</a></p>`
  return shell(cfg, p1.confirmation, body)
}

/** `/healthz` — readiness probe (fixed content, no perturbation). */
export function renderHealthz(): string {
  return "ok"
}
