# SWE Intern @ Pinetree Research — Research-Backed Proposal

> Goal: get hired as a $300K SWE Intern. The hiring test is **not** a resume — it's
> "fork the Solari repo and build a real use case with Solari (browsers, sandboxes, and/or…)".
> This doc decodes the company, the founder's real interests, the live market trend,
> what every other applicant is submitting, and the one idea that beats them all.

---

## 0. TL;DR — the pitch in 3 sentences

Pinetree's whole thesis is **"intelligence is no longer the bottleneck. Execution is."**
So the single most valuable thing you can hand them is not *another* demo agent —
it's **the reliability primitive** that proves an agent did the right thing and didn't
escape its box. I'll build **Witness**: a self-verifying, snapshot-branching computer-use
runtime on Solari that (1) runs the agent in an isolated sandbox, (2) lets it *speculate*
by forking a snapshot, (3) **independently verifies the real-world outcome** (not just
"HTTP 200"), and (4) emits an auditable, replayable evidence packet. It uses **all three**
Solari surfaces (browser + sandbox + desktop), it is **exactly** what Solari's own issue
#20 / #16 / #4 / #14 are asking for, and it is **the live, top-of-mind trend** this month
(agent sandbox-escape + silent-failure reliability).

---

## 1. The company — who you're actually applying to

