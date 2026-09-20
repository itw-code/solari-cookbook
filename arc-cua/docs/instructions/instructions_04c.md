# instructions_04c.md

## Phase 4B Review Result

Status: PASS

Approved Phase 4B components:

- `src/arc_cua/eval/webarena_env.py`
- `src/arc_cua/eval/webarena_mapper.py`
- `src/arc_cua/eval/webarena_assertions.py`
- `src/arc_cua/eval/tasks_webarena.py`
- `src/arc_cua/eval/webarena_runner.py`
- `tests/test_phase4b_webarena.py`

Review notes:

1. WebArena environment adapter and dual-layer DB diffing are approved.
2. Task mapper and assertion adapter are approved.
3. Mock environment successfully allows 100% offline CI execution.
4. Phase 4C must now integrate real-world desktop benchmark tasks.

---

## Phase 4C Mission

Build the OSWorld Desktop Subset Integration.

Work in:

```text
arc-hybrid-cua/
```

Phase 4C connects the local evaluation harness to a subset of the OSWorld benchmark, focusing on desktop applications (LibreOffice, Terminal, VS Code, OS file system).

Do not download or run the full OSWorld Docker/VM infrastructure if it exceeds local CI limits. Instead, build the complete harness, task mapper, and assertion adapter, and run a representative subset using mock/stubbed AT-SPI trees and file systems if the live Linux desktop environment is unavailable.

---

## Phase 4C Scope

Allowed:

- OSWorld environment adapter (AT-SPI state, File System, Terminal output)
- OSWorld task schema mapper
- OSWorld assertion adapter (file checks, terminal checks, GUI state checks)
- Subset task selection (10-12 representative tasks)
- OSWorld eval runner integration
- Tests
- Documentation

Not allowed:

- Modifying Phase 1, 2, 3, 4A, or 4B core logic
- Real Cortex calls
- Private Playwright internals

---

## Strict Rules

1. Default mode must remain offline/mock if a real Linux desktop/Xvfb environment is not running.
2. Do not modify Phase 4A/4B schemas; extend them if necessary.
3. Use existing `EvalRunner`, `ScorecardBuilder`, `HybridRunner`, and `AT_SPI_Bridge`.
4. Keep final implementation inside `arc-hybrid-cua/`.

---

## Task 1: OSWorld Environment Adapter

Create:

```text
src/arc_cua/eval/osworld_env.py
```

Purpose:

Manage the connection to the OSWorld desktop environment.

Requirements:

1. Support `live` mode (connecting to real X11/Xvfb, AT-SPI D-Bus, and real file system).
2. Support `mock` mode (returning stubbed AT-SPI trees, in-memory file system, and mock terminal outputs).
3. Provide methods to reset the environment state before a task (e.g., restore mock files, reset mock AT-SPI state).
4. Integrate with `src/arc_cua/at_spi_bridge.py` for live mode.

---

## Task 2: OSWorld Task Schema Mapper

Create:

```text
src/arc_cua/eval/osworld_mapper.py
```

Purpose:

Convert OSWorld task definitions into our internal `EvalTask` schema.

Requirements:

1. Ingest OSWorld JSON task format.
2. Map `instruction`, `start_state`, and `eval_types` to `EvalTask`.
3. Map OSWorld evaluation criteria to our `EvalAssertion` schema.
4. Handle unsupported evaluation types gracefully (mark as `SKIP`).

---

## Task 3: OSWorld Assertion Adapter

Create:

```text
src/arc_cua/eval/osworld_assertions.py
```

Purpose:

Implement OSWorld-specific evaluation logic.

Requirements:

1. `file_exist`: Check if a specific file exists in the file system.
2. `file_content_match`: Check if a file contains specific text or matches a regex.
3. `terminal_output_match`: Check if the mock/real terminal history contains expected commands or outputs.
4. `at_spi_state_match`: Check if a specific widget is present, focused, or has a specific value in the AT-SPI tree.
5. Integrate with `osworld_env.py` to fetch live or mock state.

---

## Task 4: OSWorld Subset Selection

Create:

```text
src/arc_cua/eval/tasks_osworld.py
```

Purpose:

Define a hardcoded subset of 10-12 representative OSWorld tasks for testing the harness.

Requirements:

1. Include tasks from at least 3 domains (e.g., OS File System, Terminal, LibreOffice/VS Code).
2. Include tasks with different evaluation types (`file_exist`, `file_content_match`, `terminal_output_match`).
3. Format them as `EvalTask` objects.
4. Ensure the mock environment can satisfy these specific subset tasks.

---

## Task 5: OSWorld Eval Runner Integration

Create:

```text
src/arc_cua/eval/osworld_runner.py
```

Purpose:

Run OSWorld tasks through the Hybrid Runner.

Requirements:

1. Initialize `OSWorldEnv`.
2. Reset environment state.
3. Execute task via `HybridRunner` (using AT-SPI perception and desktop actions).
4. Evaluate assertions via `OSWorldAssertionAdapter`.
5. Return `EvalResult`.

---

## Task 6: Tests

Create:

```text
tests/test_phase4c_osworld.py
```

Required tests:

1. OSWorld task mapper correctly parses sample JSON.
2. OSWorld assertion adapter correctly evaluates `file_exist`.
3. OSWorld assertion adapter correctly evaluates `file_content_match`.
4. OSWorld assertion adapter correctly evaluates `terminal_output_match`.
5. OSWorld assertion adapter correctly evaluates `at_spi_state_match` (using mock AT-SPI tree).
6. OSWorld runner executes a mock subset task successfully.
7. No external network calls occur in mock mode.

---

## Task 7: Documentation

Update:

```text
ARCHITECTURE.md
IMPLEMENTATION_PLAN.md
```

Add:

1. Phase 4C OSWorld integration design.
2. Task mapping strategy.
3. Assertion adapter logic (File, Terminal, AT-SPI).
4. Mock vs Live desktop environment policy.

---

## Definition of Done

Phase 4C is complete only if:

1. OSWorld environment adapter exists.
2. OSWorld task mapper exists.
3. OSWorld assertion adapter exists.
4. Subset task selection exists.
5. OSWorld runner integration exists.
6. Tests pass in mock mode.
7. Documentation is updated.

---

## Required Final Output

After completing Phase 4C, create:

```text
checkpoint_04c.md
```

Use this format:

```markdown
# checkpoint_04c.md

## 1. Phase 4C Status

- [ ] OSWorld environment adapter
- [ ] OSWorld task mapper
- [ ] OSWorld assertion adapter
- [ ] OSWorld subset selection
- [ ] OSWorld runner integration
- [ ] Tests
- [ ] Documentation

## 2. Files Added/Updated

List files.

## 3. Real vs Mocked

Clearly say what was real and what was mocked.

## 4. Test Results

Include pass/fail count.

## 5. OSWorld Subset Results

If live OSWorld was available, include success rate.
If mock only, confirm mock success rate.

## 6. Cross-Repo Patterns Used

List reused patterns.

## 7. Remaining Blockers

List blockers.
```

---

## Stop Condition

Do not start Phase 5.

Do not modify Phase 1-4B core logic.

Stop after producing:

```text
checkpoint_04c.md
```
