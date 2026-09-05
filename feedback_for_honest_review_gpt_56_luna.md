# Response to `muse_spark_1.3_honest_feedback.md`

**Date:** 2026-09-05  
**Repository:** `solari-cookbook`  
**Status:** Remediation applied locally; no live VLM run or new causal benchmark run is claimed.

## Executive response

The review was correct about the distinction between the durable ColdStart harness and the
unverified Phase 2/3 product narrative. I have kept the benchmark, verifier, isolated-run
evidence, and Nakama findings, while relabeling the mock/prototype material and removing
unsupported outcome and economics claims.

The current repository should be read as one primary product:

> ColdStart is an evidence-backed, zero-shot generalization harness with a seeded variant
> factory, screenshot-driven agent loop, harness-side click grounding, fail-closed SQLite
> verification, and committed live-run traces.

The Slop-Catcher and QA framework material is now clearly marked as either an offline mock
prototype or dogfooding/service evidence.

## Review points addressed

### Grounding disclosure

The documentation now says **vision plus harness grounding**. The model receives screenshots
and emits pixel coordinates. `src/agent/action.ts` may use a harness-side `page.evaluate` call
to snap an imprecise click to the nearest visible interactive element. DOM text, selectors,
accessibility nodes, and element boxes are not returned to the model.

Updated references include:

- `DESIGN.md`
- `README.md`
- `PITCH.md`
- `AUDIT_LOG.md`
- `src/agent/action.ts`
- `src/agent/screenshot.ts`
- `docs/DEMO_SCRIPT.md`

### Phase 2 claims

Phase 2 is now labeled **Prototype (MOCK ONLY)**. The repository does not claim a live VLM
evaluation, a router gate, a CI triage gate, a measured per-scan price, or a measured 95%
compute reduction. `README.md`, `NEXT_STEPS.md`, `PITCH.md`, `ABOUT.md`, and the generated
HTML pages use the same disclosure.

The committed combined demo remains explicitly scripted and MOCK. Its hardcoded design
metrics are not presented as a live model judgment.

### QA framework positioning

Nakama QA is presented as dogfooding/service evidence rather than Product #3. The heuristic
module now describes itself as a deterministic UX report template. It formats findings that
are supplied by the caller; it does not inspect a page, screenshot, DOM, or application state.

### Benchmark language

The README and pitch now use measured directional language:

| Axis | Current evidence | Interpretation |
| --- | --- | --- |
| P2 structure | 0/2 raw success; 0/1 clean evidence | strongest observed breaker, directional |
| P3 field order | 1/1 clean evidence; second run infra-aborted | directional pass, small sample |
| P5 theme | 2/2 isolated | directional control result |
| P1 relabel | 1/1 mixed run at P1:4 + P3:3 | not causally isolated |
| P4 navigation | no isolated run | unverified |

The previous “100% Surface Invariance” wording has been removed. Exact rates remain soft at
`n=2`, and infrastructure aborts remain visible rather than being counted as model failures.

### Test count and repository hygiene

Documentation and badges now report the current test count: **110 passing tests**. Workspace
and nested-repository ignore files cover common editor, agent, OS cache, build, database, and
artifact directories, including `.env*` patterns. No secret file was read or added.

## Verification receipt

Command run from `solari-cookbook/`:

```text
npm run verify
```

Result:

```text
tsc -p tsconfig.json --noEmit       passed
Test Files  12 passed (12)
Tests       110 passed (110)
```

The local documentation preview also returned HTTP 200 at `http://localhost:8081/` because
port 8080 was already occupied.

## Deliberately unresolved items

These remain future work and are not represented as completed:

1. A live VLM call with a committed trace and cost envelope.
2. P1-only and P4-only causal runs at `n >= 3`.
3. Runner hardening for infrastructure-abort retry and browser rotation.
4. Generalizing the invoice verifier/agent loop to an arbitrary application and autonomously
   reproducing a Nakama finding.

The next engineering priority is runner reliability and the missing causal matrix points,
not additional products, desktop surfaces, enterprise templates, or new marketing claims.

## Bottom line

The review changed the packaging and the claims, not the core evidence. The submission now
makes the strongest defensible statement: ColdStart has a real harness and a real directional
finding about procedural change, while the perception/router and QA product narratives remain
explicitly unverified prototypes or service evidence.
