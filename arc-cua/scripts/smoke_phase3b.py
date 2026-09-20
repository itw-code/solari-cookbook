#!/usr/bin/env python3
"""Live Browser Hybrid Smoke Test Script for ARC (Phase 3B Task 8).

Validates HybridRunner on real headless Chromium:
1. Opens interactive test page.
2. Performs healthy action (typing into input).
3. Simulates repeated no-op stall to force stuck detection.
4. Triggers Escalation Controller and Cortex recovery.
5. Executes recovery action to update DOM.
6. Validates telemetry and exports trajectory logs.
"""

import json
import logging
import sys
from pathlib import Path

# Ensure src is on sys.path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "src"))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("smoke_phase3b")

from tests.test_phase3b_live import LIVE_BROWSER_SMOKE_SKIPPED, run_live_hybrid_smoke


def main():
    print("=" * 60)
    print("PHASE 3B LIVE BROWSER HYBRID SMOKE TEST")
    print("=" * 60)

    try:
        smoke_result = run_live_hybrid_smoke(headless=True)
    except Exception as e:
        if LIVE_BROWSER_SMOKE_SKIPPED in str(e) or "Executable doesn't exist" in str(e):
            print(f"\n[NOTICE] {LIVE_BROWSER_SMOKE_SKIPPED}: Chromium browser unavailable in environment.")
            print(f"Details: {e}")
            print("=" * 60)
            return 0
        raise

    print("\nLive Smoke Test Succeeded!")
    print(f"  Total Steps Executed:      {smoke_result['total_steps']}")
    print(f"  Reflex Steps:              {smoke_result['reflex_steps']}")
    print(f"  Escalations Triggered:     {smoke_result['escalations']}")
    print(f"  Recoveries Attempted:      {smoke_result['recoveries_attempted']}")
    print(f"  Recoveries Succeeded:      {smoke_result['recoveries_succeeded']}")
    print(f"  Page Input Value:          '{smoke_result['input_value']}'")
    print(f"  Final DOM Status:          '{smoke_result['final_status']}'")
    print(f"  Trajectory Windows Logged: {smoke_result['trajectory_windows_count']}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
