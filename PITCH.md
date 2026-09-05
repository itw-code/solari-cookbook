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

I scanned the public challenge forks before writing a single line of code (manual audit; exact counts not archived in this repo):

| Theme | # of applicants | Examples |
|-------|-----------------|----------|
| Reliability-CI / verify-the-outcome / audit | ~6 + PRs | `receipts`, `agent-gauntlet`, `agent-ready` (PR numbers from a manual scan, not archived here) |
| Stealth / captcha / residential proxies | ~7 | `agent-ready`, `cascade`, `hotel-california`, `brief`, `apply-lens` |
| Cost-aware surface routing | 1 | `cascade` |
| Voice agents | 2 | `solari-voice-agent` |
| Vertical workflows | 2 | healthcare RCM, subscription-cancel |
| **Zero-shot generalization / unseen environments** | **0** | — |

The most crowded cluster was **verification/reliability** — the thing my first proposal ("Witness") targeted. I caught this before building, pivoted, and found the open gap.

---

## Why ColdStart

Pinetree's entire public identity is **zero-shot generalization**:

> Pinetree reports a strong zero-shot result on **Hallucinate Westworld**, a fully-unseen environment, which their agent had never seen. (The specific score and the Yutori comparison that appeared in an earlier draft of this line had no linkable source; add the official links before quoting numbers.)

Their research page says the moat is **vision-first + true generalization**. Nobody in the applicant field had built tooling to measure that.

**ColdStart operationalizes the claim Pinetree actually makes:**

- Not "is the agent reliable on a known app?" — that's the crowded cluster
- **"Does the agent generalize to an app it has never seen?"** — Pinetree's crown jewel

---

## What ColdStart proves

| What it tests | How it works | What we learned |
|---------------|--------------|-----------------|
| **Surface variation** | Relabel every field, re-theme the entire app | Directional evidence: P1 1/1 mixed; P5 2/2 isolated |
| **Procedural change** | Split the form into a two-step wizard | P2 0/2 raw success; only 0/1 clean evidence |
| **Ground truth** | Read SQLite directly, recompute expected values | Fail-closed verification works |
| **Vision-first honesty** | Model sees screenshots only; harness-side click snap is disclosed | P5 is a directional control, not proof of pure no-DOM execution |

**The insight:** *Recognizing every element is not the same as knowing the order of operations.* This is a genuine, measurable finding that would matter to Pinetree's research.

---

## Why this uses Solari's superpower correctly

Every competitor used sandboxes for **verification/CI**. ColdStart uses Solari microVMs to spin up **N fresh, isolated, unseen environment variants in ~10s each (measured; the snapshot fast-fork path was best-effort in our runs and mostly 409'd, so direct provisioning is the working path)**:

- **Procedural environment generation** — the exact primitive that makes this cheap and reproducible
- Nobody else touched this use of the Solari API
- Worldline (PR #20) branched *plans*; ColdStart branches *environments*

---

## What I'd build next

1. **More task templates** — expand beyond Create-Invoice to ticket filing, address updates, data reconciliation
2. **Desktop variants** — test generalization to native GUI apps, not just web
3. **Model comparison** — run the same variant matrix across multiple vision-capable models
4. **Procedural hardness dial** — generate variants along a continuous novelty axis instead of discrete points
5. **Prototype perception routing** — validate a live VLM path and measure its cost before proposing CI/CD triage or adversarial red teaming.
6. **Continuous benchmark for Pinetree Agent** — wire directly into CI leaderboards to prevent generalization regressions on commit.

---

## The ask

> "You don't want my resume — you want to know if I can close the gap you care about.
> 
> I built **ColdStart** to measure zero-shot generalization. The Slop-Catcher is an offline mock prototype and future research direction, not a shipped product.
> 
> The ColdStart harness runs with reproducible variants, harness-side grounding, and fail-closed verification; its cost envelope is reported in observable seconds, calls, and tokens because the SDK exposes no dollar rate.
> 
> The core code runs and the tests pass. The prototype layers remain explicitly unverified. I'd ship it, learn your stack fast, and contribute to Pinetree Agent's reliability story from day one."
