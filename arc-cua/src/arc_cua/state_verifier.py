"""State Verification Engine for Phase 2 Reflex Automation.

Implements Task 2.4:
- Verifies post-action state transition deterministically without LLM calls.
- Employs 64-bit SimHash comparison via Phase 1 TelemetryCollector.
- Detects:
  1. Accessibility tree SimHash divergence (Hamming distance).
  2. URL transitions.
  3. Visible text deltas.
  4. DOM mutations / node count changes.
- Flags "stuck" loop indicator if an action succeeds mechanically with zero state delta.
- Yields structured StateVerificationResult.
"""

from __future__ import annotations

import dataclasses
import difflib
import logging
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from .cdp_extractor import CDP_AXTree_Extractor, SanitizedAXTree
from .schemas import ActionResult, UIState
from .telemetry import compute_simhash64

logger = logging.getLogger("arc_cua.state_verifier")


@dataclasses.dataclass
class StateVerificationResult:
    """Outcome of state verification comparing UI state before and after an action."""
    state_changed: bool
    simhash_before: int
    simhash_after: int
    hamming_distance: int
    url_changed: bool = False
    url_before: Optional[str] = None
    url_after: Optional[str] = None
    text_delta_detected: bool = False
    dom_mutations_detected: bool = False
    is_stuck_indicator: bool = False
    verification_latency_ms: float = 0.0
    details: Dict[str, Any] = dataclasses.field(default_factory=dict)


def compute_hamming_distance(h1: int, h2: int) -> int:
    """Calculate the bitwise Hamming distance between two 64-bit integers."""
    return bin((h1 ^ h2) & 0xFFFFFFFFFFFFFFFF).count("1")


class StateVerifier:
    """Deterministic state verification engine detecting state progression and stuck loops."""

    # Actions where a lack of state change is normal
    NEUTRAL_ACTIONS = {"WAIT", "WAIT_FOR_SELECTOR"}

    def __init__(self, stuck_hamming_threshold: int = 0):
        """Initialize the state verification engine.

        Args:
            stuck_hamming_threshold: Maximum Hamming distance considered "no change".
        """
        self.stuck_hamming_threshold = stuck_hamming_threshold

    def verify(
        self,
        action_result: ActionResult,
        state_before: Union[UIState, SanitizedAXTree, str],
        state_after: Union[UIState, SanitizedAXTree, str],
        url_before: Optional[str] = None,
        url_after: Optional[str] = None,
    ) -> StateVerificationResult:
        """Verify state change between pre-action and post-action snapshots.

        Args:
            action_result: The ActionResult returned by PlaywrightExecutor.
            state_before: Snapshot prior to action execution.
            state_after: Snapshot after action execution.
            url_before: Optional starting URL.
            url_after: Optional resulting URL.

        Returns:
            StateVerificationResult with delta flags and stuck indicator.
        """
        start_time = time.perf_counter()

        # 1. Normalize representations and compute SimHashes
        text_before, hash_before = self._extract_text_and_hash(state_before)
        text_after, hash_after = self._extract_text_and_hash(state_after)

        # 2. Compute Hamming distance
        hamming = compute_hamming_distance(hash_before, hash_after)

        # 3. Check URL change
        eff_url_before = url_before
        eff_url_after = url_after or action_result.resulting_url
        url_changed = bool(
            eff_url_before and eff_url_after and eff_url_before.rstrip("/") != eff_url_after.rstrip("/")
        )

        # 4. Check Text Delta
        text_delta = text_before.strip() != text_after.strip()

        # 5. Check Node / DOM Mutation Counts
        dom_mutated, mutation_details = self._check_dom_mutations(state_before, state_after)

        # 6. Overall State Change Determination
        state_changed = bool(
            (hamming > self.stuck_hamming_threshold)
            or url_changed
            or text_delta
            or dom_mutated
        )

        # 7. Stuck Indicator Evaluation (Mechanical success, but zero state change)
        is_stuck = False
        verb_upper = (action_result.verb or "").upper()
        if action_result.success and not state_changed:
            if verb_upper not in self.NEUTRAL_ACTIONS:
                is_stuck = True
                logger.warning(
                    f"Stuck Indicator: Action {verb_upper} on '{action_result.target_selector}' "
                    f"succeeded mechanically with zero state delta (Hamming={hamming}, URL={eff_url_after})"
                )

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        details = {
            "verb": action_result.verb,
            "target": action_result.target_selector,
            "dom_mutations": mutation_details,
        }

        return StateVerificationResult(
            state_changed=state_changed,
            simhash_before=hash_before,
            simhash_after=hash_after,
            hamming_distance=hamming,
            url_changed=url_changed,
            url_before=eff_url_before,
            url_after=eff_url_after,
            text_delta_detected=text_delta,
            dom_mutations_detected=dom_mutated,
            is_stuck_indicator=is_stuck,
            verification_latency_ms=latency_ms,
            details=details,
        )

    def verify_with_page(
        self,
        action_result: ActionResult,
        page: Any,
        state_before: Union[UIState, SanitizedAXTree, str],
        extractor: Optional[CDP_AXTree_Extractor] = None,
        url_before: Optional[str] = None,
    ) -> StateVerificationResult:
        """Capture live post-action state from page and perform verification."""
        url_after = getattr(page, "url", None)

        if extractor is not None:
            # Extract live AXTree from page/CDP
            try:
                tree_after = extractor.extract()
                return self.verify(
                    action_result=action_result,
                    state_before=state_before,
                    state_after=tree_after,
                    url_before=url_before,
                    url_after=url_after,
                )
            except Exception as e:
                logger.debug(f"Live AXTree extraction failed during state verification: {e}")

        # Fallback to page text content or title
        page_text = ""
        if hasattr(page, "content"):
            try:
                page_text = page.content()
            except Exception:
                pass

        return self.verify(
            action_result=action_result,
            state_before=state_before,
            state_after=page_text,
            url_before=url_before,
            url_after=url_after,
        )

    def _extract_text_and_hash(
        self, state: Union[UIState, SanitizedAXTree, str]
    ) -> Tuple[str, int]:
        """Extract linear text representation and 64-bit SimHash."""
        if isinstance(state, UIState):
            simhash = state.simhash or compute_simhash64(state.yaml_representation)
            return state.yaml_representation, simhash
        elif isinstance(state, SanitizedAXTree):
            text = state.yaml_linearized
            return text, compute_simhash64(text)
        elif isinstance(state, str):
            return state, compute_simhash64(state)
        else:
            text = str(state)
            return text, compute_simhash64(text)

    def _check_dom_mutations(
        self,
        before: Union[UIState, SanitizedAXTree, str],
        after: Union[UIState, SanitizedAXTree, str],
    ) -> Tuple[bool, Dict[str, Any]]:
        """Compare node counts or structured nodes if available."""
        mutated = False
        details: Dict[str, Any] = {}

        count_before = None
        count_after = None

        if isinstance(before, (UIState, SanitizedAXTree)):
            count_before = (
                before.actionable_count
                if hasattr(before, "actionable_count")
                else getattr(before, "raw_node_count", None)
            )
        if isinstance(after, (UIState, SanitizedAXTree)):
            count_after = (
                after.actionable_count
                if hasattr(after, "actionable_count")
                else getattr(after, "raw_node_count", None)
            )

        if count_before is not None and count_after is not None:
            details["count_before"] = count_before
            details["count_after"] = count_after
            if count_before != count_after:
                mutated = True
                details["count_delta"] = count_after - count_before

        return mutated, details
