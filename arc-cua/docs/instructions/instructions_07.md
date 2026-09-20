# instructions_07.md

## Context

The ARC is engineering-complete across all 6 phases (152 tests passing, final research report generated). Two final tasks remain:

1. **Codebase consolidation** — organize the accumulated checkpoint files, instruction files, and artifacts into a clean, navigable structure.
2. **HTML showcase** — build a polished, interactive single-page showcase, following the same presentation pattern used by `coldstart/`.

---

## Part A: Codebase Consolidation & Checkpoint Management

### Task A1: Inventory existing files

List all files matching:
- `checkpoint_*.md`
- `instructions_*.md`
- `DEPLOYMENT_PLAYBOOK.md`
- Everything under `artifacts/`

Print this inventory to stdout before moving anything.

### Task A2: Create a `docs/` archive structure

Create:
```text
docs/
├── checkpoints/
├── instructions/
├── architecture/
└── CHANGELOG.md
```

### Task A3: Move checkpoint and instruction files

Move all `checkpoint_*.md` files into `docs/checkpoints/`.
Move all `instructions_*.md` files into `docs/instructions/`.

Rules:
- Do NOT move `ARCHITECTURE.md`, `IMPLEMENTATION_PLAN.md`, or `README.md` — these stay at repo root.
- Do NOT move anything under `artifacts/` yet (handled in A4).
- Use `git mv` if the repo is a git repository, otherwise plain file move.
- After moving, update any internal cross-references that point to the old paths.

### Task A4: Consolidate artifacts

Current artifacts are spread across:
```text
artifacts/phase3b/
artifacts/phase4a/
artifacts/phase6/
artifacts/production/
```

Leave them in place, but create a top-level:
```text
artifacts/INDEX.md
```

This index must list every artifact file, its purpose, and which phase produced it.

### Task A5: Build `docs/CHANGELOG.md`

Create a chronological changelog summarizing all 6 phases. For each phase include:
- Phase name and objective
- Key deliverables
- Final test count
- Headline metric achieved

Use the data from the checkpoint files (do not invent numbers).

### Task A6: Create `docs/checkpoints/INDEX.md`

Create a timeline index of all checkpoints:
```text
| File | Phase | Status | Test Count | Key Metric |
```

Populate it from the actual checkpoint contents.

### Task A7: Update root `README.md`

Rewrite `README.md` to include:
- One-paragraph project summary
- Architecture diagram (copy the ASCII diagram from `ARCHITECTURE.md`)
- Quickstart commands
- Link table to `docs/` subpages
- Final benchmark headline numbers

### Task A8: Verify packaging

Check whether `pyproject.toml` or `setup.py` exists. If not, create a minimal `pyproject.toml` so the package is installable via `pip install -e .`.

Verify `.gitignore` excludes:
```text
__pycache__/
*.pyc
artifacts/
.venv/
node_modules/
```

### Task A9: Run the full test suite

Run `pytest tests/` and confirm all 152 tests still pass after file moves. If any test imports a moved file, fix the import path.

---

## Part B: HTML Showcase

### Task B1: Study the coldstart showcase pattern

Before writing any HTML, read these files to understand the presentation style:
```text
coldstart/index.html
coldstart/arc-cookbook/index.html
coldstart/arc-cookbook/docs/index.html
coldstart/arc-cookbook/docs/interactive-sections.html
coldstart/arc-cookbook/PITCH.md
research-assets/coldstart-site/index.html
```

Note the layout, section structure, and tone. Match that quality level.

### Task B2: Build the showcase HTML

Create:
```text
showcase.html
```

Requirements:
- Single self-contained HTML file. All CSS and JS inline.
- Use Tailwind CSS via CDN (`https://cdn.tailwindcss.com`).
- Use Chart.js via CDN for the cost/latency simulator.
- Dark-mode aesthetic (deep background, emerald/green accents for Arc, red/orange for baseline).
- Fully responsive.
- No external image files — use inline SVG for icons and diagrams.

### Task B3: Required showcase sections

Include these sections in order:

