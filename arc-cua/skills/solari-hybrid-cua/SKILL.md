---
name: solari-hybrid-cua
description: Browser control through ARC — compact [#N] accessibility trees, verified actions, stall detection, marked screenshots — on a local Chromium or a Solari cloud browser. Use when driving a website: filling forms, clicking through a web app, reading a live page, or checking a UI.
---

# ARC browser control

ARC shows a page as a token-budgeted accessibility tree whose actionable lines carry `[#N]` indices, acts on those indices, and reports whether each action changed the page.

Use the `arc_*` MCP tools when they are available: they hold one browser across calls. Otherwise use the CLI (see "CLI fallback"); the loop is the same.

## Loop

1. `arc_open(url)` — pick the backend:
   - `local` (default): Chromium on this machine. `visible=True` opens a window the user can watch.
   - `solari`: a Solari cloud browser. Needs `SOLARI_API_KEY` in the server's environment and bills hourly until closed; `stealth=True` needs a paid plan.
   - `cdp`: attach to an existing browser at `cdp_url`.
2. `arc_inspect` — read the tree, once per page you arrive on by `arc_open`.
3. `arc_act(action, index=N, value=...)` — one action. The result ends with the page after the action, in the same tree format; its `[#N]` indices replace the old ones, so act on them directly without another `arc_inspect`.
4. Done when the tree returned by the last action shows the goal's end state (confirmation text, target URL, saved value) — `success: true` alone only means the action was delivered.
5. `arc_close` — every time, and always for `solari`, which stops billing.

## Reading the tree

```yaml
# AXTree [Actionable: 3 | Tokens: ~45 | Latency: 0.8ms]
- RootWebArea "Sign In" [focused]
  - [#1] textbox "Username" css="#user"
  - [#2] textbox "Password"
  - [#3] button "Sign In"
```

- `css=` appears only for attribute-based locators (`#id`, `[data-testid]`, `[placeholder]`); every `[#N]` is actionable with or without it.
- `Truncated` in the header means the ~1,200-token cap was hit. Plain text is evicted first, links and buttons last; `# !` manifest lines count what went. Indices named in `# !DROPPED-ACTIONABLE [#N]` still work with `arc_act`. On a truncated tree an element you cannot see may still exist: `arc_inspect(query="words")` lists every matching link, button or field on the page, including evicted ones.
- A `WARNING: no actionable nodes` line is a failed perception: retry with a larger `settle_ms` (slow client-rendered apps) or take a screenshot.

## Acting

- Target by `index`; ARC pins it to the exact DOM node, so identical links ("hide", "Edit") resolve to the right row. Use `target` for a shown `css=` selector.
- Actions: `click`, `dblclick`, `fill`, `type`, `select`, `press_key` (value `"Enter"`), `scroll`, `wait`, `goto` (value is the URL).
- `state_changed: false` on a mutating action means it was delivered and changed nothing — usually an inert or wrong element. `stall_suspected: true` (three in a row) means switch strategy: re-inspect and pick a different element, or take a screenshot.
- `page_changed_since_inspect: true` means the page moved on its own before the action ran; check the returned tree before trusting the result.
- `observe=false` drops the returned tree to save tokens when chaining actions on a page you already know (e.g. filling several fields).
- Scrolling a list or table: pass `target` inside the scrolling container, then check `metadata.scroll_applied`; `scroll_mode: "document"` means the page scrolled, not the container.

## Screenshots

`arc_screenshot` costs far more tokens than `arc_inspect`; reach for it when the tree cannot show what you need — canvas/WebGL, charts, images, visual layout. With `marks=True` each `[#N]` is outlined with its number. Image coordinates are page CSS pixels: click unindexed content with `arc_act(action="click", target="coords:X,Y")`.

## CLI fallback

Same loop through `arc-cua` (each call reattaches to one persistent local browser):

```bash
arc-cua inspect --url "https://example.com" [--visible] [--settle-ms 15000]
arc-cua act --action click --index 3
arc-cua act --action fill --target "#user" --value "admin@example.com"
arc-cua close
```

The CLI drives local or `--cdp` browsers only (no Solari backend, no screenshots). `arc-cua run` is not functional; drive tasks step by step.

## Setup

When the `arc_*` tools are missing, from the ARC repo:

```bash
pip install -e ".[mcp]" && playwright install chromium
claude mcp add --scope user arc -- arc-cua-mcp
```

Then restart the agent host. Export `SOLARI_API_KEY` in the environment the host starts from; the key never goes in MCP config.
