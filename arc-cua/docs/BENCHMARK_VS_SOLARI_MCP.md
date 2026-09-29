# ARC MCP vs Solari MCP — head-to-head (2026-09-27)

**Verdict:**
- **Success and tokens:** on 7 grounding tasks ARC succeeded on 7 and Solari's official MCP on 6, and ARC's tools handed the agent **3.3× fewer perception tokens** (8,438 vs 28,198).
- **Protocol traffic:** ARC sent **15× fewer DevTools Protocol commands** (255 vs 3,868).
- **Speed:** ARC's counted tool calls now take **70 s against Solari's 86 s**. Before the round-trip fix below, ARC was the slower one (99 s vs 78 s).
- **Real model:** a small, fast LLM driving ARC through a coding agent succeeded on all 13 task runs that reached the model, in 3–5 tool calls and about 25 s each.
- **One call per action:** with one model call per action (Part D), Gemini 3.8 Flash completed 24/24 runs, including Google Flights, at a median 9.4 s per task. Gemini 3.5 Flash-Lite decides in 0.9 s and did Google Flights in 16–22 s. That's not yet Jev's 7.1 s.

Raw data:
- Head-to-head: `artifacts/benchmarks/vs_solari_mcp_20260927-035501.{json,md}` (after the round-trip fix; Part A below is from `vs_solari_mcp_20260927-030500`, whose page reads the fix doesn't affect)
- LLM agent: `artifacts/benchmarks/llm_agent_omp_20260927-032435.{json,md}` and `llm_agent_omp_20260927-033001.{json,md}`
- Scripts: `scripts/benchmark_vs_solari_mcp.py`, `scripts/benchmark_llm_agent_omp.py`
- Before the round-trip fix: `vs_solari_mcp_20260927-030500`. Before timing was added: `vs_solari_mcp_20260926-215606`.

## Setup

- Both servers ran over stdio exactly as an agent host runs them: `arc-cua-mcp` (backend `solari`) and `npx -y @solarisdk/mcp` v0.4.6 (`mode: "fast"`, captcha off).
- Both used **Solari cloud browsers** from the fast pool on the free plan, with the same 800×600 viewport.
- **Parts A and B use no LLM.** Each task is a scripted policy standing in for an agent:
  - **ARC:** `arc_inspect`, then match the named `[#N]` line, then `arc_act` by index. On a truncated tree it falls back to `arc_inspect(query=…)`. When the policy needs the next page (Wikipedia's search toggle), it reads the tree `arc_act` returns instead of calling `arc_inspect` again.
  - **Solari:** `read_page` with `links` for link targets and `html` for form controls, then derive a `querySelector` selector with an HTML parser, then `solari_browser_click` / `_type`.
- **How things are measured:**
  - Tokens are estimated as chars/4 for both.
  - **s** is the summed latency of the counted tool calls.
  - **CDP** is the number of DevTools Protocol commands those calls sent. It is counted from each server's own debug log (Playwright `pw:protocol`, Puppeteer `puppeteer:protocol:SEND`).
  - Verification reads are excluded from every count.

## Part A — what one "look at the page" costs

| Page | ARC `arc_inspect` | ARC actionable (visible / total) | Solari `text` | Solari `links` | Solari `html` |
|---|---:|---:|---:|---:|---:|
| example.com | 82 | 1 / 1 | 37 | 42 | 101 |
| news.ycombinator.com | 1,240 (T) | 109 / 230 | 1,049 | 5,608 | 7,516 (T) |
| en.wikipedia.org/wiki/Web_browser | 1,239 (T) | 55 / 486 | 5,495 | 6,527 | 7,519 (T) |
| github.com/microsoft/playwright | 1,225 (T) | 46 / 265 | 2,673 | 6,160 | 7,519 (T) |
| docs.python.org asyncio | 1,239 (T) | 76 / 102 | 1,010 | 2,255 | 6,861 |
| MDN `<input>` | 1,072 (T) | 39 / 1,522 | 7,527 (T) | 6,683 | 7,528 (T) |
| httpbin.org/forms/post | 468 | 16 / 16 | 59 | 22 | 359 |
| todomvc (React) | 466 | 12 / 12 | 174 | 376 | 755 |

(T) = truncated by the tool. ARC truncates by evicting plain text first, then affordances. Solari truncates the output tail.

## Part B — grounding tasks

| Task | ARC | Solari | ARC calls / tokens / s / CDP | Solari calls / tokens / s / CDP |
|---|:-:|:-:|---:|---:|
| HN: click "new" | ✅ | ✅ | 3 / 1,237 / 6.9 / 28 | 3 / 5,575 / 9.0 / 964 |
| HN: 2nd "N comments" link | ✅ | ✅ | 3 / 1,237 / 6.2 / 28 | 3 / 5,575 / 10.3 / 964 |
| Wikipedia: search | ✅ | ❌ | 5 / 2,568 / 21.6 / 51 | 3 / 7,519 / 16.4 / 70 |
| httpbin: fill form, pick radio, submit | ✅ | ✅ | 5 / 468 / 12.3 / 65 | 5 / 359 / 18.8 / 84 |
| GitHub: Issues tab | ✅ | ✅ | 3 / 1,223 / 9.0 / 29 | 3 / 6,160 / 11.2 / 1,395 |
| Python docs: "Coroutines and tasks" | ✅ | ✅ | 3 / 1,239 / 7.9 / 28 | 3 / 2,255 / 10.1 / 347 |
| TodoMVC: add item | ✅ | ✅ | 4 / 466 / 6.3 / 26 | 3 / 755 / 10.3 / 44 |
| **Total** | **7/7** | **6/7** | **26 / 8,438 / 70.2 / 255** | **23 / 28,198 / 86.1 / 3,868** |

**Why Solari missed Wikipedia:** at 800 px Wikipedia collapses its search box behind a button. The HTML still contains `input[name=search]`, so the HTML-reading policy typed into a box that wasn't visible. HTML doesn't show visibility. The accessibility tree does, so ARC's policy clicked the `Search` button and read the tree that click returned.

**Where the CDP gap comes from:** Solari's `read_page("links")` walks the DOM from the client, which costs 964 commands on Hacker News and 1,395 on GitHub. Its `html` read is cheap (44–84 commands per task), about the same as ARC. ARC fetches the whole accessibility tree in a few commands.

**Speed, and the round-trip fix:** every CDP message to a Solari browser is a network round trip of about 0.2–0.5 s, so ARC's speed is set by how many of them it makes. The first timed run had ARC at 99 s against Solari's 78 s. A profile of one Hacker News click showed why:
- **Tree extraction took 1.4 s.** Each extraction opened a new CDP session and re-enabled two domains before its two real calls.
- **Node pinning took 1.5 s,** over five round trips.
- **Settling took two extra extractions.** Confirming the page had settled after an action re-read the tree twice more.

The fix reuses one CDP session per page, pins in two round trips, and counts the post-action snapshot as the first settle read. Measured on the same click:

| Stage | Before | After |
|---|---:|---:|
| Tree extraction | 1.3–1.8 s | 0.7 s |
| Pin node | 1.5 s | 0.4 s |
| `arc_act`, no returned tree | 6.9 s | 4.0 s |
| `arc_act`, returned tree | 10.8 s | 4.9 s |

ARC is now faster on 6 of 7 tasks. The exception is Wikipedia, where it makes two more calls (open the search toggle, then fill). Solari's own totals varied between runs (78 s, then 86 s), so read the tool times as ±10%.

## Part C — a real LLM agent on ARC

The same 7 tasks, but a model chooses every action.
- **Model:** `laguna-xs-2-1:free` via the Kenari provider. It was picked for speed: in a quick check (`omp bench`, 4 runs each) its time to first token was 1.7 s median and 2.5 s p95, the steadiest of the free fast models tried. Gemma 4 31B ranged from 1.1 s to 14 s.
- **Agent:** the Oh My Pi coding agent (`omp`) with its built-in tools disabled, so `arc-cua-mcp` was its only tool set.
- **Browser:** local headless Chromium. Every omp run starts a fresh ARC server, which on Solari would be a separately billed session per task.
- **Instructions:** a short system prompt telling the model to read the tree that `arc_act` returns instead of re-inspecting.
- **Runs:** two, after the fixes below.

| Task | Run 1 | Run 2 | Wall s (1 / 2) | Model s (1 / 2) | Tool s (1 / 2) | Tool calls |
|---|:-:|:-:|---:|---:|---:|---:|
| HN: click "new" | ✅ | ✅ | 18.2 / 27.2 | 5.0 / 14.9 | 7.6 / 7.3 | 3 |
| HN: 2nd "N comments" link | ✅ | ⚠️ | 25.5 / — | 12.9 / — | 7.1 / — | 3 |
| Wikipedia: search | ✅ | ✅ | 34.3 / 30.7 | 15.3 / 13.1 | 13.9 / 12.7 | 4 |
| httpbin: fill form, pick radio, submit | ✅ | ✅ | 180.3 / 25.5 | 169.4 / 13.4 | 7.2 / 7.1 | 5 |
| GitHub: Issues tab | ✅ | ✅ | 23.2 / 23.0 | 7.4 / 8.0 | 11.7 / 10.9 | 3 |
| Python docs: "Coroutines and tasks" | ✅ | ✅ | 26.1 / 24.7 | 12.1 / 11.0 | 9.6 / 9.1 | 4 |
| TodoMVC: add item | ✅ | ✅ | 17.8 / 20.8 | 8.4 / 10.2 | 5.9 / 5.6 | 4 |

- **13/13 runs that reached the model succeeded.** ⚠️ marks the one that never started: the free Kenari tier rejected the request (`400 upstream_rejected`) before any tool call.
- **Typical run:** about 25 s wall time and 3–5 tool calls. That breaks down into about 11–13 s of model time over 4–6 turns, 6–14 s of ARC tool time, and about 4–5 s of omp start-up plus Chromium launch.
- **Outlier:** httpbin's 180 s in run 1 is a single model turn that took minutes on the provider side; ARC's tool time was a normal 7 s.
- **Pattern:** in every run the model called `arc_inspect` once per page (plus one `query` on the Python docs, whose target link was evicted from the truncated tree) and then acted on the trees `arc_act` returned.

**What the model runs exposed and fixed** (before these two runs):
- **Stale trees after client-side navigation.** On GitHub the model clicked the right `[#19] link "Issues 159"`, but the tree `arc_act` returned was still the repository page: GitHub changes the URL before it renders, and network idle doesn't reset for in-page navigations.
  - Before the fix, one run fell back to typing the URL with `goto`, and another spent 10 calls re-querying.
  - `arc_act` now waits briefly for a clicked link to change the URL, then polls until the tree differs from the post-click snapshot and holds steady for two reads.
  - GitHub now takes 3 calls in both runs.

For scale, Browser Use's Jev reports a Google Flights search in 7.1 s, with one model call choosing both the operation and the element. ARC with a general chat model needs one model turn per action (2–3 s each here) plus ARC's own settle waits. Those are the two gaps.

## Part D — reflex policy: one model call per action

Part C's agent loop paid for a general coding agent on every step: about 20k input tokens per turn, prose before each tool call, and chat history. `arc_cua.reflex_policy` is the Jev-style alternative:
- **Input:** each step sends one direct chat-completions request with the goal, ARC's current tree (≤ ~1,200 tokens) and the last 4 actions (each naming the element it hit and whether the page changed).
- **Output:** exactly one JSON action, such as `{"op":"click","index":19}`, about 9 output tokens.
- **ARC side:** `arc_act` returns the next tree, so each step is one model call plus one ARC action.

Setup and scoring:
- **Tasks:** the same 7 tasks plus **Google Flights**: one-way Zurich → London on 2026-10-20, the task Browser Use's Jev times at 7.1 s. Flights passes only if the results URL's `tfs` parameter encodes that date and the Freebase ids of Zürich (`/m/08966`) and London (`/m/04jpl`).
- **Browser:** local headless Chromium, kept warm across tasks.
- **Scoring:** a run where the model itself gives up never counts.
- **Artifacts:** `artifacts/benchmarks/reflex_policy_20260927-{044804,045518,045016}`. Script: `scripts/benchmark_reflex_policy.py`.

| Model (endpoint) | Success | Median s / task | Median s / decision | Google Flights |
|---|:-:|---:|---:|---|
| `gemini-3.8-flash` (Gemini API, thinking off) | **24/24** | 9.4 | 1.57 | ✅✅✅ 26.7 / 27.0 / 28.6 s |
| `gemini-3.5-flash-lite` (Gemini API, minimal thinking) | 22/24 | **7.9** | **0.89** | ✅✅✅ 15.8 / 21.1 / 21.5 s |
| `deepseek-v4-1-flash` (Kenari, 1 run) | 7/8 | 9.8 | 1.47 | ✅ 27.9 s |

- **Against Part C:** median task time fell from about 25 s to 8–9 s.
  - Part C carried about 20k tokens and prose per turn; Part D sends about 1.5k tokens in and gets about 9 tokens out.
  - Part D also runs on a warm browser, where Part C paid 4–5 s of start-up per task.
  - The Flights task wasn't in Part C.
- **Against Jev (7.1 s on Google Flights):** not beaten. The best run was 15.8 s.
  - **Model time:** Flash-Lite spends about 6 s on 7 decisions of 0.7–1.1 s each.
  - **ARC time:** about 8–13 s. That is now the larger share. Google Flights' tree is large and changes constantly, and each action reads it again.
  - Cutting ARC's settle budget from 3 s to 1.5 s didn't change the Flights time, so the cost is the reads themselves.
  - Jev's structural advantage is a model trained to pick operation and element directly, plus speculative fan-out.
- **Failures:**
  - Flash-Lite's 2 misses and DeepSeek's miss were all on "click the second 'N comments' link": the model clicked the right link (`#24`) but didn't recognise it was done. Adding the clicked element's name and the new URL to the history helped Gemini 3.8 Flash (3/3) but not Flash-Lite.
- **Models ruled out:**
  - `gemma-4-26b-a4b-it` (Gemini API) looped on the same click, then hit the free-tier rate limit.
  - The free Kenari models (`laguna-xs-2-1`, `glm-4-7-flash`) failed mostly on `429`/`503`; `agnes-3-0-flash` passed 7/8 but took 1–40 s per decision.
  - Kenari's paid fast models measured 1.3–2.8 s per decision in a latency probe, slower than Gemini direct.

## Part E — same model, two harnesses

Part D's comparison against Opus changed the model and the harness at once. Here the model is held fixed: **Gemini 3.8 Flash** (thinking off) drives a Solari browser either through Solari's own MCP or through ARC.
- **Solari MCP side:** a standard tool-calling agent (`scripts/benchmark_gemini_solari_mcp.py`). The model gets Solari's six page tools (`navigate`, `read_page`, `click`, `type`, `key`, `evaluate`) as functions, keeps the whole conversation, and works until it answers DONE. The harness injects the Solari `sessionId`, so the model provider never sees it.
- **ARC side:** the reflex policy from Part D, on the Solari backend (`reflex_policy_20260927-062541`).
- **Both:** the same 8 tasks, 3 runs each, one warm Solari browser, the start page opened by the harness inside the timed window, and the same `judge` (the `tfs` check for Flights).
- **Artifacts:** `artifacts/benchmarks/gemini_solari_mcp_20260927-144808.json`. Video: `artifacts/gemini-harness-showreel.mp4` (`media/showreel`, variant `gemini`).

| Task (median of 3) | Solari MCP | ARC |
|---|---:|---:|
| HN: click "new" | **8.4 s** | 10.6 s |
| HN: 2nd comments link | **9.8 s** | 10.5 s |
| Wikipedia: search | 51.8 s | **28.7 s** |
| httpbin: fill + submit | 23.6 s | **21.4 s** |
| GitHub: Issues tab | **14.2 s** | 15.9 s |
| Python docs: follow link | **11.1 s** | 12.8 s |
| TodoMVC: add item | 14.8 s | **10.7 s** |
| Google Flights | ❌ 0/3 | ✅ 3/3, 61.3 s |
| **Success** | 21/24 | **24/24** |
| **Sum of medians, 7 tasks both pass** | 133.7 s | **110.6 s** (1.2×) |
| **Input tokens, 24 runs** | 458,546 | **122,034** (3.8×) |
| **Output tokens, 24 runs** | 5,354 | **762** |
| **Model + browser, per 1,000 tasks** | $16.01 | **$4.84** (3.3×) |

- **Speed is close on simple pages.** The tool-calling agent often clicks a guessed CSS selector without reading the page, which wins 4 of the 7 simple tasks by 0.7–2.2 s. ARC wins overall on the pages where reading matters: Wikipedia's search took the Solari MCP agent 13 turns.
- **Google Flights failed on all 3 Solari MCP runs.** Twice it navigated to a `?q=` text-search URL instead of filling the form; once it spent all 20 turns on the "Where from?" autocomplete, mostly probing the DOM with `evaluate`. ARC completed it every time, at 61 s.
- **Tokens:** the tool-calling agent resends tool schemas, every page read and the full history on each turn (up to 131k tokens on one Flights run). ARC sends the goal, one budgeted tree and the last 4 actions.
- **Cost** uses Gemini 3.8 Flash's $0.75 / $3.75 per 1M tokens and Solari's $0.15 per browser-hour.

## Caveats

- **Parts A and B are scripted policies, not agents.** I wrote both policies. The Solari side assumes an agent that can parse HTML and pick the right link among duplicates. The token and CDP counts are what each tool *hands* the agent or sends to the browser, which holds regardless of the policy.
- **Part C is one model, two runs per task.** It ran on a local browser, not Solari, and success was judged from the agent's own tool results (the last URL or tree ARC reported).
- **Small sample:** 8 pages and 7 tasks on public sites that change daily.
- **Solari `text` is the cheapest read on most pages,** but it carries no handles. An agent that only needs to *read* content should use it.
- **ARC on MDN kept 39 of 1,522 affordances visible.** On very large pages the agent relies on `arc_inspect(query=…)` to reach the rest.