**1. Hero**
- Title: "ARC"
- Subtitle: the core value prop (99.7% cost reduction, sub-10ms reflex)
- Three stat cards: Cost Reduction / Latency Reduction / Test Count

**2. Architecture Diagram**
- Recreate the Reflex + Cortex cascading diagram from `ARCHITECTURE.md`
- Use inline SVG or styled divs
- Label the two tiers clearly

**3. Interactive Cost & Latency Simulator**
- A slider for "Number of UI Steps" (range 10 to 10,000)
- As the slider moves, update a Chart.js chart and stat cards comparing:
  - Frontier LLM baseline (cost grows linearly, high latency)
  - Arc Hybrid (cost stays near zero, flat latency)
- Use the real per-task cost figures from `FINAL_RESEARCH_REPORT.md`:
  - Frontier baseline: ~$0.48/task
  - Arc Hybrid: ~$0.0015/task

**4. Benchmark Results**
- Two tables: WebArena and OSWorld
- Populate with real numbers from `FINAL_RESEARCH_REPORT.md`
- Mark clearly: "PROJECTED_BASED_ON_MOCK_EXECUTION"

**5. Monitor Efficacy**
- Show the escalation prevention rates:
  - Stuck Monitor: 94.2%
  - Milestone Monitor: 98.1%
  - Session Guard: 100%
- Use simple bar visualizations

**6. Phase Timeline**
- Horizontal or vertical timeline of Phases 1 through 6
- Pull phase names and headline metrics from `docs/CHANGELOG.md`

**7. Roadmap / CTA**
- Three cards: Live Cloud Deployment / ModernBERT Fine-Tuning / Enterprise Integration
- Pulled from `FINAL_RESEARCH_REPORT.md` Section 6

### Task B4: Embed real data

Do NOT use placeholder numbers. Read from:
```text
artifacts/phase6/FINAL_RESEARCH_REPORT.md
artifacts/production/final_scorecard.json
```

If a number is projected/mock-based, keep the `PROJECTED_BASED_ON_MOCK_EXECUTION` label visible near it.

### Task B5: Validate the HTML

Open the generated `showcase.html` in a headless browser (or validate the HTML structure) and confirm:
- No broken CDN references
- The slider updates the chart
- All tables render
- No console errors

If Playwright is available, write a quick smoke test:
```text
tests/test_showcase.py
```
that loads `showcase.html` and asserts the presence of key section IDs.

---

## Definition of Done

Part A is complete when:
1. All checkpoint and instruction files are moved into `docs/`.
2. `docs/CHANGELOG.md`, `docs/checkpoints/INDEX.md`, and `artifacts/INDEX.md` exist.
3. `README.md` is updated.
4. `pyproject.toml` exists.
5. All 152 tests still pass.

Part B is complete when:
1. `showcase.html` exists and is self-contained.
2. All 7 sections are present and populated with real data.
3. The interactive simulator works.
4. A smoke test confirms the HTML renders.

---

## Required Final Output

After completing both parts, create:
```text
checkpoint_07.md
```

Format:
```markdown
# checkpoint_07.md

## 1. Part A Status
- [ ] File inventory
- [ ] docs/ structure created
- [ ] Checkpoints moved
- [ ] Instructions moved
- [ ] artifacts/INDEX.md
- [ ] CHANGELOG.md
- [ ] checkpoints/INDEX.md
- [ ] README.md updated
- [ ] pyproject.toml
- [ ] Tests pass (152)

## 2. Part B Status
- [ ] Coldstart pattern studied
- [ ] showcase.html created
- [ ] All 7 sections present
- [ ] Real data embedded
- [ ] Interactive simulator works
- [ ] Smoke test passes

## 3. Files Moved
List every file moved from root to docs/.

## 4. Files Created
List every new file.

## 5. Test Results
Confirm 152/152 passing.

## 6. Showcase Verification
Confirm showcase.html renders and the simulator updates.

## 7. Remaining Issues
List anything incomplete.
```

---

## Stop Condition

Stop after producing `checkpoint_07.md`.
Do not start any new feature work beyond consolidation and the showcase.
