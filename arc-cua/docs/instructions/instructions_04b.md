# instructions_04b.md

## Phase 4A Review Result

Status: PASS

Approved Phase 4A components:

- `src/arc_cua/eval/schemas.py`
- `tests/fixtures/eval_site.html`
- `src/arc_cua/eval/tasks_local.py`
- `src/arc_cua/eval/assertions.py`
- `src/arc_cua/eval/runner.py`
- `src/arc_cua/eval/cost.py`
- `src/arc_cua/eval/scorecard.py`
- `scripts/report_phase4a.py`
- `tests/test_phase4a_eval.py`

Review notes:

1. Local evaluation harness is approved.
2. Hybrid mode successfully outperformed Reflex-only (92.3% vs 46.2%).
3. Assertion engine and cost ledger are approved.
4. Phase 4B must now integrate real-world benchmark tasks.

---

## Phase 4B Mission

Build the WebArena-Verified Subset Integration.

Work in:

```text
arc-hybrid-cua/
```

Phase 4B connects the local evaluation harness to a subset of the WebArena-Verified benchmark.

Do not download or run the full WebArena Docker infrastructure if it exceeds local CI limits. Instead, build the complete harness, task mapper, and assertion adapter, and run a representative subset using mock/stubbed environment responses if the live Docker containers are unavailable.

---

## Phase 4B Scope

Allowed:

- WebArena environment adapter (Docker config or API stubs)
- WebArena task schema mapper (WebArena JSON to `EvalTask`)
- WebArena assertion adapter (URL, DB diff, string match)
- Subset task selection (10-15 representative tasks)
- WebArena eval runner integration
- Tests
- Documentation

Not allowed:

- Full OSWorld integration (Phase 4C)
- Modifying Phase 1, 2, 3, or 4A core logic
- Real Cortex calls
- Private Playwright internals

---

## Strict Rules

1. Default mode must remain offline/mock if WebArena Docker containers are not running.
2. Do not modify Phase 4A schemas; extend them if necessary.
3. Use existing `EvalRunner`, `ScorecardBuilder`, and `HybridRunner`.
4. Keep final implementation inside `arc-hybrid-cua/`.
5. Use `coldstart/arc-cookbook/` and WebArena documentation only as design references.

---

## Cross-Repo Design References

Use these only as design references:

```text
coldstart/arc-cookbook/src/qa-framework/db-diff.ts
coldstart/arc-cookbook/src/verify/checks.ts
coldstart/arc-cookbook/src/verify/verifier.ts
```

---

## Task 1: WebArena Environment Adapter

Create:

```text
src/arc_cua/eval/webarena_env.py
```

Purpose:

Manage the connection to the WebArena environment (Shopping, Reddit, GitLab, Wikipedia, Map).

Requirements:

1. Support `live` mode (connecting to actual WebArena Docker containers via URLs).
2. Support `mock` mode (returning stubbed state/responses for CI environments without Docker).
3. Provide methods to reset the environment state before a task (if live).
4. Provide methods to query the environment database (if live) or return mock DB state (if mock).

---

## Task 2: WebArena Task Schema Mapper

Create:

```text
src/arc_cua/eval/webarena_mapper.py
```

Purpose:

Convert WebArena task definitions into our internal `EvalTask` schema.

Requirements:

1. Ingest WebArena JSONL/JSON task format.
2. Map `intent`, `start_url`, and `eval_types` to `EvalTask`.
3. Map WebArena `eval_reference` to our `EvalAssertion` schema.
4. Handle unsupported evaluation types gracefully (mark as `SKIP` or `UNSUPPORTED`).

---

## Task 3: WebArena Assertion Adapter

Create:

```text
src/arc_cua/eval/webarena_assertions.py
```

Purpose:

Implement WebArena-specific evaluation logic.

Requirements:

1. `url_match`: Check if final URL matches expected pattern.
2. `string_match`: Check if specific text exists in the final DOM or API response.
3. `program_html`: Check database state or API endpoints for expected mutations (e.g., "did the post get created in the DB?").
4. Integrate with `webarena_env.py` to fetch live or mock DB state.

---

## Task 4: WebArena Subset Selection

Create:

```text
src/arc_cua/eval/tasks_webarena.py
```

Purpose:

Define a hardcoded subset of 10-15 representative WebArena tasks for testing the harness.

Requirements:

1. Include tasks from at least 3 domains (e.g., Shopping, Reddit, GitLab).
2. Include tasks with different evaluation types (`url_match`, `string_match`, `program_html`).
3. Format them as `EvalTask` objects.
4. If live WebArena is unavailable, ensure the mock environment can satisfy these specific subset tasks.

---

## Task 5: WebArena Eval Runner Integration

Update:

```text
src/arc_cua/eval/runner.py
```

Or create:

```text
src/arc_cua/eval/webarena_runner.py
```

Purpose:

Run WebArena tasks through the Hybrid Runner.

Requirements:

1. Initialize `WebArenaEnv`.
2. Reset environment state (if live).
3. Execute task via `HybridRunner`.
4. Evaluate assertions via `WebArenaAssertionAdapter`.
5. Return `EvalResult`.

---

## Task 6: Tests

Create:

```text
tests/test_phase4b_webarena.py
```

Required tests:

1. WebArena task mapper correctly parses sample JSON.
2. WebArena assertion adapter correctly evaluates `url_match`.
3. WebArena assertion adapter correctly evaluates `string_match`.
4. WebArena assertion adapter correctly evaluates `program_html` (using mock DB).
5. WebArena runner executes a mock subset task successfully.
6. WebArena runner correctly handles unsupported assertion types.
7. No external network calls occur in mock mode.

---

## Task 7: Documentation

Update:

```text
ARCHITECTURE.md
IMPLEMENTATION_PLAN.md
```

Add:

1. Phase 4B WebArena integration design.
2. Task mapping strategy.
3. Assertion adapter logic.
4. Mock vs Live environment policy.

---

## Definition of Done

Phase 4B is complete only if:

1. WebArena environment adapter exists.
2. WebArena task mapper exists.
3. WebArena assertion adapter exists.
4. Subset task selection exists.
5. WebArena runner integration exists.
6. Tests pass in mock mode.
7. Documentation is updated.

---

## Required Final Output

After completing Phase 4B, create:

```text
checkpoint_04b.md
```

Use this format:

```markdown
# checkpoint_04b.md

## 1. Phase 4B Status

- [ ] WebArena environment adapter
- [ ] WebArena task mapper
- [ ] WebArena assertion adapter
- [ ] WebArena subset selection
- [ ] WebArena runner integration
- [ ] Tests
- [ ] Documentation

## 2. Files Added/Updated

List files.

## 3. Real vs Mocked

Clearly say what was real and what was mocked.

## 4. Test Results

Include pass/fail count.

## 5. WebArena Subset Results

If live WebArena was available, include success rate.
If mock only, confirm mock success rate.

## 6. Cross-Repo Patterns Used

List reused patterns.

## 7. Remaining Blockers

List blockers.
```

---

## Stop Condition

Do not start Phase 4C (OSWorld).

Do not modify Phase 1-4A core logic.

Stop after producing:

```text
checkpoint_04b.md
```
