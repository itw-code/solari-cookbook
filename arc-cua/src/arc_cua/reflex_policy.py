"""Reflex policy: one small model call per action, choosing an operation and a [#N] target.

The Jev pattern (Browser Use / TypeSafe) on ARC's perception: the model sees only the goal,
the current budgeted tree and the last few actions, and answers with one JSON object. No
chat history, no tool schemas, no prose, so input stays near the tree's ~1,200 tokens and
output near 20 tokens. `arc_act` already returns the page after each action, so every step
is exactly one model call plus one ARC action.

Works with any OpenAI-compatible chat endpoint. The key comes from the caller (read it from
an environment variable); nothing here logs it.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

SYSTEM = """\
You control a web browser. Each turn you see the goal, the current page as an accessibility tree, and your previous actions.
Lines like `[#12] link "new"` are elements you can act on by index.
Answer with ONE JSON object and nothing else:
{"op":"click","index":N}
{"op":"fill","index":N,"value":"text","enter":true}   (enter submits after typing; omit it to only type)
{"op":"select","index":N,"value":"option label"}
{"op":"press_key","value":"Enter"}
{"op":"query","value":"words"}   (the tree is truncated and the element you need is not shown: list matching elements)
{"op":"scroll"}
{"op":"done"}   (the goal is visibly achieved on the current page)
{"op":"fail","value":"reason"}
First check Previous actions: if the last one already achieved the goal (e.g. the requested link was clicked and the page changed), answer {"op":"done"}.
Pick the element whose role and name best match the goal. Do not repeat an action that did not change the page."""

OPS = {"click", "fill", "select", "press_key", "query", "scroll", "done", "fail"}


@dataclass
class Step:
    op: str
    index: Optional[int] = None
    value: Optional[str] = None
    model_ms: float = 0.0
    act_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    note: str = ""


@dataclass
class Episode:
    goal: str
    steps: List[Step] = field(default_factory=list)
    finished: bool = False
    failed_reason: Optional[str] = None
    final_url: str = ""
    final_tree: str = ""
    seconds: float = 0.0
    error: Optional[str] = None

    @property
    def model_seconds(self) -> float:
        return sum(s.model_ms for s in self.steps) / 1000

    @property
    def act_seconds(self) -> float:
        return sum(s.act_ms for s in self.steps) / 1000


class ChatClient:
    """Minimal OpenAI-compatible /chat/completions client (stdlib only)."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 30.0, max_tokens: int = 256,
                 extra: Optional[Dict[str, Any]] = None, retries: int = 1):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self._key = api_key
        self.model = model
        self.timeout = timeout
        # Room for models that reason before answering; a 60-token cap left them with no JSON.
        self.max_tokens = max_tokens
        self.extra = extra or {}  # e.g. {"reasoning_effort": "none"} to disable thinking
        self.retries = retries

    def complete(self, system: str, user: str) -> Dict[str, Any]:
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0,
            "max_tokens": self.max_tokens,
            **self.extra,
        }).encode("utf-8")
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(self.url, data=body, method="POST", headers={
                "Content-Type": "application/json", "Authorization": f"Bearer {self._key}"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                detail = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"
                if e.code < 500 or attempt == self.retries:
                    raise RuntimeError(detail) from None
            except (TimeoutError, urllib.error.URLError) as e:
                if attempt == self.retries:
                    raise RuntimeError(f"request failed: {e}") from None
        msg = (data.get("choices") or [{}])[0].get("message") or {}
        usage = data.get("usage") or {}
        return {"text": msg.get("content") or "", "input_tokens": int(usage.get("prompt_tokens") or 0),
                "output_tokens": int(usage.get("completion_tokens") or 0)}


def parse_action(text: str) -> Dict[str, Any]:
    """First JSON object in the reply (models sometimes wrap it in prose or code fences)."""
    m = re.search(r"\{.*?\}", text, re.S)
    if not m:
        raise ValueError(f"no JSON in reply: {text[:120]!r}")
    action = json.loads(m.group(0))
    op = str(action.get("op", "")).lower()
    if op not in OPS:
        raise ValueError(f"unknown op {op!r}")
    action["op"] = op
    if action.get("index") is not None:
        action["index"] = int(action["index"])
    return action


def run_episode(session: Any, client: ChatClient, goal: str, url: str, max_steps: int = 10,
                settle_ms: float = 3000.0, history_len: int = 4) -> Episode:
    """Drive `session` (an ARC BrowserSession) toward `goal`, one model call per step."""
    ep = Episode(goal=goal)
    start = time.perf_counter()
    try:
        # Keep whatever backend the caller opened (switching backend would restart the browser).
        session.open(url=url, backend=session.backend or "local")
        tree = f"URL: {session.page.url}\n" + session.inspect(settle_ms=settle_ms)["text"]
        extra = ""
        history: List[str] = []
        for _ in range(max_steps):
            prompt = (f"Goal: {goal}\n\nPrevious actions:\n" + ("\n".join(history[-history_len:]) or "(none)")
                      + f"\n\nCurrent page:\n{tree}" + (f"\n\n{extra}" if extra else "") + "\n\nYour action (JSON):")
            t = time.perf_counter()
            reply = client.complete(SYSTEM, prompt)
            step = Step(op="?", model_ms=(time.perf_counter() - t) * 1000,
                        input_tokens=reply["input_tokens"], output_tokens=reply["output_tokens"])
            ep.steps.append(step)
            try:
                action = parse_action(reply["text"])
            except (ValueError, json.JSONDecodeError) as e:
                step.note = f"unparseable: {e}"
                history.append(f"- (invalid reply: answer with one JSON object)")
                continue
            step.op, step.index, step.value = action["op"], action.get("index"), action.get("value")
            extra = ""
            if step.op == "done":
                ep.finished = True
                break
            if step.op == "fail":
                ep.failed_reason = str(step.value or "")
                break
            t = time.perf_counter()
            if step.op == "query":
                extra = session.inspect(settle_ms=0, query=str(step.value or ""))["text"]
                summary = f"- query {step.value!r}: matches listed below the page"
            else:
                # Name the element in the history: "click #24" alone did not tell small models
                # that they had already clicked the link the goal asked for.
                target = {**session._evicted_map, **session._index_map}.get(step.index) if step.index is not None else None
                label = f"{target.get('role')} {json.dumps(target.get('name') or '')}" if target else ""
                verb = "press_key" if step.op == "press_key" else step.op
                result = session.act(verb, index=step.index, value=step.value,
                                     observe=not action.get("enter"), settle_ms=settle_ms)
                if action.get("enter") and step.op == "fill":
                    result = session.act("press_key", value="Enter", observe=True, settle_ms=settle_ms)
                tree = result.get("tree") or tree
                summary = (f"- {step.op} {('#' + str(step.index)) if step.index is not None else ''} {label} "
                           f"{json.dumps(step.value) if step.value else ''} -> "
                           f"{'page changed' if result.get('state_changed') or result.get('url_changed') else 'NO CHANGE'}"
                           + (f", now at {result.get('url')}" if result.get("url_changed") else "")
                           + (f", error: {result['error']}" if result.get("error") else ""))
            step.act_ms = (time.perf_counter() - t) * 1000
            history.append(" ".join(summary.split()))
        ep.final_url = session.page.url
        ep.final_tree = tree
    except Exception as e:  # a crashed episode is a failed episode
        ep.error = f"{type(e).__name__}: {e}"[:300]
        try:
            ep.final_url = session.page.url
        except Exception:
            pass
    ep.seconds = time.perf_counter() - start
    return ep
