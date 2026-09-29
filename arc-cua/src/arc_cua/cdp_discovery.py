"""Dynamic Chrome DevTools Protocol (CDP) Discovery Service.

Remediates Task 1.2:
- Eliminates hardcoded CDP Unix Domain Socket paths.
- Discovers CDP endpoints dynamically with fallback cascade:
  1. Explicit endpoint argument.
  2. Environment variables (ARC_CDP_ENDPOINT, CDP_ENDPOINT).
  3. Arc Cloud API endpoint routing (via ARC_API_KEY and api.getarc.com).
  4. Localhost loopback probe (TCP 9222/9223 or standard UDS paths).
  5. Autonomous ingress tunnel fallback (TARGET_URL from quick tunnel or mock tunnel).
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import socket
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger("arc_cua.cdp_discovery")

# Candidate Unix Domain Sockets for Chromium on Linux
CANDIDATE_UDS_PATHS: List[str] = [
    "/tmp/chromium-cdp.sock",
    "/var/run/chromium/cdp.sock",
    "/run/arc/chromium.sock",
]

# Standard TCP remote debugging ports
CANDIDATE_TCP_PORTS: List[int] = [9222, 9223, 9224]


def is_cdp_alive(cdp_url: str, timeout: float = 1.5) -> bool:
    """Return True iff a real CDP endpoint at cdp_url responds with HTTP 200.

    Normalizes ws:// and wss:// debugger URLs to http:// and https:// and probes /json/version.
    """
    from urllib.parse import urlparse
    try:
        parsed = urlparse(cdp_url)
        scheme = "https" if parsed.scheme in ("wss", "https") else "http"
        netloc = parsed.netloc or parsed.path
        if not netloc:
            netloc = cdp_url
        url = f"{scheme}://{netloc.rstrip('/')}/json/version"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


@dataclasses.dataclass(frozen=True)
class CDPEndpointSpec:
    """Resolved descriptor for a Chrome DevTools Protocol endpoint."""
    endpoint_url: str
    transport_type: str  # "explicit", "env", "arc_cloud", "uds", "tcp_localhost", "omp_relay", "tunnel", "mock"
    is_mock: bool
    description: str


class CDPDiscovery:
    """Discovers and resolves live or simulated Chromium CDP endpoints."""

    def __init__(
        self,
        arc_base_url: Optional[str] = None,
        timeout: float = 1.0,
    ):
        """Initialize CDP Discovery.

        Args:
            arc_base_url: Base URL for Solari/ARC Cloud API (default: https://api.getsolari.com).
            timeout: Probe network timeout in seconds.
        """
        self.arc_base_url = (
            arc_base_url
            or os.environ.get("SOLARI_BASE_URL")
            or os.environ.get("ARC_BASE_URL", "https://api.getsolari.com")
        )
        self.timeout = timeout

    def discover(
        self,
        endpoint_override: Optional[str] = None,
        allow_tunnel_fallback: bool = True,
        allow_mock: bool = True,
    ) -> CDPEndpointSpec:
        """Resolve active CDP endpoint using the prioritized discovery cascade.

        Returns:
            CDPEndpointSpec detailing the resolved endpoint and transport mechanism.
        """
        # 1. Explicit override
        if endpoint_override:
            return CDPEndpointSpec(
                endpoint_url=endpoint_override,
                transport_type="explicit",
                is_mock="mock" in endpoint_override.lower(),
                description=f"Explicitly configured CDP endpoint: {endpoint_override}",
            )

        # 2. Environment variables: ARC_CDP_ENDPOINT or CDP_ENDPOINT
        for env_var in ("SOLARI_CDP_ENDPOINT", "ARC_CDP_ENDPOINT", "CDP_ENDPOINT"):
            val = os.environ.get(env_var)
            if val and val.strip():
                return CDPEndpointSpec(
                    endpoint_url=val.strip(),
                    transport_type="env",
                    is_mock="mock" in val.lower(),
                    description=f"Resolved via environment variable {env_var}",
                )

        # 3. Solari/ARC Cloud API lookup if SOLARI_API_KEY or ARC_API_KEY is configured
        api_key = os.environ.get("SOLARI_API_KEY") or os.environ.get("ARC_API_KEY")
        if api_key:
            cloud_endpoint = f"{self.arc_base_url.rstrip('/')}/v1/browser/cdp"
            transport = "solari_cloud" if os.environ.get("SOLARI_API_KEY") else "arc_cloud"
            return CDPEndpointSpec(
                endpoint_url=cloud_endpoint,
                transport_type=transport,
                is_mock=False,
                description=f"Solari/ARC Cloud Managed CDP gateway ({cloud_endpoint})",
            )

        # 4. Localhost Unix Domain Socket probes (Linux)
        if hasattr(socket, "AF_UNIX"):
            for uds in CANDIDATE_UDS_PATHS:
                p = Path(uds)
                if p.exists():
                    return CDPEndpointSpec(
                        endpoint_url=f"unix://{uds}",
                        transport_type="uds",
                        is_mock=False,
                        description=f"Discovered active local Chromium UDS socket at {uds}",
                    )

        # 5. Localhost live TCP probes (9222, 9223, 9224)
        omp_relay_detected = False
        for port in CANDIDATE_TCP_PORTS:
            if not self._is_tcp_port_open("127.0.0.1", port):
                continue
            if is_cdp_alive(f"http://127.0.0.1:{port}", self.timeout):
                return CDPEndpointSpec(
                    endpoint_url=f"http://127.0.0.1:{port}",
                    transport_type="tcp_localhost",
                    is_mock=False,
                    description=f"Discovered active local Chromium DevTools on 127.0.0.1:{port}",
                )
            elif port == 9224:
                omp_relay_detected = True

        # 6. Autonomous Ingress Tunnel fallback (TARGET_URL / Cloudflare Quick Tunnel)
        target_url = os.environ.get("TARGET_URL")
        if target_url and allow_tunnel_fallback:
            return CDPEndpointSpec(
                endpoint_url=target_url.strip(),
                transport_type="tunnel",
                is_mock="mock" in target_url.lower(),
                description=f"Ingress tunnel bridge active at {target_url}",
            )

        # 7. Discovered omp browser relay (listener open, but not live raw CDP)
        if omp_relay_detected:
            return CDPEndpointSpec(
                endpoint_url="http://127.0.0.1:9224",
                transport_type="omp_relay",
                is_mock=False,
                description=(
                    "Discovered omp browser relay on 127.0.0.1:9224 "
                    "(TCP listener active, but /json/version non-200; not a raw CDP endpoint)"
                ),
            )
        # 7. Mock fallback for offline/isolated sandbox test environments
        if allow_mock:
            mock_url = "mock://chromium-cdp.local"
            return CDPEndpointSpec(
                endpoint_url=mock_url,
                transport_type="mock",
                is_mock=True,
                description="Auto-provisioned in-memory mock CDP endpoint for testing",
            )

        raise ConnectionError(
            "No active Chromium CDP endpoint could be discovered. "
            "Set CDP_ENDPOINT, SOLARI_CDP_ENDPOINT, or ARC_CDP_ENDPOINT, or start Chromium with --remote-debugging-port=9222."
        )

    def _is_tcp_port_open(self, host: str, port: int) -> bool:
        """Attempt quick TCP socket handshake to verify port listener."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        try:
            s.connect((host, port))
            s.close()
            return True
        except (OSError, ConnectionRefusedError):
            return False

    def _probe_tcp_port(self, host: str, port: int) -> bool:
        """Validate the port via TCP handshake followed by CDP HTTP probe."""
        if not self._is_tcp_port_open(host, port):
            return False
        return is_cdp_alive(f"http://{host}:{port}", self.timeout)

