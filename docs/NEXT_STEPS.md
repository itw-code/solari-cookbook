# Next Steps

> If hired, this is what I'd build next — extending ColdStart from a proof-of-concept to a production generalization benchmark.

---

## Immediate (Week 1-2)

### 1. Expand task templates

Currently: **Create-Invoice** (one CRUD workflow)

Add:
- **File Ticket** — multi-field form with category dropdown, priority, attachment upload
- **Update Address** — navigate to settings, find address section, update fields, verify change
- **Data Reconciliation** — compare data between two views, identify discrepancies, correct them

Each template gets the same 5-axis perturbation treatment.

### 2. Desktop variants

ColdStart currently tests web apps only. Add:

- Native GUI variants (calc.exe, notepad, file explorer)
- Cross-platform testing (Windows, macOS, Linux)
- Desktop-specific perturbations (window size, DPI scaling, theme)

This uses Solari's **desktop** surface, which most competitors ignored.

---

## Short-term (Week 3-4)

### 3. Model comparison matrix

Run the same variant set across multiple vision-capable models:

| Model | P1 (Relabel) | P2 (Structure) | P3 (Field Order) | P4 (Nav) | P5 (Theme) |
|-------|--------------|----------------|------------------|----------|------------|
| GPT-4o | ? | ? | ? | ? | ? |
| Claude 3.5 Sonnet | ? | ? | ? | ? | ? |
| Gemini 2.5 Pro | ? | ? | ? | ? | ? |
| Pinetree Agent | ? | ? | ? | ? | ? |

This produces a **comparative generalization scorecard** — valuable for Pinetree's benchmark-driven positioning.

### 4. Continuous novelty axis

Replace discrete variant points with a **continuous perturbation intensity slider**:

```
intensity: 0.0 ────────────────────────────── 1.0
           │         │         │         │
           baseline   light    medium    extreme
```

Generate the generalization curve as a smooth function, not isolated points.

---

## Medium-term (Month 2)

### 5. Integration with Pinetree Agent

Wire ColdStart as a **continuous benchmark** for Pinetree Agent:

- Run on every agent commit
- Track generalization score over time
- Alert on regressions (e.g., "P2 structure sensitivity increased")
- Publish to internal leaderboard

This makes ColdStart a **production tool**, not just a demo.

### 6. Failure mode taxonomy

From the "where it breaks" analysis, build a classifier:

| Failure Mode | Signature | Root Cause | Mitigation |
|--------------|-----------|------------|------------|
| Click-lock | Same coordinate 3+ times | Visual grounding issue | Coordinate snapping |
| Step cap burn | 40 steps, no `done` | Flow confusion | Better task decomposition |
| Premature `done` | Claims done, verifier fails | Hallucination | Stricter grounding |

This becomes a diagnostic tool for agent developers.

---

## Long-term (Month 3+)

### 7. Real-world environment sampling

Instead of procedural variants, sample from **real enterprise apps**:

- Salesforce configurations
- SAP screens
- Custom internal tools (with permission)

Measure generalization to *actual* unseen environments, not synthetic ones.

### 8. Procedural environment hardening

Use ColdStart's findings to **automatically harden** agents:

- Identify the weakest perturbation axis
- Generate adversarial variants
- Fine-tune or prompt-engineer for robustness
- Re-measure

This creates a **generalization improvement loop**.

---

## Cost projections

| Expansion | Estimated sandbox hours | Est. LLM calls | Notes |
|-----------|------------------------|----------------|-------|
| +3 task templates | ~2 hours | ~500 calls | Each template: ~8 variants × 2 reps |
| Desktop variants | ~1 hour | ~200 calls | Fewer variants, longer sessions |
| Model comparison | ~4 hours | ~1000 calls | 4 models × 5 axes × 2 reps |
| Continuous integration | ~10 hours/month | ~2000 calls/month | Ongoing benchmark |

---

## Open questions

1. **What's the right n?** Current n=2 per isolated point. Statistical significance requires more, but cost scales linearly. Multi-arm bandit sampling could help.

2. **Is P2 universally hard?** The two-step wizard broke this agent. Does it break all agents? Or is this model-specific?

3. **What's the ceiling?** ColdStart measures *where* agents break. What's the theoretical maximum generalization score? Can we approach it?

4. **How does this relate to WebVoyager/Mind2Web?** Those benchmarks test live sites. ColdStart tests synthetic variants. What's the correlation?

---

## The vision

ColdStart becomes:

> **The benchmark that proves Pinetree's core claim.**
> 
> Every time Pinetree Agent ships, ColdStart runs. Every time a competitor releases a model, ColdStart compares. Every time the research community debates "generalization," ColdStart provides the measurement.
> 
> It's not just a demo — it's the infrastructure that keeps Pinetree's thesis honest.
