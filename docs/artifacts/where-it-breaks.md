# ColdStart — where it breaks (Step 06b · AXIS-ISOLATED · Option C)

- Generated: 2026-09-02T07:50:46.359Z
- Run set: inv__isol__P2_structure:3__s0, inv__isol__P2_structure:3__s0, inv__isol__P5_theme:3__s0, inv__isol__P5_theme:3__s0, inv__isol__P3_field_order:4__s0, inv__isol__P3_field_order:4__s0 (n=2 each)
- Constant task: `deriveTaskSpec(0).instruction` (ACMECORP) — ONLY the single active axis varies (causal).
- Success defined: agent `status === "ok"` AND verifier `task_completed === true`.

## Per-variant (per-point) result

| run_id | point (axis:intensity) | variant_id | terminated_by | status | task_completed | success | replay_url |
| --- | --- | --- | --- | --- | --- | --- | --- |
| r_mtjsgujp_isol__P2_structure-k3__s0_r1 | P2_structure:3 | inv__isol__P2_structure:3__s0 | abort | aborted | false | ❌ | yes |
| r_mtjsi3p1_isol__P2_structure-k3__s0_r2 | P2_structure:3 | inv__isol__P2_structure:3__s0 | step_cap | step_cap | false | ❌ | yes |
| r_mtjsm13e_isol__P5_theme-k3__s0_r1 | P5_theme:3 | inv__isol__P5_theme:3__s0 | done | ok | true | ✅ | yes |
| r_mtjsnjob_isol__P5_theme-k3__s0_r2 | P5_theme:3 | inv__isol__P5_theme:3__s0 | done | ok | true | ✅ | yes |
| r_mtjsp83o_isol__P3_field_order-k4__s0_r1 | P3_field_order:4 | inv__isol__P3_field_order:4__s0 | done | ok | true | ✅ | null |
| r_mtjsqyft_isol__P3_field_order-k4__s0_r2 | P3_field_order:4 | inv__isol__P3_field_order:4__s0 | abort | aborted | false | ❌ | null |

## success_by_point (causal, per isolated point)

| point | success_rate | n_runs |
| --- | --- | --- |
| P2_structure:3 | 0.00 | 2 |
| P5_theme:3 | 1.00 | 2 |
| P3_field_order:4 | 0.50 | 2 |

## success_by_axis (isolated — only the active axis's runs count)

| axis | success_rate | n_runs (isolated) |
| --- | --- | --- |
| P1_relabel (Semantic relabeling) | n/a (no isolated runs) | 0 |
| P2_structure (Structure / flow reorder) | 0.00 | 2 |
| P3_field_order (Field order & density) | 0.50 | 2 |
| P4_nav_order (Navigation order) | n/a (no isolated runs) | 0 |
| P5_theme (Theme / CSS skin) | 1.00 | 2 |

## generalization_curve (success rate vs intensity, isolated)

| axis | intensity | success_rate | n_runs |
| --- | --- | --- | --- |
| P2_structure | 0 | 1.00 (baseline ref) | 1 |
| P2_structure | 3 | 0.00 | 2 |
| P3_field_order | 0 | 1.00 (baseline ref) | 1 |
| P3_field_order | 4 | 0.50 | 2 |
| P5_theme | 0 | 1.00 (baseline ref) | 1 |
| P5_theme | 3 | 1.00 | 2 |

## where it breaks

| axis | intensity | variant_id | failure_mode |
| --- | --- | --- | --- |
| P2_structure | 3 | inv__isol__P2_structure:3__s0 | agent_aborted: agent loop failed: page.screenshot: Protocol error (Page.captureScreenshot): Unable to capture screenshot
Call log:
[2m  - taking page screenshot[22m
[2m  - waiting for fonts to load...[22m
[2m  - fonts loaded[22m
 |
| P2_structure | 3 | inv__isol__P2_structure:3__s0 | agent_step_cap: hit 40 steps without reaching 'done' |
| P3_field_order | 4 | inv__isol__P3_field_order:4__s0 | agent_aborted: Control channel closed (1005) |

> Honesty note: this is the CAUSAL axis-isolated run. Every perturbed run perturbs EXACTLY ONE axis
> (all others intensity 0) with a CONSTANT task/expected answer. A failure is attributed only to the
> one active axis. Intensity-0 'baseline ref' rows cite the Step 04b/06 baseline (success 1.0, n=1)
> — no additional agent run was spent on a baseline.
> Curve + break analysis are derived from run traces + verifier checks, not vibes.