# SWE Intern @ Pinetree Research — v2 (audited & corrected)

> This supersedes the v1 "Witness" proposal. v1 failed an audit: the ideas it
> leaned on (Solari "issues" #20/#16/#4/#9/#12/#14) turned out to be **other
> applicants' already-submitted PRs**, and the "verification/reliability" cluster
> is the most crowded part of the field. This v2 replaces it with a validated,
> uncrowded, on-mission idea.

---

## 1. Audit verdict on v1 "Witness"

**Verdict: REJECT / pivot.** Three independent problems:

| v1 claim | Audit finding |
| --- | --- |
| "Solari's issue tracker is *asking for* snapshot-branching / verified-runtime / form-delivery-check" | **False.** Those "issues" (#20 Worldline, #16 Verified Agent Runtime, #4 form-delivery-check, #9 ghostspec, #12, #14) are `pull_request: YES` from authors with `author_association: NONE` — i.e., **they are competitor submissions**. Recommending them = copying other applicants. |
| "Verification / audit primitive is the white space" | **False — it's the most crowded cluster.** `dshak1/receipts` ("Reliability CI… verify every outcome"), `Konuktor/agent-gauntlet` ("crash-test your browser agent"), `Nishant27-2006/agent-ready` (agent-usability scoring), plus PRs #16/#20/#4 all live there. "Witness" would be the ~6th entry. |
| "Lean on Solari's stealth moat — nobody uses it" | **Overstated.** 7 of 13 challenge repos already touch stealth/captcha/proxy (`agent-ready`, `cascade`, `hotel-california`, `brief`, `apply-lens`, `GentechLabs`, `ideascape`). Not differentiating. |

**Lesson:** the first pass mistook *competitor PRs* for *the team's roadmap* and picked the
single most-crowded theme. The fix is to find the theme that is **(a) central to Pinetree's
identity and (b) touched by zero applicants.**

---

## 2. The validated gap (the whole argument in one scan)

I scanned all 13 challenge submissions' READMEs for the concepts that define Pinetree's
differentiation:

| Theme | # of 13 submissions touching it | Verdict |
| --- | --- | --- |
| Reliability-CI / verify-the-outcome / audit | ~6 (+4 PRs) | **Crowded** — avoid |
| Stealth / captcha / residential proxies | ~7 | **Crowded** — avoid |
| Cost-aware surface routing (`cascade`) | 1 | taken |
| Voice agents | 2 | taken |
| Vertical workflow (healthcare RCM, subscription-cancel) | 2 | taken |
| **Zero-shot / generalization / unseen env / distribution-shift** | **0** | ✅ **OPEN — and it is Pinetree's crown jewel** |

Pinetree's entire public identity is *zero-shot generalization*: **93% on Hallucinate
Westworld — a fully-unseen environment — with no prior exposure**, beating Yutori (86%)
which *was RL-trained on that exact environment*. Their research page says the moat is
vision-first + "true generalization." **Nobody in the applicant field demonstrated,
measured, or built tooling for that.** That's the gap.

---

## 3. ✅ The better idea — **ColdStart**

> *"They test whether your agent is reliable on sites it knows.
> ColdStart tests whether it's reliable on software it's never seen — which is the
> only thing Pinetree actually claims. It's Hallucinate Westworld as an engineering tool."*

### One-line pitch

A harness that **procedurally generates never-before-seen versions of a real task app**,
has a vision-first agent complete the *same* task in each one **cold** (zero prior exposure),
verifies the outcome against ground truth, and emits a **generalization scorecard** —
a success-vs-novelty curve showing exactly which UI changes break the agent.

### Why this is the right move

- **It is Pinetree's thesis, operationalized.** A founder whose identity is "we generalize
  zero-shot and we prove it on benchmarks" immediately reads ColdStart as fluent in their
  worldview — and *useful to them*, not just a demo.
- **Validated uncrowded** — 0/13 applicants, 0 of the competing PRs.
- **Uses Solari's superpower differently.** Every competitor used sandboxes for *verification/CI*.
  ColdStart uses **snapshot → fork** to spin up **N fresh, isolated, unseen environment variants
  in ~1s each** — procedural *environment generation*, which is the exact primitive that makes
  this cheap and reproducible, and which nobody else touched. (Worldline branched *plans*; ColdStart
  branches *environments* — a different, novel use of the same API.)
- **Ground-truth verification is free and airtight.** Because I generate the app, I know whether
  the invoice/ticket/record was *actually* created correctly — checked via the filesystem/DB
  channel, never the agent's narration. (Borrows the one good idea from PR #20 without copying it.)
- **Produces a benchmark artifact.** Pinetree is leaderboard-driven; a "generalization curve" is
  literally the shape of their marketing (WebVoyager 99%, Mind2Web 90%, Westworld 93%).

### What gets built (concrete, demoable)

1. **A tiny task app with a "perturbation dial."** One small CRUD app (e.g., create-invoice,
   file-ticket, update-address) that can be re-rendered with randomized: layout, button/field
   labels, nav order, CSS framework, theme, and copy. Served from inside a Solari sandbox via
   `previewUrl`. This is the "unseen environment factory."
2. **Seeded variant matrix.** Generate ~3 task templates × ~8–10 variants each, each seeded and
   reproducible, each booted from a base snapshot (fast forks).
3. **A minimal vision-first agent loop.** screenshot → action (click/type/nav) via Solari
   browser/desktop — no per-variant scripting, no DOM selectors (stays true to Pinetree's
   vision-first doctrine).
4. **A programmatic verifier.** Query the app's DB/files in the sandbox to confirm the real
   outcome (invoice exists with correct fields), independent of what the agent "said."
5. **The scorecard.** success-rate per perturbation axis (relabeling vs. layout vs. flow-reorder),
   a generalization curve, per-run replay links, and a short **"where it breaks" report** —
   the genuinely useful artifact.

### Why it beats the field (and beats v1)

- vs. `receipts` / `agent-gauntlet` / `agent-ready` / #16 / #4: they test **repeatability on a
  known app**. ColdStart tests **generalization to unseen apps** — the claim Pinetree actually makes.
- vs. the stealth/proxy cluster: that's plumbing everyone used. ColdStart is a *measurement +
  hardening* tool for the company's core research claim.
- It naturally shows **browser + sandbox (+ desktop for the GUI-app variant)** — the post's "and/or" —
  with snapshots as the star, not an afterthought.

### Scope control (their value: "keep it simple")

Start with **one** task app + ~8 variants + one agent + the verifier + scorecard. That's a
complete, runnable, impressive submission. The multi-template and desktop variants are stretch.

---

## 4. Backup idea (if you want a more "product" flavor)

**`apply-lens`-style "truth-check," but for the *agent-readiness* of a real site:** point a
vision-first agent at a real, awkward no-API portal and produce a "can this be automated
zero-shot, and where does it break" report. — *Weaker:* drifts toward the crowded
agent-readiness/scoring cluster (`agent-ready`, `apply-lens`). Keep **ColdStart** as primary.

---

## 5. The pitch / why-you (updated)

> "You don't want my resume — you want to know if I get the problem you actually work on. Your
> whole thesis is that generalization is the moat: 93% on Hallucinate Westworld, on an environment
> you'd never seen, beating models that were *trained on it*. Everyone else in this challenge
> tested whether their agent is reliable on an app it already knows. I built the opposite.
> **ColdStart** spins up never-before-seen versions of a task app in isolated Solari microVMs,
> has a vision-first agent do the real task cold, verifies the outcome against ground truth
> (not the agent's word), and gives you a generalization curve showing exactly where it breaks.
> It's the tool you'd use to keep proving — and improving — the one claim that defines Pinetree.
> I ship fast, I keep it simple, and I'd rather advance your core claim than demo another scraper."

### Execution plan
1. Fork `solari-sdk/solari-cookbook`; get a `slr_live_` key at `console.getsolari.com`.
2. Build the perturbable task app + serve it from a Solari sandbox (`previewUrl`).
3. Wire a seeded variant generator + snapshot/fork to boot N unseen variants fast.
4. Minimal vision-first agent loop (screenshot → act) with session recording.
5. Programmatic ground-truth verifier (DB/files channel).
6. Emit the generalization scorecard + a "where it breaks" report + a 60s demo video.

---

## Appendix — what changed & evidence
- **v1 "Witness" deprecated**: its three pillars mapped to competitor PRs #20/#16/#4
  (all `author_association: NONE`, `pull_request: YES`) and the crowded `receipts` /
  `agent-gauntlet` / `agent-ready` cluster.
- **Gap validation**: keyword scan of 13 challenge repos — zero use of
  zero-shot / generalization / unseen / distribution-shift.
- **Caveat (honesty):** founder-level interest is inferred from Pinetree's own artifacts
  (mission/research/blog/benchmarks). Direct X scraping of `@harrychow_` was blocked
  (Cloudflare), and the `last30days` X lane returned 0 posts in this environment — so the
  "founder interest" signal rests on the company's public thesis, which is unambiguous.
