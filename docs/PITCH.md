# The Pitch

> This is the strategic reasoning behind ColdStart — the "why this, why me" that a resume can't convey.

---

## The hiring test decoded

Pinetree's challenge wasn't "build something cool with Solari." It was:

> **Show us you understand what we actually care about, and ship it fast.**

The test filters for:
- **Independence** — no hand-holding, no roadmap handed to you
- **First-principles thinking** — read the mission, infer the gap
- **Judgment** — build the *right* thing, not the most features
- **Execution** — ship working code, not a proposal

---

## What everyone else built

I scanned all 13 public challenge forks before writing a single line of code:

| Theme | # of applicants | Examples |
|-------|-----------------|----------|
| Reliability-CI / verify-the-outcome / audit | ~6 + 4 PRs | `receipts`, `agent-gauntlet`, `agent-ready`, PRs #16/#20/#4 |
| Stealth / captcha / residential proxies | ~7 | `agent-ready`, `cascade`, `hotel-california`, `brief`, `apply-lens` |
| Cost-aware surface routing | 1 | `cascade` |
| Voice agents | 2 | `solari-voice-agent` |
| Vertical workflows | 2 | healthcare RCM, subscription-cancel |
| **Zero-shot generalization / unseen environments** | **0** | — |

The most crowded cluster was **verification/reliability** — the thing my first proposal ("Witness") targeted. I caught this before building, pivoted, and found the open gap.

---

## Why ColdStart

Pinetree's entire public identity is **zero-shot generalization**:

> 93% on Hallucinate Westworld — a fully-unseen environment — with no prior exposure, beating Yutori (86%) which *was RL-trained on that exact environment*.

Their research page says the moat is **vision-first + true generalization**. Nobody in the applicant field had built tooling to measure that.

**ColdStart operationalizes the claim Pinetree actually makes:**

- Not "is the agent reliable on a known app?" — that's the crowded cluster
- **"Does the agent generalize to an app it has never seen?"** — Pinetree's crown jewel

---

## What ColdStart proves

| What it tests | How it works | What we learned |
|---------------|--------------|-----------------|
| **Surface variation** | Relabel every field, re-theme the entire app | Agent generalizes (P1, P5 pass) |
| **Procedural change** | Split the form into a two-step wizard | Agent breaks (P2 fails 0/2) |
| **Ground truth** | Read SQLite directly, recompute expected values | Fail-closed verification works |
| **Vision-first honesty** | No DOM, no selectors, no accessibility tree | The P5 theme control proves it |

**The insight:** *Recognizing every element is not the same as knowing the order of operations.* This is a genuine, measurable finding that would matter to Pinetree's research.

---

## Why this uses Solari's superpower correctly

Every competitor used sandboxes for **verification/CI**. ColdStart uses **snapshot → fork** to spin up **N fresh, isolated, unseen environment variants in ~1s each**:

- **Procedural environment generation** — the exact primitive that makes this cheap and reproducible
- Nobody else touched this use of the Solari API
- Worldline (PR #20) branched *plans*; ColdStart branches *environments*

---

## What I'd build next

1. **More task templates** — expand beyond Create-Invoice to ticket filing, address updates, data reconciliation
2. **Desktop variants** — test generalization to native GUI apps, not just web
3. **Model comparison** — run the same variant matrix across multiple vision-capable models
4. **Procedural hardness dial** — generate variants along a continuous novelty axis instead of discrete points
5. **🧠 Cost-Optimized Multi-Model Evaluation Pipeline (The "Slop-Catcher" Router)** — decouple action from perception: use high-speed VLMs (Gemini 1.5 Flash / GPT-4o) to catch UX "slop" for &lt; $0.002, gate adversarial agent-vs-agent red teaming (Claude 3.5 vs. UI-TARS / GPT-5.6 Luna) to UI diffs, and save 95% compute in CI/CD.
6. **Continuous benchmark for Pinetree Agent** — wire directly into CI leaderboards to prevent generalization regressions on commit.

---

## The ask

> You don't want my resume — you want to know if I can close the gap you care about.
> 
> I read the mission: *intelligence is no longer the bottleneck, execution is.*
> 
> So I didn't build another agent demo. I built **ColdStart** — the tool that measures the one thing Pinetree claims that nobody else is testing: zero-shot generalization to unseen environments.
> 
> The code runs. The tests pass. The insight is real: agents that recognize every label can still fail when the order of operations changes.
> 
> I'd ship it, learn your stack fast, and contribute to Pinetree Agent's reliability story from day one.
