"""ARC Cloud Driver adapter (aliases SolariCloudDriver).

Provides backward-compatible import path for ARC-branded code while
interfacing directly with Solari Cloud infrastructure.
"""

from .solari_driver import (
    ArcCloudDriver,
    ArcSession,
    SessionStatus,
    SessionType,
    SolariCloudDriver,
    SolariSession,
)

__all__ = [
    "SolariCloudDriver",
    "SolariSession",
    "ArcCloudDriver",
    "ArcSession",
    "SessionType",
    "SessionStatus",
]
