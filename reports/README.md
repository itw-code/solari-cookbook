# Reports — conventions & mandatory template

Every step of the master plan MUST produce exactly one report at
`reports/step-NN-<slug>.md`. The orchestrator audits the step **only from this file plus
the deliverables it references**. Missing sections or claims without evidence = audit
FAIL. Subagents: copy the template below and fill every section.

---

## Template

```md
# Step NN — <slug> — Report

- **Status:** DONE | BLOCKED | DONE-MOCK (label honestly)
- **Mode:** LIVE | MOCK
- **Agent:** <subagent name/role>
- **Date:** YYYY-MM-DD

## 1. What was done
(short narrative; no fluff)

## 2. Commands run
(verbatim, pastable; each output referenced below)

## 3. Deliverables
- <path> — <what it is>
(every path must exist)

## 4. Evidence
- Claim → file/log/screenshot/URL pointer, e.g.
  - "sandbox fork boots in 830ms" → artifacts/timing.json
  - "live replay" → https://... (live mode only)

## 5. Deviations from plan
(what differs from the step spec and why)

## 6. Self-check vs acceptance criteria
| Criterion | Met? | Evidence |
| --- | --- | --- |
| <each acceptance item from MASTER_PLAN> | yes/no | <pointer> |

## 7. Open questions / risks
(for the orchestrator)

## 8. Secrets & cleanup attestation
- [ ] No API keys/secrets in repo or this report
- [ ] All Solari resources killed / VMs terminated (list cleanup proof)
```

## Audit notes (orchestrator use)

The orchestrator will:
1. Verify each Deliverable path exists.
2. Re-run the step's verification commands where feasible.
3. Check section 6 is complete and truthful.
4. Append verdict to `../AUDIT_LOG.md` with PASS / FAIL + notes.

---

## Note on this vendored copy

These reports were produced during the ColdStart build (Steps 00–07) and are committed
here as the audit trail behind every claim in the root `README.md`. They are reproduced
**verbatim** from the working directory in which they were written — so a handful of
relative links inside them (e.g. `../AUDIT_LOG.md`, `../MASTER_PLAN.md`) point at
orchestration files that live outside this repository. The report contents, commands, and
evidence pointers into `artifacts/` are unchanged and remain accurate.
