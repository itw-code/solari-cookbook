"""CLI `close` must end the whole Chromium process tree and delete its temp profile.

Regression for audit item #9: `os.kill(pid, SIGTERM)` on Windows ends only the parent
browser process, leaving renderer/GPU children holding the `arc_cua_session_*` profile,
which was never deleted either.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from arc_cua import cli


def pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@pytest.fixture
def isolated_session_files(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "SESSION_CONFIG_PATH", tmp_path / "cua-session.json")
    monkeypatch.setattr(cli, "TREE_CACHE_PATH", tmp_path / "cua-last-tree.json")
    monkeypatch.setattr(cli, "ACT_STREAK_PATH", tmp_path / "cua-act-streak.json")
    return tmp_path


def test_close_kills_tree_and_removes_profile(isolated_session_files):
    pytest.importorskip("playwright.sync_api")
    try:
        cli.ensure_cdp_session(visible=False, discover=False)
    except Exception as e:
        pytest.skip(f"LIVE_BROWSER_SKIPPED: {e}")

    import json
    session = json.loads(cli.SESSION_CONFIG_PATH.read_text(encoding="utf-8"))
    pid, profile = session["pid"], Path(session["user_data_dir"])
    assert pid_alive(pid) and profile.is_dir()

    assert cli.close_cdp_session() is True

    deadline = time.monotonic() + 10
    while pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not pid_alive(pid)
    assert not profile.exists(), "temp profile must be deleted (children still holding files would block this)"
    assert not cli.SESSION_CONFIG_PATH.exists()


def test_profile_removal_refuses_foreign_directories(tmp_path):
    foreign = tmp_path / "not-ours"
    foreign.mkdir()
    assert cli._remove_session_profile(str(foreign)) is False
    assert foreign.exists()
