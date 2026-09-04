# ColdStart — where it breaks (Step 06)

- Generated: 2026-09-02T06:52:36.316Z
- Run set: s0, s17, s9, s21, s3 (n=1 each)
- Success defined: agent `status === "ok"` AND verifier `task_completed === true`.

## Per-variant result

| run_id | seed | variant_id | terminated_by | status | task_completed | success |
| --- | --- | --- | --- | --- | --- | --- |
| r_mtjqb0xr_s0 | 0 | inv__s0__P1:0__P2:0__P3:0__P4:0__P5:0 | done | ok | true | ✅ |
| r_mtjqchve_s17 | 17 | inv__s17__P1:4__P2:0__P3:3__P4:0__P5:0 | done | ok | true | ✅ |
| r_mtjqdzgn_s9 | 9 | inv__s9__P1:0__P2:3__P3:4__P4:1__P5:0 | step_cap | step_cap | false | ❌ |
| r_mtjqhrwi_s21 | 21 | inv__s21__P1:1__P2:0__P3:3__P4:0__P5:3 | step_cap | step_cap | false | ❌ |
| r_mtjqmi96_s3 | 3 | inv__s3__P1:4__P2:2__P3:4__P4:0__P5:3 | abort | aborted | false | ❌ |

## success_by_axis

| axis | success_rate | n_runs (intensity>0) |
| --- | --- | --- |
| P1_relabel | 0.33 | 3 |
| P2_structure | 0.00 | 2 |
| P3_field_order | 0.25 | 4 |
| P4_nav_order | 0.00 | 1 |
| P5_theme | 0.00 | 2 |

## generalization_curve (success rate vs intensity)

| axis | intensity | success_rate | n_runs |
| --- | --- | --- | --- |
| P1_relabel | 0 | 0.50 | 2 |
| P1_relabel | 1 | 0.00 | 1 |
| P1_relabel | 4 | 0.50 | 2 |
| P2_structure | 0 | 0.67 | 3 |
| P2_structure | 2 | 0.00 | 1 |
| P2_structure | 3 | 0.00 | 1 |
| P3_field_order | 0 | 1.00 | 1 |
| P3_field_order | 3 | 0.50 | 2 |
| P3_field_order | 4 | 0.00 | 2 |
| P4_nav_order | 0 | 0.50 | 4 |
| P4_nav_order | 1 | 0.00 | 1 |
| P5_theme | 0 | 0.67 | 3 |
| P5_theme | 3 | 0.00 | 2 |

## where it breaks

| axis | intensity | variant_id | failure_mode |
| --- | --- | --- | --- |
| P2_structure | 3 | inv__s9__P1:0__P2:3__P3:4__P4:1__P5:0 | agent_step_cap: hit 40 steps without reaching 'done' |
| P3_field_order | 4 | inv__s9__P1:0__P2:3__P3:4__P4:1__P5:0 | agent_step_cap: hit 40 steps without reaching 'done' |
| P4_nav_order | 1 | inv__s9__P1:0__P2:3__P3:4__P4:1__P5:0 | agent_step_cap: hit 40 steps without reaching 'done' |
| P1_relabel | 1 | inv__s21__P1:1__P2:0__P3:3__P4:0__P5:3 | agent_step_cap: hit 40 steps without reaching 'done' |
| P3_field_order | 3 | inv__s21__P1:1__P2:0__P3:3__P4:0__P5:3 | agent_step_cap: hit 40 steps without reaching 'done' |
| P5_theme | 3 | inv__s21__P1:1__P2:0__P3:3__P4:0__P5:3 | agent_step_cap: hit 40 steps without reaching 'done' |
| P1_relabel | 4 | inv__s3__P1:4__P2:2__P3:4__P4:0__P5:3 | agent_aborted: agent loop failed: page.screenshot: mouse.click: page.evaluate: Browser closed |
| P2_structure | 2 | inv__s3__P1:4__P2:2__P3:4__P4:0__P5:3 | agent_aborted: agent loop failed: page.screenshot: mouse.click: page.evaluate: Browser closed |
| P3_field_order | 4 | inv__s3__P1:4__P2:2__P3:4__P4:0__P5:3 | agent_aborted: agent loop failed: page.screenshot: mouse.click: page.evaluate: Browser closed |
| P5_theme | 3 | inv__s3__P1:4__P2:2__P3:4__P4:0__P5:3 | agent_aborted: agent loop failed: page.screenshot: mouse.click: page.evaluate: Browser closed |

> Honesty note: perturbed variants perturb MULTIPLE axes at once, so a failure
> is attributed to every axis the variant touched (intensity>0). n=1 per point.
> Curve + break analysis are derived from run traces + verifier checks, not vibes.