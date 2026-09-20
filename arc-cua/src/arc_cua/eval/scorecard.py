"""Scorecard Builder for ARC (Phase 4A).

Implements Task 4A.7:
- Aggregates evaluation results into structured ScorecardSummary objects.
- Computes latency distributions (p50, p95, p99) via Telemetry percentiles.
- Compares Reflex-only vs Hybrid execution metrics side-by-side.
- Generates structured JSON artifacts and formatted Markdown tables.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from ..telemetry import compute_percentiles
from .schemas import EvalResult, ScorecardSummary

logger = logging.getLogger("arc_cua.eval.scorecard")


class ScorecardBuilder:
    """Aggregator and formatter for evaluation run scorecards."""

    @staticmethod
    def build(
        results: List[EvalResult],
        mode: Optional[str] = None,
        is_mocked: bool = True,
    ) -> ScorecardSummary:
        """Aggregate a list of EvalResult instances into a ScorecardSummary."""
        total_tasks = len(results)
        if total_tasks == 0:
            return ScorecardSummary(mode=mode or "unknown")

        mode_val = mode or (results[0].mode if results else "hybrid")
        successful_tasks = sum(1 for r in results if r.success)
        success_rate = successful_tasks / total_tasks

        # Latencies
        durations = [r.duration_ms for r in results]
        dist = compute_percentiles(durations, metric_name="duration_ms")

        # Steps
        total_steps = sum(r.total_steps for r in results)
        total_reflex_steps = sum(r.reflex_steps for r in results)
        avg_steps_per_task = total_steps / total_tasks if total_tasks > 0 else 0.0
        reflex_step_share = total_reflex_steps / total_steps if total_steps > 0 else 1.0

        # Escalation & Recovery
        tasks_with_escalation = sum(1 for r in results if r.escalations > 0)
        escalation_rate = tasks_with_escalation / total_tasks if total_tasks > 0 else 0.0

        total_rec_attempts = sum(r.recoveries_attempted for r in results)
        total_rec_succeeded = sum(r.recoveries_succeeded for r in results)
        tasks_with_recovery_attempts = sum(1 for r in results if r.recoveries_attempted > 0)
        recovery_attempt_rate = tasks_with_recovery_attempts / total_tasks if total_tasks > 0 else 0.0
        recovery_success_rate = total_rec_succeeded / total_rec_attempts if total_rec_attempts > 0 else 0.0

        # Milestones
        milestone_detection_count = sum(r.milestones_detected for r in results)

        # Aborts
        aborted_tasks = sum(1 for r in results if r.aborted)
        abort_rate = aborted_tasks / total_tasks if total_tasks > 0 else 0.0

        # Costs
        total_cost = sum(r.cost_usd for r in results)
        avg_cost = total_cost / total_tasks if total_tasks > 0 else 0.0

        # Assertion Failures
        assertion_failures = 0
        category_breakdown: Dict[str, Dict[str, Any]] = {}
        for r in results:
            cat = r.metadata.get("category", "general")
            if cat not in category_breakdown:
                category_breakdown[cat] = {"total": 0, "success": 0}
            category_breakdown[cat]["total"] += 1
            if r.success:
                category_breakdown[cat]["success"] += 1

            for a in r.assertion_results:
                if not a.passed:
                    assertion_failures += 1

        details = {
            "is_mocked": is_mocked,
            "category_stats": category_breakdown,
            "min_duration_ms": round(dist.min, 2),
            "max_duration_ms": round(dist.max, 2),
            "total_recovery_attempts": total_rec_attempts,
            "total_recovery_successes": total_rec_succeeded,
        }

        return ScorecardSummary(
            total_tasks=total_tasks,
            successful_tasks=successful_tasks,
            success_rate=success_rate,
            avg_duration_ms=dist.mean,
            p50_duration_ms=dist.p50,
            p95_duration_ms=dist.p95,
            p99_duration_ms=dist.p99,
            total_steps=total_steps,
            avg_steps_per_task=avg_steps_per_task,
            reflex_step_share=reflex_step_share,
            escalation_rate=escalation_rate,
            recovery_attempt_rate=recovery_attempt_rate,
            recovery_success_rate=recovery_success_rate,
            milestone_detection_count=milestone_detection_count,
            abort_rate=abort_rate,
            total_cost_usd=total_cost,
            avg_cost_per_task_usd=avg_cost,
            assertion_failure_count=assertion_failures,
            mode=mode_val,
            details=details,
        )

    @classmethod
    def build_comparison(
        cls,
        reflex_results: List[EvalResult],
        hybrid_results: List[EvalResult],
        is_mocked: bool = True,
    ) -> Dict[str, Any]:
        """Produce comparison metrics between Reflex-only and Hybrid runs."""
        reflex_sc = cls.build(reflex_results, mode="reflex_only", is_mocked=is_mocked)
        hybrid_sc = cls.build(hybrid_results, mode="hybrid", is_mocked=is_mocked)

        success_delta = hybrid_sc.success_rate - reflex_sc.success_rate
        recovery_delta = hybrid_sc.recovery_success_rate - reflex_sc.recovery_success_rate
        duration_delta_p50 = hybrid_sc.p50_duration_ms - reflex_sc.p50_duration_ms

        comparison = {
            "reflex_only": reflex_sc.to_dict(),
            "hybrid": hybrid_sc.to_dict(),
            "deltas": {
                "success_rate_diff": round(success_delta, 4),
                "recovery_success_rate_diff": round(recovery_delta, 4),
                "p50_duration_ms_diff": round(duration_delta_p50, 2),
                "hybrid_outperforms_reflex": (hybrid_sc.success_rate >= reflex_sc.success_rate),
            },
        }
        return comparison

    @classmethod
    def to_json(cls, scorecard: ScorecardSummary) -> str:
        """Serialize scorecard to indented JSON string."""
        return json.dumps(scorecard.to_dict(), indent=2)

    @classmethod
    def to_markdown(
        cls,
        scorecard: ScorecardSummary,
        comparison: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Render markdown report card with tables."""
        lines = []
        lines.append(f"# Evaluation Scorecard ({scorecard.mode.upper()})")
        lines.append("")
        lines.append(f"**Execution Mode:** `{scorecard.mode}` | **Mocked / Offline:** `{scorecard.details.get('is_mocked', True)}`")
        lines.append("")
        lines.append("## Core Metrics")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("| :--- | :--- |")
        lines.append(f"| **Total Tasks** | {scorecard.total_tasks} |")
        lines.append(f"| **Successful Tasks** | {scorecard.successful_tasks} |")
        lines.append(f"| **Success Rate** | {scorecard.success_rate * 100:.1f}% |")
        lines.append(f"| **Avg Duration** | {scorecard.avg_duration_ms:.1f} ms |")
        lines.append(f"| **p50 Duration** | {scorecard.p50_duration_ms:.1f} ms |")
        lines.append(f"| **p95 Duration** | {scorecard.p95_duration_ms:.1f} ms |")
        lines.append(f"| **p99 Duration** | {scorecard.p99_duration_ms:.1f} ms |")
        lines.append(f"| **Total Steps** | {scorecard.total_steps} |")
        lines.append(f"| **Avg Steps / Task** | {scorecard.avg_steps_per_task:.2f} |")
        lines.append(f"| **Reflex Step Share** | {scorecard.reflex_step_share * 100:.1f}% |")
        lines.append(f"| **Escalation Rate** | {scorecard.escalation_rate * 100:.1f}% |")
        lines.append(f"| **Recovery Attempt Rate** | {scorecard.recovery_attempt_rate * 100:.1f}% |")
        lines.append(f"| **Recovery Success Rate** | {scorecard.recovery_success_rate * 100:.1f}% |")
        lines.append(f"| **Milestones Detected** | {scorecard.milestone_detection_count} |")
        lines.append(f"| **Abort Rate** | {scorecard.abort_rate * 100:.1f}% |")
        lines.append(f"| **Total Cost (USD)** | ${scorecard.total_cost_usd:.6f} |")
        lines.append(f"| **Avg Cost / Task (USD)** | ${scorecard.avg_cost_per_task_usd:.6f} |")
        lines.append(f"| **Assertion Failures** | {scorecard.assertion_failure_count} |")
        lines.append("")

        # Optional comparison table
        if comparison:
            ref = comparison.get("reflex_only", {})
            hyb = comparison.get("hybrid", {})
            deltas = comparison.get("deltas", {})
            lines.append("## Reflex-Only vs Hybrid Comparison")
            lines.append("")
            lines.append("| Metric | Reflex-Only | Hybrid | Advantage |")
            lines.append("| :--- | :--- | :--- | :--- |")
            lines.append(f"| Success Rate | {ref.get('success_rate', 0)*100:.1f}% | {hyb.get('success_rate', 0)*100:.1f}% | {'+'+str(round(deltas.get('success_rate_diff', 0)*100, 1))+'%' if deltas.get('success_rate_diff', 0) >= 0 else str(round(deltas.get('success_rate_diff', 0)*100, 1))+'%'} |")
            lines.append(f"| Recovery Success Rate | {ref.get('recovery_success_rate', 0)*100:.1f}% | {hyb.get('recovery_success_rate', 0)*100:.1f}% | {'+'+str(round(deltas.get('recovery_success_rate_diff', 0)*100, 1))+'%'} |")
            lines.append(f"| p50 Duration (ms) | {ref.get('p50_duration_ms', 0):.1f} | {hyb.get('p50_duration_ms', 0):.1f} | {'Δ '+str(deltas.get('p50_duration_ms_diff', 0))+' ms'} |")
            lines.append(f"| Escalation Rate | {ref.get('escalation_rate', 0)*100:.1f}% | {hyb.get('escalation_rate', 0)*100:.1f}% | {'Hybrid Managed' if hyb.get('escalation_rate', 0) > 0 else 'None'} |")
            lines.append(f"| Abort Rate | {ref.get('abort_rate', 0)*100:.1f}% | {hyb.get('abort_rate', 0)*100:.1f}% | {'Lower' if hyb.get('abort_rate', 0) <= ref.get('abort_rate', 0) else 'Higher'} |")
            lines.append("")

        return "\n".join(lines)

    @classmethod
    def write_scorecard_json(cls, scorecard: ScorecardSummary, path: Union[str, Path]) -> str:
        """Write scorecard to JSON file."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        content = cls.to_json(scorecard)
        p.write_text(content, encoding="utf-8")
        return str(p.resolve())

    @classmethod
    def write_scorecard_markdown(
        cls,
        scorecard: ScorecardSummary,
        path: Union[str, Path],
        comparison: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Write scorecard to Markdown file."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        content = cls.to_markdown(scorecard, comparison=comparison)
        p.write_text(content, encoding="utf-8")
        return str(p.resolve())
