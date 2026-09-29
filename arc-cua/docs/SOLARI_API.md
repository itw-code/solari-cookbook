# Solari API — verified contract vs. `solari_driver.py`

Researched 2026-09-26 from public docs, then confirmed with one live call (see "Live probe"). Items still marked **unverified** were not exercised by that call.

Sources: [API reference](https://docs.getsolari.com/api-reference) · [Sessions](https://docs.getsolari.com/sessions) · [Desktops](https://docs.getsolari.com/desktops) · [MCP](https://docs.getsolari.com/mcp) · [Pricing](https://docs.getsolari.com/pricing) · [Rust SDK](https://docs.rs/solari-browser/latest/solari_browser/)

## Contract

| Item | Documented value |
|---|---|
| Base URL | `https://api.getsolari.com` (browsers and VMs) |
| Auth | `Authorization: Bearer slr_live_<id>_<secret>` |
| Env var | `SOLARI_API_KEY` (official SDK/MCP also read `SOLARI_BASE_URL`, `SOLARI_BROWSER_URL`) |
| Create browser | `POST /sessions` → `201` |
| Get / release | `GET /sessions/{id}` · `DELETE /sessions/{id}` → `204` |
| Replays | `GET /sessions/{id}/replays` |
| Create body (known fields) | `stealth`, `profileId`, `recording`, `proxy`, `captcha` — full schema **unverified** |
| Response fields | Docs list `id`, `cdpEndpoint`, `wsEndpoint`, `replay`, `expiresAt`, `region`; live create returned `sessionId`, `wsEndpoint`, `cdpEndpoint`, `expiresAt` only (see below) |
| Driving | Raw CDP at `cdpEndpoint` (Playwright `connect_over_cdp`); signed URL is the credential, no auth header |
| Idempotency | `Idempotency-Key: <uuid-v4>` on creates |
| Errors | `{error, code, detail?, message?, retryable?}`; retry only 502/503/504; 429 = concurrency cap, don't retry |
| Desktops | VM API (`POST /sandboxes` family / SDK `desktops.create`); screenshot + mouse/keyboard only, **no accessibility tree exposed** |
| Free plan | $3/month credit, 3 concurrent browsers, $0.15/h; no stealth/proxy/captcha; 1-day replay |

## Live probe (2026-09-26, free plan, body `{}`)

| Call | Status | Latency | Observed shape |
|---|---|---|---|
| `GET /health` | 200 | 870 ms | `{ok, idle, busy, recycling, pools, draining, tripped, saturated, fast:{…}, stealth:{…}}` |
| `POST /sessions` | 201 | 438 ms | `{sessionId, wsEndpoint, cdpEndpoint, expiresAt}` |
| `GET /sessions/{id}` | 200 | 457 ms | `{id, status:"active", kind:"fast", org, createdAt, expiresAt, wsEndpoint, cdpEndpoint}` |
| Playwright `connect_over_cdp(cdpEndpoint)` + `goto` | OK | 1651 ms | one existing context; page title read fine |
| `DELETE /sessions/{id}` | 204 | 283 ms | empty |
| `GET /sessions/{id}/replays` (after release, no `recording`) | 404 | 273 ms | plain text `404 Not Found` |

Findings that differ from the docs:

- **Create returns `sessionId`; get returns `id`.** Read both.
- **The session id is a long signed token** (~250 chars). Treat it as a secret: never log it in full.
- **Default lifetime is 5 hours** (`expiresAt` = `createdAt` + 5h) and billing is hourly, so a leaked
  session costs up to ~$0.75 on the free plan. Release in a `finally` and on process exit.
- No `replay` or `region` field is returned when `recording` is not requested.
- Endpoints are `wss://api.getsolari.com/{cdp,ws}/<signed>` — the URL itself is the credential; redact it too.

## Mismatches in `src/arc_cua/cloud/solari_driver.py`

**Status: all fixed 2026-09-26** — offline contract tests in `tests/test_solari_driver.py`; opt-in live test
in `tests/test_solari_live.py` (`SOLARI_LIVE_TESTS=1` + `SOLARI_API_KEY`). The table records what was wrong.

| Driver assumption | Reality | Fix |
|---|---|---|
| Sends `session_id`, `session_type`, `region`, `viewport`, `record_session`, `metadata` | Unknown fields; `recording` not `record_session`; server assigns id | Send only documented fields; add `Idempotency-Key` |
| Reads `sessionId` / `session_id` | Create returns `sessionId`, get returns `id` | Read `sessionId` or `id` |
| Logs full session id / endpoints | Both are bearer-like capabilities | Redact in logs and repr |
| No cleanup guarantee | 5h default lifetime, billed hourly | Release in `finally` + `atexit` |
| Falls back to invented `wss://api.getsolari.com/ws/{sid}` | Must come from response | Fail if `cdpEndpoint` missing |
| Invents `replay.getsolari.com` / `cloud.arc.ai` URLs | `GET /sessions/{id}/replays` | Fetch replay list on demand |
| `POST /sessions/desktop` | Does not exist; desktops are the VM API | Drop desktop from the driver for now |
| AT-SPI desktop perception | Not exposed by Solari | Desktop support is out of scope |
| Silent mock when no key | — | Raise a clear error |
| No error-code handling | Structured `code` + retry table | Map codes; retry only 5xx transient |

## Strategic note

Solari ships an official MCP server (`npx -y @solarisdk/mcp`, or hosted `https://mcp.getsolari.com/mcp`) with
`solari_browser_create / navigate / read_page / screenshot / click / type / key / evaluate / replay_url / close`
plus sandbox/desktop tools. ARC's value must therefore be what that server lacks — the hard token-budgeted
AXTree with announced truncation, `[#N]` indexed actions, and no-op/stall detection — not session management.
