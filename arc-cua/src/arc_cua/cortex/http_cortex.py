"""HTTP Cortex Client Adapter for ARC (Phase 3B Task 7).

Routes escalations to frontier reasoning models or mock endpoints:
- Supports modes: 'mock' (default), 'dry_run', and 'real'.
- Never makes external network calls unless explicitly configured (CORTEX_MODE=real).
- Builds comprehensive diagnostic payload:
  * task_goal
  * escalation_reason
  * recent_trajectory
  * current_state_hash
  * recent_state_hashes
  * last_actions
  * locator_attempts
  * errors
  * budget
- Validates response schemas and compiles through RecoveryCompiler.
- Implements bounded exponential backoff retries and safe timeouts.
- Strictly redacts API keys and secrets from logs and telemetry.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Dict, List, Optional, Union

from ..schemas import (
    ActionStep,
    CortexResponse,
    EscalationPayload,
    PlanSource,
    RecoveryPlan,
)
from .cortex_interface import CortexClient
from .mock_cortex import MockCortexClient
from .recovery_compiler import RecoveryCompilationError, RecoveryCompiler

logger = logging.getLogger("arc_cua.cortex.http_cortex")


class HttpCortexClient(CortexClient):
    """Cortex Client routing escalations over HTTP with robust safety controls."""

    def __init__(
        self,
        mode: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        timeout_ms: Optional[int] = None,
        recovery_compiler: Optional[RecoveryCompiler] = None,
        mock_fallback: Optional[MockCortexClient] = None,
    ):
        """Initialize HttpCortexClient with environment defaults."""
        self.mode = (mode or os.getenv("CORTEX_MODE", "mock")).lower()
        self.provider = provider or os.getenv("CORTEX_PROVIDER", "generic")
        self.model = model or os.getenv("CORTEX_MODEL", "cortex-reasoner-v1")
        self._api_key = api_key or os.getenv("CORTEX_API_KEY", "")
        self.endpoint = endpoint or os.getenv("CORTEX_ENDPOINT", "")
        self.timeout_ms = int(timeout_ms or os.getenv("CORTEX_TIMEOUT_MS", "10000"))
        self.recovery_compiler = recovery_compiler or RecoveryCompiler()
        self.mock_fallback = mock_fallback or MockCortexClient(model_name=f"mock-{self.model}")

        # Safety: log configuration with redacted key
        has_key = bool(self._api_key)
        logger.info(
            f"Initialized HttpCortexClient [mode={self.mode}, provider={self.provider}, "
            f"model={self.model}, has_api_key={has_key}, endpoint={self.endpoint or 'none'}]"
        )

    def build_request_payload(self, payload: EscalationPayload) -> Dict[str, Any]:
        """Construct structured diagnostic payload for Cortex."""
        step_history = payload.step_history or []

        recent_trajectory: List[Dict[str, Any]] = []
        recent_hashes: List[str] = []
        last_actions: List[Dict[str, Any]] = []
        locator_attempts: List[str] = []

        for step in step_history[-5:]:
            recent_trajectory.append({
                "step_index": getattr(step, "step_number", getattr(step, "step_index", 1)),
                "verb": getattr(step, "verb", ""),
                "target": getattr(step, "target_selector", getattr(step, "target", None)),
                "value": getattr(step, "value", None),
                "success": getattr(step, "success", True),
                "resulting_url": getattr(step, "resulting_url", None),
            })
            last_actions.append({"verb": step.verb, "target": step.target_selector})
            if step.target_selector:
                locator_attempts.append(step.target_selector)

        current_hash = hex(payload.current_state.simhash) if payload.current_state else "0x0"
        recent_hashes.append(current_hash)

        return {
            "task_goal": payload.task_goal,
            "escalation_reason": payload.reason.value,
            "recent_trajectory": recent_trajectory,
            "current_state_hash": current_hash,
            "recent_state_hashes": recent_hashes,
            "last_actions": last_actions,
            "locator_attempts": list(set(locator_attempts)),
            "errors": payload.failure_details or {},
            "budget": {
                "max_recovery_actions": 5,
                "timeout_ms": self.timeout_ms,
            },
            "timestamp": payload.timestamp,
            "escalation_id": payload.escalation_id,
        }

    def recover(self, payload: EscalationPayload) -> CortexResponse:
        """Process an escalation payload in mock, dry_run, or real mode."""
        start_time = time.perf_counter()

        # 1. Mock mode: Pure deterministic local recovery
        if self.mode == "mock":
            logger.info("Executing recovery in MOCK mode (zero network)")
            resp = self.mock_fallback.recover(payload)
            resp.model = f"mock:{self.model}"
            return resp

        # 2. Build request payload
        req_payload = self.build_request_payload(payload)

        # 3. Dry-run mode: Build payload without network dispatch
        if self.mode == "dry_run":
            latency = (time.perf_counter() - start_time) * 1000.0
            logger.info(f"Executing recovery in DRY_RUN mode (payload built in {latency:.2f}ms)")
            # Generate mock plan for dry run but attach payload
            mock_res = self.mock_fallback.recover(payload)
            return CortexResponse(
                plan=mock_res.plan,
                raw_response=json.dumps({"dry_run": True, "request_payload": req_payload}),
                model=f"dry-run:{self.model}",
                latency_ms=latency,
                tokens_used=0,
                cost_usd=0.0,
                success=True,
                metadata={"dry_run_payload": req_payload, "mode": "dry_run"},
            )

        # 4. Real mode: Explicit network call with retries and validation
        if self.mode == "real":
            return self._execute_real_recovery(req_payload, start_time)

        # Unknown mode fallback
        logger.warning(f"Unknown CORTEX_MODE '{self.mode}', falling back to mock")
        return self.mock_fallback.recover(payload)

    def _execute_real_recovery(
        self, req_payload: Dict[str, Any], start_time: float
    ) -> CortexResponse:
        """Execute real HTTP POST request to Cortex endpoint with exponential backoff."""
        if not self.endpoint:
            return CortexResponse(
                plan=None,
                model=self.model,
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
                success=False,
                error="CORTEX_CONFIG_ERROR: CORTEX_ENDPOINT is not configured",
            )

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Arc-Hybrid-CUA/1.0",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        body_bytes = json.dumps(req_payload).encode("utf-8")
        timeout_sec = max(1.0, self.timeout_ms / 1000.0)

        max_retries = 3
        backoff_sec = 0.1
        last_error: Optional[str] = None

        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"Dispatching real Cortex request (attempt {attempt}/{max_retries}) to {self.endpoint}")
                req = urllib.request.Request(self.endpoint, data=body_bytes, headers=headers, method="POST")

                with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                    resp_data = resp.read().decode("utf-8")
                    latency = (time.perf_counter() - start_time) * 1000.0
                    return self._parse_and_validate_response(resp_data, latency)

            except urllib.error.HTTPError as http_err:
                last_error = f"HTTPError {http_err.code}: {http_err.reason}"
                logger.error(f"Cortex HTTP error on attempt {attempt}: {last_error}")
                if http_err.code in {400, 401, 403}:  # Client/auth error, do not retry
                    break
            except urllib.error.URLError as url_err:
                last_error = f"URLError: {url_err.reason}"
                logger.warning(f"Cortex network error on attempt {attempt}: {last_error}")
            except Exception as e:
                last_error = f"RequestError: {e}"
                logger.warning(f"Cortex generic error on attempt {attempt}: {last_error}")

            if attempt < max_retries:
                time.sleep(backoff_sec)
                backoff_sec *= 2.0

        latency = (time.perf_counter() - start_time) * 1000.0
        return CortexResponse(
            plan=None,
            model=self.model,
            latency_ms=latency,
            success=False,
            error=f"CORTEX_CALL_FAILED: {last_error}",
        )

    def _parse_and_validate_response(self, raw_text: str, latency: float) -> CortexResponse:
        """Parse raw response text, validate schema invariants, and compile recovery plan."""
        try:
            data = json.loads(raw_text)
        except Exception as json_err:
            return CortexResponse(
                plan=None,
                raw_response=raw_text,
                model=self.model,
                latency_ms=latency,
                success=False,
                error=f"INVALID_JSON_RESPONSE: {json_err}",
            )

        # Check required fields
        # If response is wrapped in OpenAI/Anthropic format, extract inner content if needed
        plan_dict = data.get("plan", data)

        plan_id = plan_dict.get("plan_id", f"cortex-{uuid.uuid4().hex[:6]}")
        actions = plan_dict.get("actions")
        expected_outcome = plan_dict.get("expected_outcome", "Recover from failure state")
        stop_condition = plan_dict.get("stop_condition", "completed")
        confidence = float(plan_dict.get("confidence", 0.9))

        if not isinstance(actions, list):
            return CortexResponse(
                plan=None,
                raw_response=raw_text,
                model=self.model,
                latency_ms=latency,
                success=False,
                error="MALFORMED_PLAN: 'actions' field must be a list of action objects",
            )

        recovery_plan = RecoveryPlan(
            plan_id=plan_id,
            source=PlanSource.REAL_CORTEX,
            actions=actions,
            expected_outcome=expected_outcome,
            stop_condition=stop_condition,
            confidence=confidence,
            metadata={"raw_length": len(raw_text)},
        )

        # Validate through RecoveryCompiler
        try:
            self.recovery_compiler.validate_plan(recovery_plan)
        except RecoveryCompilationError as comp_err:
            return CortexResponse(
                plan=None,
                raw_response=raw_text,
                model=self.model,
                latency_ms=latency,
                success=False,
                error=f"RECOVERY_COMPILATION_REJECTED: {comp_err}",
            )

        return CortexResponse(
            plan=recovery_plan,
            raw_response=raw_text,
            model=self.model,
            latency_ms=latency,
            success=True,
        )