- **Pinetree Research** — [pinetree-research.com](https://pinetree-research.com). An AI
  research lab headquartered in **Palo Alto**. Small, highly technical, "focused on shipping
  quickly." Runs the research/benchmark org on X as **[@Pinetree_AI](https://x.com/Pinetree_AI)**.
- **Mission:** *"close the gap between thinking and doing."* Their own framing:
  *"Intelligence is no longer the bottleneck. **Execution is.**"* They call agents
  **"the Execution Layer for AI."**
- **What they build:** browser/computer-use agents that operate software *the way humans do* —
  "through browsers, portals, desktop interfaces, and systems **with no APIs**." The target is
  the enterprise reality of dashboards, internal tools, and legacy systems full of clicking.

### Their product: **Pinetree Agent** (frontier benchmark results)

| Benchmark | Pinetree Agent | Peers (for context) |
| --- | --- | --- |
| **WebVoyager** (600+ real tasks, 15 live sites) | **99%** | prior SOTA ~97% |
| **Online-Mind2Web** | **90%** | OpenAI Lux 83.6%, Yutori Navigator 78.7%, Gemini 2.5 CUA 69% |
| **Hallucinate Westworld** (unseen env, zero-shot) | **93%** | Yutori 86% *(RL-trained on the env)*, Claude Sonnet 4.5 67.7%, Gemini 2.5 Pro 54%, OpenAGI Lux 40% |

**What the benchmarks reveal about their obsession:**
- **Vision-first** — they explicitly reject protocol/API and text/HTML approaches. *"We take a
  pure vision approach, where agents interact through the screen, keyboard, and mouse."*
- **Zero-shot generalization** beats competitors that are *trained on the environment* (Yutori).
- **Hallucination resistance / "true generalization"** is the crown jewel (Hallucinate Westworld).

**Company values** (from their careers page): think from first principles, build what lasts,
embrace your weaknesses, thrive through growth, **keep it simple — the best solution is often the simplest.**

---

## 2. Decode the hiring post — what the test actually measures

The post: **$300K annualized, no resume, no cover letter, no grades.** Steps:

1. Fork the Solari repo (`solari-sdk/solari-cookbook`, link via `t.co/TxbSy4v2XQ`).
2. Build a real use case with Solari (browsers, sandboxes, **and/or** desktops).

**This is a deliberate, minimal signal test.** They are not filtering on credentials — they are
filtering on: *independence, first-principles thinking, the ability to ship real code against a
real product, and judgment about what's actually useful.* They want people who can close
*their* gap (thinking → doing). So the best submission is the one that *demonstrates reliable
execution*, not the one with the most features.

---

## 3. The founder's real interests (in their own words)

Synthesized from the company's mission/research pages and the products they ship:

- **Execution = the bottleneck.** They are obsessed with agents that **complete tasks reliably in
  production**, not just "understand" them.
- **Reliability, auditability, scale** — stated explicitly as the enterprise requirements.
- **Operating software humans use** — no clean APIs, no ideal integrations; work through the GUI.
- **Verification & evidence** — "auditability" and "reliable execution."
- **A "small, ships fast, keep it simple" engineering culture.**
- **Solari** (stealth cloud browser, microVM sandboxes, VNC desktops) is *their* infra — the
  execution substrate for the vision-first agent.

---

## 4. What's hot right now — the last-30-days trend that validates the idea

I ran the `last30days` research engine on **computer-use agents** and on **agent security /
sandbox isolation**. The community signal for the last 30 days is unmistakable:

- **"Meta Security Researcher's AI Agent Accidentally Deleted Her Emails"** — Hacker News,
  59 pts / 61 cmts. Real-world *agent did the wrong thing*.
- **"The Hugging Face Incident Is Not an AI Story"** — r/cybersecurity, 530 pts / 50 cmts.
- **"Can AI Improve Itself? RSI"** — r/MachineLearning: *"An OpenAI eval agent escaped its
  sandbox and broke into Hugging Face… to grab test solutions."* **Sandbox-escape is the threat
  of the moment.**
- **"Dataset: AI agent security failures, 1000 incidents classified"** (Hugging Face) — people
  are *literally building a taxonomy of agent failure modes*.
- **"Bounded Agents: Delegation Security for Multi-Agent AI Systems"** (arXiv 2608.15888).
- **"Wasmer SDK – Local Sandboxes for AI Agents"** (Show HN) — everyone is racing to sandbox agents.
- **"AC2 Protocol: The missing security layer for AI agents"** — the market wants a security layer.

**Three words dominate: sandbox isolation, verification, and silent-failure reliability.**
That is *precisely* the white space for a "reliable execution layer" company, and exactly where
a differentiated intern submission should live.

---

## 5. Competitive map — what other applicants already submitted (and the gap)

I scanned GitHub for other "Pinetree Research challenge" forks. Everyone built something real,
which raises the bar — but none of them built the thing Pinetree actually sells:

| Applicant / repo | Approach |
| --- | --- |
| `GentechLabs/solari-cookbook` | x402 pay-per-scrape (crypto micropayments per scrape) |
| `EXO-Robotics/solari-agent-arena` | Embodied robot agent benchmark, deterministic MuJoCo replay + SHA-256 evidence |
| `Muhammad-AbdullahGhani/solari-voice-agent` | Voice-directed computer-use agent + live "War Room" observability |
| `EXO-Robotics/smartcart-solari` | Agentic shopping with provenance + dynamic-programming basket optimization |
| `devAkatyal/solari_security_scanner` | Security scanner (Semgrep) in a sandbox |
| `DhruvDS2/solari-cookbook` | DAG-based web-agent eval harness |
| `psjuan97/solari-db-pr-reviewer` | DB PR reviewer |
| `skyf0xx/solari-scan` | Runtime behavior (network + FS) of a GitHub PR |

**Two patterns:** (a) everyone leans *scrape / benchmark / voice / scan* — the "consume the world"
side; (b) almost no one built the **reliability/verification/audit primitive** that is Pinetree's
actual mission and the market's biggest open wound. The standout competitor (`solari-agent-arena`)
only does deterministic verification for *robots* — nobody does it for *enterprise computer-use*.

**The gap:** *A deployable runtime that proves a computer-use agent did the right thing, in a way
an enterprise can audit, and in a way that detects silent failure + sandbox escape.*

---

## 6. ✅ Recommended project — **Witness**

> *A self-verifying, snapshot-branching computer-use runtime for reliable execution on Solari.*

### The one-line pitch

**Pinetree already beats the field on hallucination at the model level (Hallucinate Westworld).
Witness is the missing *infrastructure* half: it makes unreliable agent runs auditable, and it
catches the silent wrong-step and the sandbox escape that kill enterprise trust.**

### What it does (end-to-end)

1. **Act** — a vision-first agent drives a real, awkward, *no-API* task on a **Solari cloud browser**
   or **Solari desktop** (e.g., submit a multi-step form in an enterprise portal / reconcile data
   between two systems). Every action is logged.
2. **Speculate** (implements Solari **issue #20 "Worldline"**) — before committing, snapshot the
   state, **branch** into isolated clones, and run the top competing plans *in parallel* sandboxes.
   Judge the artifacts **outside** the call.
3. **Verify independently** (implements **issue #4 "form-delivery-check"** and **issue #16
   "verified agent runtime"**) — a separate verifier re-runs the *critical* action deterministically
   in a fresh sandbox and checks **the real-world outcome**, not "HTTP 200" (did the lead actually
   land? did the record actually write?). This is the "verify the lead arrived, not just the 200" idea.
4. **Bound it & prove no escape** (addresses the sandbox-escape trend) — the agent runs in an
   isolated microVM; `Witness` captures a **trust boundary report**: which ports/FS/network the
   agent touched, what exited the box, and whether the observed behavior stayed inside bounds.
5. **Emit an audit packet** — replayable session recording + per-step screenshots + hashes +
   the verification result + a **reliability score**. Enterprise-grade, for compliance.

### Why it's a strong use of *all three* Solari surfaces

The tweet says "browsers, sandboxes, **and/or**." `Witness` deliberately composes them — which
is something the cookbook templates *don't* show and the team explicitly wants more of
(**issues #8, #6, #11** all ask for composed multi-surface examples):
- **Browser** = act in the real world.
- **Sandbox** = isolate + deterministically replay + fork (snapshot).
- **Desktop** = the no-API GUI case (the true enterprise frontier).

### Concrete scope (keep it simple — their value)

- A real task on a real, annoying site/portal (not a toy page). **Form submission with a verified
  delivery check** is the perfect first demo.
- A tiny verifier that re-runs and asserts the outcome.
- A snapshot-branch "speculative execution" module (2 competing plans).
- An audit packet exporter (JSON + screenshots + replay).
- Clean `README` + a demo GIF/video. **One idea, done well** — matching the cookbook's own ethos.

### Why this wins

1. **It's the company's thesis in code** — "reliable execution," "auditability," "scale."
2. **It directly answers their own issue tracker** — #20 (branch), #16 (verified runtime),
   #4 (verify real outcome), #14 (pay-on-pass evidence), #10 (verifiable benchmark).
3. **It hits the live trend** — sandbox-escape + silent-failure + verification (last 30 days).
4. **It's differentiated** — no competitor built the reliability/audit primitive for *computer-use*.
5. **It composes all three surfaces** — proving control of their whole stack, not one API.
6. **It shows first-principles judgment** — you read their mission and built the missing piece,
   which is exactly the signal the post is filtering for.

---

## 7. Two alternative strong ideas (backup / to show range)

**A. `ghostspec` (Solari issue #9) — "English in, verified test out."**
Describe a user flow in plain English; `Witness` opens your app in a Solari cloud browser, performs
the flow, and generates a Playwright test that **verifiably passes**. Natural-language → self-verifying
browser test. Client-side of "reliability," extremely demoable, browser-only (leaner than the primary).

**B. `pulse` (Solari issue #10) — a live, *verifiable* benchmark of Solari browsers, sandboxes, and
desktops.** Continuous measurement of the three surfaces' reliability/latency, with replay-able evidence.
Very on-mission ("reliability at scale"), mostly sandbox + browser + desktop observability.

_Recommended order: Witness (primary) → ghostspec (backup)._

---

## 8. The "sell" — why this is the winning submission

- **You're solving a problem they already stated**, not inventing one you hope they like. That's the
  strongest possible signal to a first-principles founder.
- **You're meeting the market where it's going** — the last 30 days of Hacker News/Reddit are
  consumed by agent sandbox-escape and silent-failure. If you ship the *antidote*, you're one step
  ahead of the discourse.
- **You control the whole stack** (browser + sandbox + desktop), which is more impressive than a
  single-surface script and directly satisfies "and/or."
- **You ship evidence.** A run that produces an auditable proof is more persuasive than a README
  that claims "it works." Show, don't tell — and *this* project is literally about showing.

---

## 9. The pitch / "why choose me" (adapt to your real background)

Pinetree says they want people who *think from first principles, ship fast, and keep it simple.*
Frame yourself with those exact values:

> "You don't want my resume — you want to know if I can close the gap you care about. I read the
> mission — *intelligence is no longer the bottleneck, execution is.* So I didn't build another
> agent demo. I built **Witness**, the thing reliable execution is missing: a runtime that forks a
> snapshot, runs competing plans in isolated Solari clones, **independently verifies the
> real-world outcome**, and emits an audit packet an enterprise can trust — all while proving the
> agent never escaped the box. That's the trend the whole field is arguing about right now, and
> it's exactly the 'execution layer' you're building. I'd ship it, learn your stack fast, and
> contribute to Pinetree Agent's reliability story from day one."

**Execution plan (what you'll actually do next):**
1. Clone `solari-sdk/solari-cookbook` into your own fork (done via `t.co/TxbSy4v2XQ`).
2. Get a `slr_live_` key at `console.getsolari.com` (free Starter plan = $3 credits).
3. Build the **form-delivery-check** path first (small, real, verifiable) — act on browser, verify in sandbox.
4. Add **snapshot-branch** (fork 2 competing plans, judge outside the box).
5. Add the **audit packet** exporter (replay + hashes + reliability score).
6. Write a crisp README + a 30–60s screen recording. Keep it **small and done**, per their values.

---

## Appendix A — `last30days` evidence (pass-through footers, saved to this folder)

**Run 1 — "computer use agents"** (GitHub/HN/Reddit; `last30days_cua.txt`):
```
✅ All agents reported back!
├─ 🟠 Reddit: 3 threads │ 2,479 upvotes │ 398 comments
├─ 🟡 HN: 4 storys │ 33 points │ 8 comments
├─ 🐙 GitHub: 1 item │ 132 stars │ 18 comments
├─ 🗣️ Top voices: r/OpenAI, r/LocalLLaMA, r/artificial
└─ 📎 Raw results saved to ~/Projects/Research - General/last30days_cua.txt
```
Key signal: *"Scaling Agents for Computer Use"* (OpenReview), *"Run Minecraft in a Windows sandbox
for computer use agents"* (cua.ai), and the `solari-sdk/solari-cookbook` repo surfaced as a live,
132-star project with **18 open issues**.

**Run 2 — "AI agent security sandbox isolation verification"** (`last30days_security.txt`):
```
✅ All agents reported back!
├─ 🟠 Reddit: 6 threads │ 3,695 upvotes │ 733 comments
├─ 🟡 HN: 6 storys │ 89 points │ 77 comments
├─ 🗣️ Top voices: r/artificial, r/cybersecurity, r/MachineLearning
└─ 📎 Raw results saved to ~/Projects/Research - General/last30days_security.txt
```
Key signal: Meta's agent deleted her emails (59 pts / 61 cmts); an OpenAI eval agent **escaped its
sandbox** into Hugging Face; a Hugging Face dataset of **1,000 classified agent-security failures**;
**"Bounded Agents: Delegation Security for Multi-Agent AI Systems"** (arXiv); **Wasmer local
sandboxes for AI agents** (Show HN); **AC2 Protocol — "the missing security layer for AI agents."**

## Appendix B — Sources consulted

- X post: `x.com/harrychow_/status/2094437473912844480` (hiring signal)
- Company: `pinetree-research.com` (about / research / blog / careers)
- Product docs: `docs.getsolari.com` (browser / sandbox / desktop / pricing / quickstart)
- Changelog: `changelog.getsolari.com` (single API key + Go/Rust/C++ SDKs + MCP server)
- GitHub: `solari-sdk/solari-cookbook` (repo + all open issues), plus public challenge forks
- `last30days` engine runs (saved locally): `last30days_cua.txt`, `last30days_security.txt`
