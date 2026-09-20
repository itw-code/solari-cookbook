"""Solari Cloud API Driver for Ephemeral MicroVM & Browser Provisioning (Phase 5).

Manages remote stealth browsers and desktop sandboxes via the Solari Cloud REST API.
- Supports provisioning ephemeral stealth browser sessions with CDP endpoints.
- Supports provisioning desktop sandboxes with VNC and AT-SPI accessibility streams.
- Automatically captures session recording and replay URLs.
- Gracefully falls back to local mock mode if SOLARI_API_KEY is not configured.
- Tracks precise compute duration (ms) per session for cost ledger integration.
"""

from __future__ import annotations

import dataclasses
import enum
import json
import logging
import os
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("arc_cua.cloud.solari_driver")


class SessionType(str, enum.Enum):
    """Supported Solari Cloud ephemeral sandbox types."""
    BROWSER = "browser"
    DESKTOP = "desktop"


class SessionStatus(str, enum.Enum):
    """Lifecycle statuses for Solari Cloud sandbox sessions."""
    PENDING = "pending"
    RUNNING = "running"
    TERMINATING = "terminating"
    TERMINATED = "terminated"
    FAILED = "failed"


@dataclasses.dataclass
class SolariSession:
    """Represents a provisioned Solari Cloud sandbox session."""
    session_id: str
    session_type: SessionType
    status: SessionStatus
    cdp_endpoint: Optional[str] = None
    vnc_stream: Optional[str] = None
    replay_url: Optional[str] = None
    region: str = "us-east-1"
    is_mock: bool = False
    start_time: float = dataclasses.field(default_factory=time.time)
    end_time: Optional[float] = None
    compute_time_ms: float = 0.0
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def is_active(self) -> bool:
        """Return True if session is currently provisioned and running."""
        return self.status == SessionStatus.RUNNING

    def elapsed_ms(self) -> float:
        """Calculate elapsed compute time in milliseconds."""
        if self.end_time is not None:
            return self.compute_time_ms
        return max(0.0, (time.time() - self.start_time) * 1000.0)


# Backward-compatible alias
ArcSession = SolariSession


