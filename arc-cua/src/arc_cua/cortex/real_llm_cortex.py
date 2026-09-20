"""Real Cortex LLM Client Adapter for ARC (Phase 5 Task 2).

Connects the ARC orchestrator to real frontier or System-1 reasoning models
(TypeSafe Jev, OpenAI GPT-4o, Anthropic Claude).
- Requires CORTEX_MODE=real for instantiation (enforces safety guardrail).
- Formats EscalationPayload into strict structured reasoning prompts.
- Parses LLM JSON output into RecoveryPlan and compiles through RecoveryCompiler.
- Accurately tracks exact input/output tokens and calculates dollar costs.
- Implements exponential backoff retries with circuit breaker timeouts.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from ..schemas import (
    ActionStep,
    CortexResponse,
    EscalationPayload,
    PlanSource,
    RecoveryPlan,
)
from .cortex_interface import CortexClient
from .recovery_compiler import RecoveryCompilationError, RecoveryCompiler

logger = logging.getLogger("arc_cua.cortex.real_llm")

# Pricing table: (input_cost_per_million, output_cost_per_million)
PROVIDER_PRICING: Dict[str, Tuple[float, float]] = {
    # OpenAI models
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "o1": (15.00, 60.00),
    "o3-mini": (1.10, 4.40),
    # Anthropic models
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-3-5-sonnet-20241022": (3.00, 15.00),
    "claude-3-5-haiku": (0.80, 4.00),
    "claude-3-haiku": (0.25, 1.25),
    "claude-3-opus": (15.00, 75.00),
    # TypeSafe Jev models
    "jev": (1.50, 6.00),
    "jev-reasoner-v1": (1.50, 6.00),
    "jev-fast": (0.50, 2.00),
}

DEFAULT_ENDPOINTS: Dict[str, str] = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "anthropic": "https://api.anthropic.com/v1/messages",
    "jev": "https://api.typesafe.com/v1/cortex/reason",
}


@dataclasses.dataclass
class TokenCostRecord:
    """Detailed token usage and calculated dollar cost for a single reasoning invocation."""
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    input_cost_usd: float
    output_cost_usd: float
    total_cost_usd: float


class RealLlmCortex(CortexClient):
    """Real LLM Cortex reasoning client for frontier models with strict cost accounting."""

    def __init__(
        self,
        mode: Optional[str] = None,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        endpoint: Optional[str] = None,
        timeout_ms: Optional[int] = None,
        max_retries: int = 3,
        recovery_compiler: Optional[RecoveryCompiler] = None,
        http_requester: Optional[Callable[[urllib.request.Request, float], Dict[str, Any]]] = None,
    ):
        """Initialize RealLlmCortex client with environment configuration.

        Args:
            mode: Operating mode. MUST be 'real' (or CORTEX_MODE=real env var).
            provider: LLM provider ('jev', 'openai', 'anthropic'). Defaults to CORTEX_PROVIDER.
            api_key: Provider API key. Defaults to CORTEX_API_KEY.
            model: Model identifier. Defaults to CORTEX_MODEL.
            endpoint: Custom API endpoint URL. Defaults to CORTEX_ENDPOINT or provider standard.
            timeout_ms: Request timeout in milliseconds.
            max_retries: Maximum number of retries on transient errors.
            recovery_compiler: Instance of RecoveryCompiler for plan validation.
            http_requester: Optional dependency-injected HTTP caller for deterministic testing.

        Raises:
            ValueError: If CORTEX_MODE != 'real' or required credentials are missing.
        """
        # Safety gate: Require CORTEX_MODE == 'real'
        resolved_mode = (mode or os.getenv("CORTEX_MODE", "mock")).lower()
        if resolved_mode != "real":
            raise ValueError(
                f"RealLlmCortex instantiation rejected: CORTEX_MODE must be 'real' (found '{resolved_mode}'). "
                f"To run real LLM calls, explicitly configure CORTEX_MODE=real."
            )

        self.mode = resolved_mode
        self.provider = (provider or os.getenv("CORTEX_PROVIDER", "openai")).lower()
        self.model = model or os.getenv("CORTEX_MODEL", self._default_model_for_provider(self.provider))
        self.api_key = (api_key or os.getenv("CORTEX_API_KEY", "")).strip()
        self.endpoint = (endpoint or os.getenv("CORTEX_ENDPOINT", DEFAULT_ENDPOINTS.get(self.provider, ""))).strip()
        self.timeout_ms = int(timeout_ms or os.getenv("CORTEX_TIMEOUT_MS", "30000"))
        self.max_retries = max_retries
        self.recovery_compiler = recovery_compiler or RecoveryCompiler()
        self._http_requester = http_requester or self._default_http_request

        # Cost & usage cumulative tracking
        self.cumulative_input_tokens: int = 0
        self.cumulative_output_tokens: int = 0
        self.cumulative_cost_usd: float = 0.0
        self.invocation_records: List[TokenCostRecord] = []

        masked_key = f"{self.api_key[:4]}...{self.api_key[-4:]}" if len(self.api_key) >= 8 else "***"
        logger.info(
            f"Initialized RealLlmCortex [provider={self.provider}, model={self.model}, "
            f"endpoint={self.endpoint}, key={masked_key}, timeout={self.timeout_ms}ms]"
        )

    @classmethod
    def _default_model_for_provider(cls, provider: str) -> str:
        """Select sensible default model for provider."""
        if provider == "openai":
            return "gpt-4o"
        elif provider == "anthropic":
            return "claude-3-5-sonnet-20241022"
        elif provider == "jev":
            return "jev-reasoner-v1"
        return "gpt-4o"

    def _default_http_request(self, req: urllib.request.Request, timeout: float) -> Dict[str, Any]:
        """Execute request using urllib and parse JSON response."""
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data) if data else {}

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> TokenCostRecord:
        """Calculate exact USD cost for token usage based on provider pricing table."""
        # Match model in pricing table, falling back to prefix or provider default
        pricing = PROVIDER_PRICING.get(self.model)
        if not pricing:
            for k, v in PROVIDER_PRICING.items():
                if k in self.model or self.model in k:
                    pricing = v
                    break
        if not pricing:
            pricing = PROVIDER_PRICING.get(self.provider, (2.50, 10.00))

        in_rate_per_token = pricing[0] / 1_000_000.0
        out_rate_per_token = pricing[1] / 1_000_000.0

        in_cost = input_tokens * in_rate_per_token
        out_cost = output_tokens * out_rate_per_token
        total_cost = in_cost + out_cost

        record = TokenCostRecord(
            provider=self.provider,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            input_cost_usd=round(in_cost, 6),
            output_cost_usd=round(out_cost, 6),
            total_cost_usd=round(total_cost, 6),
        )

        self.cumulative_input_tokens += input_tokens
        self.cumulative_output_tokens += output_tokens
        self.cumulative_cost_usd += total_cost
        self.invocation_records.append(record)
        return record

    def format_prompts(self, payload: EscalationPayload) -> Tuple[str, str]:
        """Format EscalationPayload into strict system and user prompts for JSON recovery plan generation."""
        system_prompt = (
            "You are the ARC Cortex Reasoning Engine, an expert autonomous recovery agent.\n"
            "A fast local reflex agent has stalled, encountered a loop, or suffered an execution failure.\n"
            "Your task is to analyze the failure context, state representation, and step history, and output a "
            "precise, minimal, executable JSON RecoveryPlan to unblock the agent.\n\n"
            "CRITICAL CONSTRAINTS:\n"
            "1. You MUST output a SINGLE valid JSON object and NOTHING else. No conversational prose or introductory text.\n"
            "2. Allowed action verbs: CLICK, TYPE, SELECT, SCROLL, PRESS_KEY, GOTO, WAIT, ASSERT_VISIBLE, ASSERT_TEXT, NOOP, ESCALATE.\n"
            "3. Actions requiring target: CLICK, TYPE, SELECT, ASSERT_VISIBLE, ASSERT_TEXT require a valid CSS or text selector in 'target_selector'.\n"
            "4. Value requirements: TYPE requires text string in 'value'. SELECT requires option value. ASSERT_TEXT requires expected text in 'value'.\n"
            "5. Safe URLs only: GOTO must start with http:// or https://. Never javascript: or file:.\n"
            "6. Bounded waits: WAIT duration must be <= 60000 ms.\n\n"
            "REQUIRED JSON SCHEMA:\n"
            "{\n"
            '  "plan_id": "cortex-recovery-...",\n'
            '  "expected_outcome": "Description of intended post-recovery state",\n'
            '  "stop_condition": "state_delta_verified | element_visible | url_changed",\n'
            '  "confidence": 0.95,\n'
            '  "actions": [\n'
            '    {"verb": "CLICK", "target_selector": "#id", "value": null},\n'
            '    {"verb": "TYPE", "target_selector": "input[name=q]", "value": "search query"}\n'
            "  ]\n"
            "}"
        )

        step_history = payload.step_history or []
        recent_steps = []
        for step in step_history[-6:]:
            recent_steps.append({
                "step": getattr(step, "step_number", getattr(step, "step_index", 1)),
                "verb": getattr(step, "verb", ""),
                "target": getattr(step, "target_selector", getattr(step, "target", None)),
                "value": getattr(step, "value", None),
                "success": getattr(step, "success", True),
                "error": getattr(step, "error", None),
            })

        current_hash = hex(payload.current_state.simhash) if payload.current_state else "0x0"
        ui_yaml = getattr(payload.current_state, "yaml_representation", None) or "None"

        user_prompt_data = {
            "task_goal": payload.task_goal,
            "escalation_reason": payload.reason.value if hasattr(payload.reason, "value") else str(payload.reason),
            "escalation_id": payload.escalation_id,
            "current_state_hash": current_hash,
            "failure_details": payload.failure_details or {},
            "recent_actions": recent_steps,
            "ui_state_snippet": ui_yaml[:1200] if len(ui_yaml) > 1200 else ui_yaml,
        }

        user_prompt = (
            f"DIAGNOSTIC ESCALATION CONTEXT:\n"
            f"{json.dumps(user_prompt_data, indent=2)}\n\n"
            f"Generate the JSON RecoveryPlan to restore execution progress towards the goal: '{payload.task_goal}'."
        )

        return system_prompt, user_prompt

    def _build_http_request(self, system_prompt: str, user_prompt: str) -> urllib.request.Request:
        """Construct provider-specific HTTP request."""
        if not self.endpoint:
            raise ValueError(f"No endpoint configured for provider '{self.provider}'.")

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Arc-Hybrid-CUA/1.0",
        }

        if self.provider == "openai":
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            body = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.1,
            }
        elif self.provider == "anthropic":
            if self.api_key:
                headers["x-api-key"] = self.api_key
            headers["anthropic-version"] = "2023-06-01"
            body = {
                "model": self.model,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
                "max_tokens": 2048,
                "temperature": 0.1,
            }
        elif self.provider == "jev":
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            body = {
                "model": self.model,
                "system": system_prompt,
                "prompt": user_prompt,
                "format": "json",
                "temperature": 0.1,
            }
        else:
            # Generic OpenAI-compatible
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            body = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.1,
            }

        return urllib.request.Request(
            self.endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )

    def _extract_text_and_usage(self, response_data: Dict[str, Any]) -> Tuple[str, int, int]:
        """Extract response text content and token usage from provider response."""
        input_tokens = 0
        output_tokens = 0
        raw_text = ""

        if self.provider == "openai":
            choices = response_data.get("choices", [])
            if choices and "message" in choices[0]:
                raw_text = choices[0]["message"].get("content", "")
            usage = response_data.get("usage", {})
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)

        elif self.provider == "anthropic":
            content = response_data.get("content", [])
            if content and isinstance(content, list):
                raw_text = content[0].get("text", "")
            usage = response_data.get("usage", {})
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)

        elif self.provider == "jev":
            raw_text = response_data.get("content") or response_data.get("response") or json.dumps(response_data)
            usage = response_data.get("usage", {})
            input_tokens = usage.get("prompt_tokens", usage.get("input_tokens", 0))
            output_tokens = usage.get("completion_tokens", usage.get("output_tokens", 0))

        else:
            # Fallback
            choices = response_data.get("choices", [])
            if choices and "message" in choices[0]:
                raw_text = choices[0]["message"].get("content", "")
            elif "content" in response_data:
                raw_text = str(response_data["content"])
            else:
                raw_text = json.dumps(response_data)
            usage = response_data.get("usage", {})
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)

        return raw_text, input_tokens, output_tokens

    def _parse_llm_json(self, raw_text: str) -> Dict[str, Any]:
        """Clean markdown wrapping and parse raw LLM text into JSON dict."""
        text = raw_text.strip()
        # Strip markdown ```json ... ``` code fences
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        if match:
            text = match.group(1).strip()

        # Parse JSON
        return json.loads(text)

    def recover(self, payload: EscalationPayload) -> CortexResponse:
        """Execute real reasoning recovery with timeout and retries."""
        start_time = time.perf_counter()
        timeout_sec = max(1.0, self.timeout_ms / 1000.0)

        system_prompt, user_prompt = self.format_prompts(payload)

        req = self._build_http_request(system_prompt, user_prompt)
        last_error: Optional[str] = None
        backoff_sec = 0.5

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(
                    f"Dispatching real Cortex LLM request (attempt {attempt}/{self.max_retries}) "
                    f"[provider={self.provider}, model={self.model}]"
                )
                res_data = self._http_requester(req, timeout_sec)
                latency = (time.perf_counter() - start_time) * 1000.0

                raw_text, in_tokens, out_tokens = self._extract_text_and_usage(res_data)
                cost_rec = self.calculate_cost(in_tokens, out_tokens)

                # Parse JSON recovery plan
                try:
                    plan_data = self._parse_llm_json(raw_text)
                except Exception as json_err:
                    return CortexResponse(
                        plan=None,
                        raw_response=raw_text,
                        model=self.model,
                        latency_ms=latency,
                        tokens_used=cost_rec.total_tokens,
                        cost_usd=cost_rec.total_cost_usd,
                        success=False,
                        error=f"JSON_PARSE_ERROR: {json_err}",
                        metadata={"cost_record": dataclasses.asdict(cost_rec)},
                    )

                # If wrapped under 'plan', extract inner object
                inner_plan = plan_data.get("plan", plan_data)
                plan_id = inner_plan.get("plan_id", f"cortex-rec-{uuid.uuid4().hex[:8]}")
                actions = inner_plan.get("actions", [])
                expected_outcome = inner_plan.get("expected_outcome", "Restore execution progress")
                stop_condition = inner_plan.get("stop_condition", "state_delta_verified")
                confidence = float(inner_plan.get("confidence", 0.90))

                recovery_plan = RecoveryPlan(
                    plan_id=plan_id,
                    source=PlanSource.REAL_CORTEX,
                    actions=actions,
                    expected_outcome=expected_outcome,
                    stop_condition=stop_condition,
                    confidence=confidence,
                    metadata={
                        "provider": self.provider,
                        "model": self.model,
                        "input_tokens": in_tokens,
                        "output_tokens": out_tokens,
                    },
                )

                # Validate through RecoveryCompiler
                try:
                    self.recovery_compiler.validate_plan(recovery_plan)
                except RecoveryCompilationError as comp_err:
                    logger.warning(f"RecoveryCompiler rejected LLM plan: {comp_err}")
                    return CortexResponse(
                        plan=None,
                        raw_response=raw_text,
                        model=self.model,
                        latency_ms=latency,
                        tokens_used=cost_rec.total_tokens,
                        cost_usd=cost_rec.total_cost_usd,
                        success=False,
                        error=f"RECOVERY_COMPILATION_REJECTED: {comp_err}",
                        metadata={"cost_record": dataclasses.asdict(cost_rec)},
                    )

                logger.info(
                    f"Successfully compiled real Cortex recovery plan '{plan_id}' "
                    f"({len(actions)} actions, tokens={cost_rec.total_tokens}, cost=${cost_rec.total_cost_usd:.6f})"
                )

                return CortexResponse(
                    plan=recovery_plan,
                    raw_response=raw_text,
                    model=self.model,
                    latency_ms=latency,
                    tokens_used=cost_rec.total_tokens,
                    cost_usd=cost_rec.total_cost_usd,
                    success=True,
                    metadata={"cost_record": dataclasses.asdict(cost_rec)},
                )

            except urllib.error.HTTPError as http_err:
                last_error = f"HTTPError {http_err.code}: {http_err.reason}"
                logger.error(f"Cortex LLM HTTP error on attempt {attempt}: {last_error}")
                if http_err.code in {400, 401, 403}:  # Client credentials / invalid format, do not retry
                    break
            except urllib.error.URLError as url_err:
                last_error = f"URLError: {url_err.reason}"
                logger.warning(f"Cortex LLM network error on attempt {attempt}: {last_error}")
            except Exception as e:
                last_error = f"RequestError: {e}"
                logger.warning(f"Cortex LLM generic error on attempt {attempt}: {last_error}")

            if attempt < self.max_retries:
                time.sleep(backoff_sec)
                backoff_sec *= 2.0

        latency = (time.perf_counter() - start_time) * 1000.0
        return CortexResponse(
            plan=None,
            model=self.model,
            latency_ms=latency,
            tokens_used=0,
            cost_usd=0.0,
            success=False,
            error=f"CORTEX_CALL_FAILED: {last_error}",
        )


def create_real_cortex_client(**kwargs) -> Optional[RealLlmCortex]:
    """Factory helper to safely instantiate RealLlmCortex only if CORTEX_MODE=real.

    Returns:
        RealLlmCortex instance if CORTEX_MODE=real, else None.
    """
    mode = (kwargs.get("mode") or os.getenv("CORTEX_MODE", "mock")).lower()
    if mode != "real":
        logger.info(f"CORTEX_MODE is '{mode}': skipping RealLlmCortex instantiation.")
        return None
    return RealLlmCortex(**kwargs)
