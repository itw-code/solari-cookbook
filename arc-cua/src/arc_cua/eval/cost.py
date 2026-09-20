"""Cost Ledger for ARC (Phase 4A).

Implements Task 4A.6:
- Tracks estimated execution and infrastructure cost per task.
- Zero cost for local Reflex and mock Cortex in default Phase 4A mode.
- Extensible pricing models for future real Cortex token usage and Arc cloud VM time.
- Emits structured CostRecord instances embedded into EvalResult.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Optional

from .schemas import CostRecord


@dataclasses.dataclass
class CostModelConfig:
    """Pricing configuration for evaluation runs."""
    # Local reflex execution cost
    reflex_step_cost_usd: float = 0.0

    # Cortex reasoning cost
    mock_cortex_call_cost_usd: float = 0.0
    cortex_input_token_cost_usd: float = 0.0000025   # $2.50 / 1M tokens
    cortex_output_token_cost_usd: float = 0.0000100  # $10.00 / 1M tokens

    # Infrastructure compute (estimated ~$0.018/hr = $0.000005/sec)
    browser_infra_cost_per_ms: float = 0.000000005


class CostLedger:
    """Calculates and records execution costs across reflex, cortex, and compute infrastructure."""

    def __init__(self, config: Optional[CostModelConfig] = None):
        self.config = config or CostModelConfig()

    def calculate_task_cost(
        self,
        task_id: str,
        reflex_steps: int = 0,
        cortex_calls: int = 0,
        browser_runtime_ms: float = 0.0,
        cortex_input_tokens: int = 0,
        cortex_output_tokens: int = 0,
        is_mock_cortex: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CostRecord:
        """Calculate and return a CostRecord for a completed task."""
        # 1. Reflex cost
        local_reflex_cost = reflex_steps * self.config.reflex_step_cost_usd

        # 2. Cortex cost
        if is_mock_cortex:
            cortex_cost = cortex_calls * self.config.mock_cortex_call_cost_usd
        else:
            cortex_cost = (
                cortex_input_tokens * self.config.cortex_input_token_cost_usd
                + cortex_output_tokens * self.config.cortex_output_token_cost_usd
            )

        # 3. Infrastructure compute cost
        infra_cost = browser_runtime_ms * self.config.browser_infra_cost_per_ms

        total_cost = local_reflex_cost + cortex_cost + infra_cost

        return CostRecord(
            task_id=task_id,
            mock_cortex_cost_usd=round(cortex_cost, 6) if is_mock_cortex else 0.0,
            local_reflex_cost_usd=round(local_reflex_cost, 6),
            browser_runtime_ms=browser_runtime_ms,
            estimated_infra_cost_usd=round(infra_cost, 6),
            total_cost_usd=round(total_cost, 6),
            metadata=metadata or {},
        )

    def aggregate_costs(self, records: List[CostRecord]) -> Dict[str, float]:
        """Aggregate total and category costs across a list of records."""
        total = sum(r.total_cost_usd for r in records)
        cortex_total = sum(r.mock_cortex_cost_usd for r in records)
        reflex_total = sum(r.local_reflex_cost_usd for r in records)
        infra_total = sum(r.estimated_infra_cost_usd for r in records)
        runtime_total = sum(r.browser_runtime_ms for r in records)

        return {
            "total_cost_usd": round(total, 6),
            "mock_cortex_cost_usd": round(cortex_total, 6),
            "local_reflex_cost_usd": round(reflex_total, 6),
            "estimated_infra_cost_usd": round(infra_total, 6),
            "browser_runtime_ms": round(runtime_total, 2),
            "avg_cost_per_task_usd": round(total / len(records), 6) if records else 0.0,
        }
