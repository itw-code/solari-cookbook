"""Solari Cloud API driver for ephemeral browser sessions.

Implements the contract verified against the live API in docs/SOLARI_API.md:
- `POST /sessions` (201) returns `{sessionId, wsEndpoint, cdpEndpoint, expiresAt}`;
  `GET /sessions/{id}` names the id `id`, so both are accepted.
- `DELETE /sessions/{id}` (204) releases. Sessions otherwise live 5 hours and bill hourly,
  so every provisioned session is released on `terminate_all`, context exit, and process exit.
- Session ids and CDP/WS endpoints are signed capabilities: they are never logged or repr'd.
- Only 502/503/504 and network errors are retried; creates reuse one `Idempotency-Key`.

There is no silent mock fallback: without `SOLARI_API_KEY` construction fails, and a failed
live call raises `SolariAPIError`. Mock mode exists only for offline benchmark scripts and
must be requested with `mock=True`.

Desktops are not supported live: Solari desktops expose only screenshots and mouse/keyboard
input, with no accessibility tree for ARC to perceive.
"""

from __future__ import annotations

import atexit
import dataclasses
import enum
import json
import logging
import os
import time
import urllib.error
import urllib.request
import uuid
import weakref
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("arc_cua.cloud.solari_driver")

DEFAULT_BASE_URL = "https://api.getsolari.com"
RETRYABLE_STATUSES = frozenset({502, 503, 504})

HttpRequester = Callable[[urllib.request.Request, float], Optional[Dict[str, Any]]]


class SolariConfigError(RuntimeError):
    """Raised when the driver is constructed without the configuration it needs."""


