# ColdStart Demo Script

> 60-90 second walkthrough for reviewers. Film with Loom, then embed in README.

---

## Opening (0-10s)

**[Screen: README header with the showcase.gif playing]**

> "This is ColdStart — a zero-shot generalization harness for computer-use agents. In the next 60 seconds, I'll show you what it does, why it matters, and what we learned."

---

## The Problem (10-25s)

**[Screen: Split view — Pinetree benchmark table vs. competitor cluster map]**

> "Pinetree's crown jewel is zero-shot generalization — their agent scores on environments it has never seen. But none of the other applicants in this hiring challenge built tooling to measure that. They all tested reliability on known apps. ColdStart tests generalization to unknown ones."

---

## How It Works (25-45s)

**[Screen: Architecture diagram, then quick cuts to code]**

> "ColdStart procedurally generates never-before-seen variants of a task app. Five perturbation axes: relabel every field, shuffle the layout, split the form into a wizard, reorder the nav, re-theme the CSS. A vision-first agent — pixels in, coordinates out — has to complete the same task cold in each variant. The harness may snap imprecise clicks to visible controls, but no DOM data is returned to the model."

**[Screen: Terminal running `npm run verify`]**

> "The verifier reads SQLite directly, recomputes ground truth from the seed, and fail-closed checks every field. No trusting the agent's narration. 37 unit tests, all offline, no API keys needed."

---

## What We Learned (45-75s)

**[Screen: Results table from README]**

> "Here's what we found. The agent generalized across surface variation — relabeling, theme changes, field reordering — all passed. But split the same form into a two-step wizard? Zero for two. It burned the entire step budget without submitting."

**[Screen: Showcase.gif again, this time paused on the POSTED confirmation]**

> "Recognizing every element is not the same as knowing the order of operations. That's a real insight that would matter to Pinetree's research."

---

## The Ask (75-90s)

**[Screen: PITCH.md or your face if recording with camera]**

> "I built the initial harness in one focused ~4-hour session after a weekend of deep competitive research and architectural design — a 48-hour total lifecycle. Polish, media, and docs followed over the next evening. The code's clean, the tests pass, and the insight is real. Thanks for watching."

---

## B-roll suggestions

- Terminal typing `npm run gen:variants` and showing `variants.json` appear
- Quick scroll through `test/*.spec.ts` showing test names
- `artifacts/scorecard.json` opened in VS Code
- The curve.png (success rate vs. perturbation intensity)
- The "where-it-breaks.md" document

---

## Thumbnail idea

**Text overlay on showcase.png:**

```
COLDSTART
Zero-Shot Generalization
for Computer-Use Agents

[▶] 60 sec demo
```