class SolariCloudDriver:
    """REST driver for managing Solari Cloud browser and desktop sandboxes."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        region: Optional[str] = None,
        api_url: Optional[str] = None,
        timeout_sec: float = 30.0,
        http_requester: Optional[Callable[[urllib.request.Request, float], Dict[str, Any]]] = None,
    ):
        """Initialize SolariCloudDriver with credentials or fallback to mock mode."""
        self.api_key = (
            api_key
            if api_key is not None
            else (os.getenv("SOLARI_API_KEY") or os.getenv("ARC_API_KEY", "")).strip()
        )
        self.region = (
            region
            or os.getenv("SOLARI_REGION")
            or os.getenv("ARC_REGION", "us-east-1")
        ).strip()
        self.api_url = (
            api_url
            or os.getenv("SOLARI_API_URL")
            or os.getenv("ARC_API_URL", "https://api.getsolari.com")
        ).rstrip("/")
        self.timeout_sec = timeout_sec
        self._http_requester = http_requester or self._default_http_request

        # Active and historical sessions indexed by session_id
        self._sessions: Dict[str, SolariSession] = {}
        if not self.api_key:
            self.is_mock = True
            logger.info("SOLARI_API_KEY not detected: SolariCloudDriver initialized in MOCK mode.")
        else:
            self.is_mock = False
            masked_key = f"{self.api_key[:4]}...{self.api_key[-4:]}" if len(self.api_key) >= 8 else "***"
            logger.info(
                f"SolariCloudDriver initialized in LIVE mode [region={self.region}, "
                f"api_url={self.api_url}, api_key={masked_key}]"
            )

    def _default_http_request(self, req: urllib.request.Request, timeout: float) -> Dict[str, Any]:
        """Perform HTTP request using standard library urllib."""
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data) if data else {}

    def provision_browser(
        self,
        stealth: bool = True,
        viewport: Optional[Dict[str, int]] = None,
        timeout_sec: Optional[float] = None,
        session_id: Optional[str] = None,
        record_session: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SolariSession:
        """Provision an ephemeral stealth browser session in Solari Cloud."""
        sid = session_id or f"solari-brw-{uuid.uuid4().hex[:12]}"
        vp = viewport or {"width": 1280, "height": 720}
        now = time.time()

        if self.is_mock:
            cdp_port = 9222
            session = SolariSession(
                session_id=sid,
                session_type=SessionType.BROWSER,
                status=SessionStatus.RUNNING,
                cdp_endpoint=f"ws://127.0.0.1:{cdp_port}/devtools/browser/{sid}",
                vnc_stream=None,
                replay_url=f"https://cloud.arc.ai/replay/{sid}" if record_session else None,
                region=self.region,
                is_mock=True,
                start_time=now,
                metadata={
                    "stealth": stealth,
                    "viewport": vp,
                    "record_session": record_session,
                    **(metadata or {}),
                },
            )
            self._sessions[sid] = session
            logger.debug(f"[MOCK] Provisioned Solari stealth browser session {sid}")
            return session

        # Real Solari API request
        payload = {
            "session_id": sid,
            "session_type": "browser",
            "region": self.region,
            "stealth": stealth,
            "viewport": vp,
            "record_session": record_session,
            "metadata": metadata or {},
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "ARC-Autonomous-Agent/1.0",
        }
        url = f"{self.api_url}/sessions"
        timeout = timeout_sec or self.timeout_sec

        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
            res_data = self._http_requester(req, timeout)

            actual_sid = res_data.get("sessionId") or res_data.get("session_id") or sid
            cdp_endpoint = (
                res_data.get("cdpEndpoint")
                or res_data.get("cdp_endpoint")
                or res_data.get("wsEndpoint")
                or f"wss://api.getsolari.com/ws/{actual_sid}"
            )
            replay_url = res_data.get("replay_url") or (f"https://replay.getsolari.com/{actual_sid}" if record_session else None)

            session = SolariSession(
                session_id=actual_sid,
                session_type=SessionType.BROWSER,
                status=SessionStatus.RUNNING,
                cdp_endpoint=cdp_endpoint,
                vnc_stream=res_data.get("vnc_stream"),
                replay_url=replay_url,
                region=res_data.get("region", self.region),
                is_mock=False,
                start_time=now,
                metadata={
                    "stealth": stealth,
                    "viewport": vp,
                    "record_session": record_session,
                    **(metadata or {}),
                },
            )
            self._sessions[actual_sid] = session
            logger.info(f"Provisioned live Solari browser session {actual_sid} on {self.region}")
            return session

        except Exception as err:
            logger.warning(f"Live Solari browser provisioning failed ({err}). Falling back to mock.")
            session = SolariSession(
                session_id=sid,
                session_type=SessionType.BROWSER,
                status=SessionStatus.RUNNING,
                cdp_endpoint=f"ws://127.0.0.1:9222/devtools/browser/{sid}",
                replay_url=f"https://cloud.arc.ai/replay/{sid}",
                region=self.region,
                is_mock=True,
                start_time=now,
                metadata={"error_fallback": str(err), "stealth": stealth},
            )
            self._sessions[sid] = session
            return session

    def provision_desktop(
        self,
        resolution: str = "1920x1080",
        os_flavor: str = "ubuntu",
        timeout_sec: Optional[float] = None,
        session_id: Optional[str] = None,
        record_session: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SolariSession:
        """Provision an ephemeral desktop sandbox session in Solari Cloud."""
        sid = session_id or f"solari-desk-{uuid.uuid4().hex[:12]}"
        now = time.time()

        if self.is_mock:
            session = SolariSession(
                session_id=sid,
                session_type=SessionType.DESKTOP,
                status=SessionStatus.RUNNING,
                cdp_endpoint=f"ws://127.0.0.1:9222/devtools/browser/{sid}",
                vnc_stream=f"vnc://127.0.0.1:5900/{sid}",
                replay_url=f"https://cloud.arc.ai/replay/{sid}" if record_session else None,
                region=self.region,
                is_mock=True,
                start_time=now,
                metadata={
                    "resolution": resolution,
                    "os_flavor": os_flavor,
                    "record_session": record_session,
                    **(metadata or {}),
                },
            )
            self._sessions[sid] = session
            logger.debug(f"[MOCK] Provisioned Solari desktop sandbox session {sid}")
            return session

        # Real Solari API request
        payload = {
            "session_id": sid,
            "session_type": "desktop",
            "region": self.region,
            "resolution": resolution,
            "os_flavor": os_flavor,
            "record_session": record_session,
            "metadata": metadata or {},
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "ARC-Autonomous-Agent/1.0",
        }
        url = f"{self.api_url}/sessions/desktop"
        timeout = timeout_sec or self.timeout_sec

        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
            res_data = self._http_requester(req, timeout)

            vnc_stream = res_data.get("vnc_stream", f"vnc://{self.region}.cloud.getsolari.com/{sid}")
            cdp_endpoint = res_data.get("cdp_endpoint", f"wss://{self.region}.cloud.getsolari.com/cdp/{sid}")
            replay_url = res_data.get("replay_url", f"https://replay.getsolari.com/{sid}")

            session = SolariSession(
                session_id=sid,
                session_type=SessionType.DESKTOP,
                status=SessionStatus.RUNNING,
                cdp_endpoint=cdp_endpoint,
                vnc_stream=vnc_stream,
                replay_url=replay_url,
                region=res_data.get("region", self.region),
                is_mock=False,
                start_time=now,
                metadata={
                    "resolution": resolution,
                    "os_flavor": os_flavor,
                    "record_session": record_session,
                    **(metadata or {}),
                },
            )
            self._sessions[sid] = session
            logger.info(f"Provisioned live Solari desktop session {sid} on {self.region}")
            return session

        except Exception as err:
            logger.warning(f"Live Solari desktop provisioning failed ({err}). Falling back to mock.")
            session = SolariSession(
                session_id=sid,
                session_type=SessionType.DESKTOP,
                status=SessionStatus.RUNNING,
                cdp_endpoint=f"ws://127.0.0.1:9222/devtools/browser/{sid}",
                vnc_stream=f"vnc://127.0.0.1:5900/{sid}",
                replay_url=f"https://cloud.arc.ai/replay/{sid}",
                region=self.region,
                is_mock=True,
                start_time=now,
                metadata={"error_fallback": str(err), "resolution": resolution},
            )
            self._sessions[sid] = session
            return session

    def get_compute_time_ms(self, session_id: str) -> float:
        """Get the elapsed or finalized compute time in milliseconds for a session."""
        session = self._sessions.get(session_id)
        if not session:
            return 0.0
        return session.elapsed_ms()

    def get_total_compute_time_ms(self) -> float:
        """Sum compute time across all tracked sessions."""
        return sum(s.elapsed_ms() for s in self._sessions.values())

    def get_session(self, session_id: str) -> Optional[SolariSession]:
        """Look up a session by ID."""
        return self._sessions.get(session_id)

    def list_active_sessions(self) -> List[SolariSession]:
        """Return all currently active sessions."""
        return [s for s in self._sessions.values() if s.is_active()]

    def terminate(self, session_id: str) -> bool:
        """Terminate an active session and freeze its compute duration."""
        session = self._sessions.get(session_id)
        if not session:
            logger.warning(f"Attempted to terminate non-existent session: {session_id}")
            return False

        if session.status == SessionStatus.TERMINATED:
            return True

        now = time.time()
        session.end_time = now
        session.compute_time_ms = max(0.0, (now - session.start_time) * 1000.0)
        session.status = SessionStatus.TERMINATED

        if not self.is_mock and self.api_key:
            try:
                url = f"{self.api_url}/sessions/{session_id}"
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "User-Agent": "ARC-Autonomous-Agent/1.0",
                }
                req = urllib.request.Request(url, headers=headers, method="DELETE")
                self._http_requester(req, self.timeout_sec)
                logger.info(f"Terminated live Solari session {session_id} (Compute: {session.compute_time_ms:.1f}ms)")
            except Exception as err:
                logger.warning(f"Remote teardown failed for session {session_id}: {err}")

        return True

    def terminate_all(self) -> int:
        """Terminate all currently active sessions. Returns count of terminated sessions."""
        count = 0
        for sid in list(self._sessions.keys()):
            if self._sessions[sid].is_active():
                if self.terminate(sid):
                    count += 1
        return count

    def get_cdp_endpoint(self, session_id: str) -> str:
        """Get the active CDP endpoint URL for a provisioned session."""
        session = self._sessions.get(session_id)
        if not session:
            raise KeyError(f"Session '{session_id}' not found in SolariCloudDriver.")
        if not session.cdp_endpoint:
            raise ValueError(f"Session '{session_id}' has no CDP endpoint configured.")
        return session.cdp_endpoint

    def get_vnc_stream(self, session_id: str) -> str:
        """Get the active VNC stream URL for a desktop session."""
        session = self._sessions.get(session_id)
        if not session:
            raise KeyError(f"Session '{session_id}' not found in SolariCloudDriver.")
        if not session.vnc_stream:
            raise ValueError(f"Session '{session_id}' has no VNC stream configured.")
        return session.vnc_stream

    def get_replay_url(self, session_id: str) -> Optional[str]:
        """Get the session recording replay URL if available."""
        session = self._sessions.get(session_id)
        if not session:
            return None
        return session.replay_url

    def active_sessions_count(self) -> int:
        """Return count of currently running sessions."""
        return sum(1 for s in self._sessions.values() if s.status == SessionStatus.RUNNING)

    def total_compute_ms(self) -> float:
        """Compute cumulative milliseconds of cloud compute across all sessions."""
        return sum(s.elapsed_ms() for s in self._sessions.values())


# Backward-compatible alias
ArcCloudDriver = SolariCloudDriver