class SolariAPIError(RuntimeError):
    """A Solari API call failed. `status` is None for network-level failures."""

    def __init__(self, message: str, status: Optional[int] = None, code: Optional[str] = None,
                 retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.code = code
        self.retryable = retryable


class SessionType(str, enum.Enum):
    """Supported Solari sandbox types."""
    BROWSER = "browser"
    DESKTOP = "desktop"


class SessionStatus(str, enum.Enum):
    """Lifecycle statuses for Solari sessions."""
    PENDING = "pending"
    RUNNING = "running"
    TERMINATING = "terminating"
    TERMINATED = "terminated"
    FAILED = "failed"


def _short(secret: Optional[str]) -> str:
    """Render a signed id/endpoint safely for logs: first 6 characters only."""
    if not secret:
        return "<none>"
    return f"{secret[:6]}…"


@dataclasses.dataclass(repr=False)
class SolariSession:
    """A provisioned Solari session. `session_id` and endpoints are secrets; see `__repr__`."""
    session_id: str
    session_type: SessionType
    status: SessionStatus
    cdp_endpoint: Optional[str] = None
    ws_endpoint: Optional[str] = None
    vnc_stream: Optional[str] = None
    replay_url: Optional[str] = None
    expires_at: Optional[str] = None
    region: Optional[str] = None
    is_mock: bool = False
    start_time: float = dataclasses.field(default_factory=time.time)
    end_time: Optional[float] = None
    compute_time_ms: float = 0.0
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def __repr__(self) -> str:
        return (f"SolariSession(id={_short(self.session_id)}, type={self.session_type.value}, "
                f"status={self.status.value}, mock={self.is_mock}, expires_at={self.expires_at})")

    def is_active(self) -> bool:
        """Return True if session is currently provisioned and running."""
        return self.status == SessionStatus.RUNNING

    def elapsed_ms(self) -> float:
        """Elapsed compute time in milliseconds (frozen once terminated)."""
        if self.end_time is not None:
            return self.compute_time_ms
        return max(0.0, (time.time() - self.start_time) * 1000.0)


# Backward-compatible alias
ArcSession = SolariSession


def _release_all_at_exit(ref: "weakref.ReferenceType[SolariCloudDriver]") -> None:
    driver = ref()
    if driver is not None:
        driver.terminate_all()


class SolariCloudDriver:
    """REST driver for Solari browser sessions."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        timeout_sec: float = 30.0,
        http_requester: Optional[HttpRequester] = None,
        mock: bool = False,
        max_retries: int = 2,
        backoff_sec: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
        register_atexit: bool = True,
    ):
        """Create a driver.

        Args:
            api_key: Solari console key (`slr_live_…`). Defaults to `SOLARI_API_KEY`.
            api_url: API base URL. Defaults to `SOLARI_BASE_URL`, then `SOLARI_API_URL`.
            timeout_sec: Per-request timeout.
            http_requester: Injectable transport `(request, timeout) -> parsed JSON | None`.
                It must raise `urllib.error.HTTPError` / `URLError` on failure.
            mock: Offline mode for benchmark scripts; makes no HTTP calls and needs no key.
            max_retries: Retries for transient failures (502/503/504, network errors).
            backoff_sec: Base delay for exponential backoff between retries.
            sleep: Injectable sleep, for tests.
            register_atexit: Release still-active sessions when the process exits.

        Raises:
            SolariConfigError: No API key and `mock` is False.
        """
        self.is_mock = mock
        self.api_key = "" if mock else (api_key if api_key is not None else os.getenv("SOLARI_API_KEY", "")).strip()
        if not mock and not self.api_key:
            raise SolariConfigError(
                "SOLARI_API_KEY is not set. Create a key at https://console.getsolari.com and export it, "
                "or pass mock=True for offline runs."
            )
        self.api_url = (
            api_url or os.getenv("SOLARI_BASE_URL") or os.getenv("SOLARI_API_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.timeout_sec = timeout_sec
        self.max_retries = max(0, max_retries)
        self.backoff_sec = backoff_sec
        self._sleep = sleep
        self._http_requester = http_requester or self._default_http_request
        self._sessions: Dict[str, SolariSession] = {}

        if register_atexit:
            atexit.register(_release_all_at_exit, weakref.ref(self))
        logger.info(f"SolariCloudDriver initialized [mode={'mock' if mock else 'live'}, api_url={self.api_url}]")

    def __repr__(self) -> str:
        return f"SolariCloudDriver(mode={'mock' if self.is_mock else 'live'}, api_url={self.api_url}, active={self.active_sessions_count()})"

    def __enter__(self) -> "SolariCloudDriver":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.terminate_all()

    # --- transport ---------------------------------------------------------------------------

    @staticmethod
    def _default_http_request(req: urllib.request.Request, timeout: float) -> Optional[Dict[str, Any]]:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data) if data else None

    def _scrub(self, text: str) -> str:
        return text.replace(self.api_key, "<redacted>") if self.api_key else text

    def _to_api_error(self, err: urllib.error.HTTPError, what: str) -> SolariAPIError:
        code = None
        message = ""
        try:
            raw = err.read().decode("utf-8", errors="replace")
        except Exception:
            raw = ""
        try:
            body = json.loads(raw)
            if isinstance(body, dict):
                code = body.get("code")
                message = body.get("error") or body.get("message") or ""
        except ValueError:
            message = raw[:200]
        detail = f"{what} failed: HTTP {err.code}" + (f" {code}" if code else "") + (f" — {message}" if message else "")
        return SolariAPIError(self._scrub(detail), status=err.code, code=code,
                              retryable=err.code in RETRYABLE_STATUSES)

    def _request(self, method: str, path: str, what: str, body: Optional[Dict[str, Any]] = None,
                 headers: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
        """Send one API call, retrying only transient failures."""
        all_headers = {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "arc-cua/0.1",
            **(headers or {}),
        }
        data = None
        if body is not None:
            all_headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")

        attempt = 0
        while True:
            req = urllib.request.Request(f"{self.api_url}{path}", data=data, headers=all_headers, method=method)
            try:
                return self._http_requester(req, self.timeout_sec)
            except urllib.error.HTTPError as err:
                error = self._to_api_error(err, what)
            except urllib.error.URLError as err:
                error = SolariAPIError(self._scrub(f"{what} failed: network error {err.reason}"), retryable=True)
            if not error.retryable or attempt >= self.max_retries:
                raise error
            delay = self.backoff_sec * (2 ** attempt)
            attempt += 1
            logger.warning(f"{error} — retry {attempt}/{self.max_retries} in {delay:.1f}s")
            self._sleep(delay)

    # --- lifecycle ---------------------------------------------------------------------------

    def provision_browser(
        self,
        stealth: bool = False,
        recording: bool = False,
        profile_id: Optional[str] = None,
        proxy: Optional[Any] = None,
        captcha: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SolariSession:
        """Create a Solari browser session.

        Only documented create fields are sent, and only when set, so a default call posts `{}`.
        Stealth, proxies, and captcha require a paid plan (the API answers 402 otherwise).

        Raises:
            SolariAPIError: The API rejected the request or returned no `cdpEndpoint`.
        """
        if self.is_mock:
            return self._track(SolariSession(
                session_id=f"mock-brw-{uuid.uuid4().hex[:12]}",
                session_type=SessionType.BROWSER,
                status=SessionStatus.RUNNING,
                cdp_endpoint="ws://127.0.0.1:9222/devtools/browser/mock",
                is_mock=True,
                metadata=dict(metadata or {}),
            ))

        payload: Dict[str, Any] = {}
        if stealth:
            payload["stealth"] = True
        if recording:
            payload["recording"] = True
        if profile_id:
            payload["profileId"] = profile_id
        if proxy is not None:
            payload["proxy"] = proxy
        if captcha:
            payload["captcha"] = True

        res = self._request("POST", "/sessions", "Create browser session", body=payload,
                            headers={"Idempotency-Key": str(uuid.uuid4())}) or {}
        sid = res.get("sessionId") or res.get("id")
        if not sid:
            raise SolariAPIError("Create browser session returned no session id")

        session = self._track(SolariSession(
            session_id=sid,
            session_type=SessionType.BROWSER,
            status=SessionStatus.RUNNING,
            cdp_endpoint=res.get("cdpEndpoint"),
            ws_endpoint=res.get("wsEndpoint"),
            replay_url=res.get("replay"),
            expires_at=res.get("expiresAt"),
            region=res.get("region"),
            metadata={"stealth": stealth, "recording": recording, **(metadata or {})},
        ))
        if not session.cdp_endpoint:
            self.terminate(sid)
            raise SolariAPIError("Create browser session returned no cdpEndpoint; session released")

        logger.info(f"Provisioned Solari browser session {_short(sid)} (expires {session.expires_at})")
        return session

    def provision_desktop(
        self,
        resolution: str = "1920x1080",
        os_flavor: str = "ubuntu",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SolariSession:
        """Mock-only desktop session for offline OSWorld benchmark accounting.

        Raises:
            NotImplementedError: In live mode. Solari desktops expose no accessibility tree,
                so ARC has nothing to perceive; see docs/SOLARI_API.md.
        """
        if not self.is_mock:
            raise NotImplementedError(
                "Live Solari desktops are not supported: they expose only screenshots and mouse/keyboard "
                "input, with no accessibility tree for ARC to perceive. Use mock=True for offline benchmarks."
            )
        return self._track(SolariSession(
            session_id=f"mock-desk-{uuid.uuid4().hex[:12]}",
            session_type=SessionType.DESKTOP,
            status=SessionStatus.RUNNING,
            vnc_stream="vnc://127.0.0.1:5900/mock",
            is_mock=True,
            metadata={"resolution": resolution, "os_flavor": os_flavor, **(metadata or {})},
        ))

    def _track(self, session: SolariSession) -> SolariSession:
        self._sessions[session.session_id] = session
        return session

    def terminate(self, session_id: str) -> bool:
        """Release a session. Returns True once it is released (idempotent), False on failure.

        A 404 means the session is already gone and counts as released. On any other failure
        the session stays active so `terminate_all` or process exit can retry it.
        """
        session = self._sessions.get(session_id)
        if not session:
            logger.warning(f"Attempted to terminate unknown session {_short(session_id)}")
            return False
        if session.status == SessionStatus.TERMINATED:
            return True

        if not session.is_mock:
            try:
                self._request("DELETE", f"/sessions/{session_id}", "Release browser session")
            except SolariAPIError as err:
                if err.status != 404:
                    logger.warning(f"Release of session {_short(session_id)} failed: {err}")
                    return False

        now = time.time()
        session.end_time = now
        session.compute_time_ms = max(0.0, (now - session.start_time) * 1000.0)
        session.status = SessionStatus.TERMINATED
        logger.info(f"Released session {_short(session_id)} (compute {session.compute_time_ms:.0f} ms)")
        return True

    def terminate_all(self) -> int:
        """Release every active session. Returns the number released."""
        return sum(1 for s in list(self._sessions.values()) if s.is_active() and self.terminate(s.session_id))

    # --- accessors ---------------------------------------------------------------------------

    def get_session(self, session_id: str) -> Optional[SolariSession]:
        """Look up a tracked session by id."""
        return self._sessions.get(session_id)

    def list_active_sessions(self) -> List[SolariSession]:
        """Return all currently active sessions."""
        return [s for s in self._sessions.values() if s.is_active()]

    def active_sessions_count(self) -> int:
        """Return count of currently running sessions."""
        return len(self.list_active_sessions())

    def get_cdp_endpoint(self, session_id: str) -> str:
        """Return the CDP endpoint for a session (a secret: do not log it)."""
        session = self._sessions.get(session_id)
        if not session:
            raise KeyError(f"Session {_short(session_id)} not found")
        if not session.cdp_endpoint:
            raise ValueError(f"Session {_short(session_id)} has no CDP endpoint")
        return session.cdp_endpoint

    def get_vnc_stream(self, session_id: str) -> str:
        """Return the VNC stream URL for a (mock) desktop session."""
        session = self._sessions.get(session_id)
        if not session:
            raise KeyError(f"Session {_short(session_id)} not found")
        if not session.vnc_stream:
            raise ValueError(f"Session {_short(session_id)} has no VNC stream")
        return session.vnc_stream

    def get_replay_url(self, session_id: str) -> Optional[str]:
        """Return the replay URL if the create response included one."""
        session = self._sessions.get(session_id)
        return session.replay_url if session else None

    def get_compute_time_ms(self, session_id: str) -> float:
        """Elapsed or finalized compute time for one session."""
        session = self._sessions.get(session_id)
        return session.elapsed_ms() if session else 0.0

    def total_compute_ms(self) -> float:
        """Cumulative compute milliseconds across all tracked sessions."""
        return sum(s.elapsed_ms() for s in self._sessions.values())

    get_total_compute_time_ms = total_compute_ms


# Backward-compatible alias
ArcCloudDriver = SolariCloudDriver
