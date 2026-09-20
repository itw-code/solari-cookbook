"""Cortex Abstract Interface for ARC (Phase 3A).

Defines the contract for frontier model / reasoning engine escalation and recovery.
"""

from __future__ import annotations

import abc
from ..schemas import CortexResponse, EscalationPayload


class CortexClient(abc.ABC):
    """Abstract interface for Cortex reasoning agents handling Reflex escalations."""

    @abc.abstractmethod
    def recover(self, payload: EscalationPayload) -> CortexResponse:
        """Process an escalation payload and return a structured recovery plan.

        Args:
            payload: EscalationPayload detailing failure context, history, and state.

        Returns:
            CortexResponse containing a typed RecoveryPlan.
        """
        ...
