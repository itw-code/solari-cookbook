"""Command-Line Interface (CLI) for ARC / Solari Hybrid CUA.

Provides atomic, low-overhead browser and computer-use tools for omp agents:
- mode: Inspect or configure the active CUA mode (default vs arc-cua).
- cdp: Probe or resolve active Chrome DevTools Protocol endpoints.
- open: Open a URL in a persistent Chromium session.
- inspect: Extract and print zero-copy sanitized AXTree (token-budgeted at 1200 tokens;
  waits out SPA hydration; announces any dropped nodes via truncation_notice) with
  monotonic [#N] indices.
- act: Dispatch a deterministic reflex action (click, type, select, scroll, goto);
  per-action latency reported, and consecutive no-ops on a target flagged as a stall.
- run: Execute autonomous goal with HybridRunner (monitors + cortex escalation).
- close: Terminate the persistent Chromium browser session.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


from arc_cua.browser_session import (
    extract_page_tree as _extract_page_tree,
    resolve_target,
    settle_and_extract as _settle_and_extract,
)
from arc_cua.cdp_discovery import is_cdp_alive

# Persistent config and session paths in user home
USER_DIR = Path.home() / ".omp"
USER_CONFIG_PATH = USER_DIR / "cua-mode.json"
PROJECT_CONFIG_PATH = Path(".omp") / "cua-mode.json"
SESSION_CONFIG_PATH = USER_DIR / "cua-session.json"
TREE_CACHE_PATH = USER_DIR / "cua-last-tree.json"
ACT_STREAK_PATH = USER_DIR / "cua-act-streak.json"

# Consecutive mutating no-op actions on one target before the CLI reports a stall.
ACT_STALL_THRESHOLD = 3

logger = logging.getLogger("arc_cua.cli")


def get_current_mode() -> str:
    """Resolve the active CUA mode from env, project config, user config, or default."""
    env_mode = os.environ.get("OMP_CUA_MODE")
    if env_mode:
        return env_mode.strip().lower()

    for path in [PROJECT_CONFIG_PATH, USER_CONFIG_PATH]:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                mode = data.get("mode")
                if mode:
                    return str(mode).strip().lower()
            except Exception as e:
                logger.debug(f"Failed to read {path}: {e}")

    return "default"


def set_current_mode(mode: str, global_scope: bool = True) -> Path:
    """Persist the active CUA mode to config."""
    target_path = USER_CONFIG_PATH if global_scope else PROJECT_CONFIG_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": mode.strip().lower(),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    target_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return target_path


def find_free_port() -> int:
    """Allocate an unbound TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get_chromium_executable() -> str:
    """Locate Chromium executable from Playwright or system paths."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            return p.chromium.executable_path
    except Exception:
        pass

    # Windows fallback paths
    candidates = [
        Path.home() / "AppData" / "Local" / "ms-playwright",
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
        if c.is_dir():
            for exe in c.glob("**/chrome.exe"):
                if exe.is_file():
                    return str(exe)

    return "chrome"


def ensure_cdp_session(explicit_cdp: str | None = None, visible: bool = False, discover: bool = True) -> str:
    """Return an active CDP endpoint URL, launching a persistent browser if none exists.

    `discover=False` skips probing well-known localhost ports, so only a session this CLI
    launched (or a fresh one) is used.
    """
    if explicit_cdp and is_cdp_alive(explicit_cdp):
        if visible:
            print(
                "NOTICE: --visible cannot be verified on an explicitly passed --cdp endpoint; "
                "attaching as-is (target browser may be headless).",
                file=sys.stderr,
            )
        return explicit_cdp

    if explicit_cdp:
        raise ConnectionError(
            f"Explicit CDP endpoint {explicit_cdp} is not a live CDP server "
            "(/json/version did not return 200). Refusing to launch a substitute browser. "
            "Omit --cdp to auto-launch."
        )

    # Check active session file
    if SESSION_CONFIG_PATH.exists():
        try:
            data = json.loads(SESSION_CONFIG_PATH.read_text(encoding="utf-8"))
            saved_url = data.get("cdp_url")
            saved_visible = data.get("visible", False)
            if saved_url and is_cdp_alive(saved_url):
                # If caller explicitly requested visible mode but active session is headless,
                # restart session so a real window appears on the user's desktop.
                if visible and not saved_visible:
                    print(
                        "NOTICE: Existing headless session closed; relaunching visible — "
                        "previous page state lost and the [#N] index map from the last inspect is stale.",
                        file=sys.stderr,
                    )
                    close_cdp_session()
                else:
                    return saved_url
        except Exception:
            pass

    # Probe standard localhost ports (9222, 9224) — skipped when visible=True, since a
    # discovered endpoint (e.g. omp's headless browser on 9224) is not known-visible and
    # silently reattaching to it would show no window. Launch our own visible browser instead.
    if not visible and discover:
        from arc_cua.cdp_discovery import CDPDiscovery
        discovery = CDPDiscovery()
        spec = discovery.discover()
        if spec.transport_type == "tcp_localhost" and is_cdp_alive(spec.endpoint_url):
            return spec.endpoint_url
        elif spec.transport_type == "omp_relay":
            print(
                f"NOTICE: Discovered omp browser relay on {spec.endpoint_url} (not a raw CDP endpoint). "
                "Bypassing relay to launch dedicated persistent Chromium session.",
                file=sys.stderr,
            )

    # No active session: launch persistent Chromium process
    port = find_free_port()
    user_data = tempfile.mkdtemp(prefix=SESSION_PROFILE_PREFIX)
    chrome_exe = get_chromium_executable()

    cmd = [
        chrome_exe,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if not visible:
        cmd.append("--headless=new")
    cmd.append("about:blank")

    # Own process group, so close can end Chromium's renderer/GPU children with it.
    group_kwargs: dict[str, Any] = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == "win32" else {"start_new_session": True}
    )
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **group_kwargs)

    cdp_url = f"http://127.0.0.1:{port}"
    ready = False
    for _ in range(40):
        if is_cdp_alive(cdp_url):
            ready = True
            break
        time.sleep(0.1)

    if not ready:
        _kill_process_tree(proc.pid)
        _remove_session_profile(user_data)
        raise RuntimeError(f"Failed to start Chromium on port {port}.")

    SESSION_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    session_data = {
        "cdp_url": cdp_url,
        "port": port,
        "pid": proc.pid,
        "visible": visible,
        "user_data_dir": user_data,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    SESSION_CONFIG_PATH.write_text(json.dumps(session_data, indent=2), encoding="utf-8")
    return cdp_url


SESSION_PROFILE_PREFIX = "arc_cua_session_"


def _kill_process_tree(pid: int) -> bool:
    """End a browser process and all of its children.

    `os.kill(pid, SIGTERM)` on Windows ends only the parent; Chromium's renderer and GPU
    processes survive and keep the profile directory locked. `taskkill /T` ends the tree.
    On POSIX the browser leads its own session (see `ensure_cdp_session`), so the whole
    process group is signalled.
    """
    if sys.platform == "win32":
        result = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True)
        return result.returncode == 0
    import signal
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
        return True
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, signal.SIGTERM)
            return True
        except OSError:
            return False


def _remove_session_profile(user_data_dir: str | None, attempts: int = 25) -> bool:
    """Delete a temp profile this CLI created. Refuses anything else.

    Only `<tempdir>/arc_cua_session_*` is removed, since the path comes from a JSON file
    in the user's home. Retries because Windows releases file locks a moment after the
    processes exit.
    """
    if not user_data_dir:
        return False
    import shutil
    path = Path(user_data_dir).resolve()
    if not path.name.startswith(SESSION_PROFILE_PREFIX) or path.parent != Path(tempfile.gettempdir()).resolve():
        logger.warning(f"Refusing to delete non-session directory: {path}")
        return False
    for _ in range(attempts):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return True
        time.sleep(0.2)
    logger.warning(f"Could not fully remove session profile {path}")
    return False


def close_cdp_session() -> bool:
    """Terminate the persistent Chromium process tree, delete its temp profile and session files."""
    killed = False
    if SESSION_CONFIG_PATH.exists():
        try:
            data = json.loads(SESSION_CONFIG_PATH.read_text(encoding="utf-8"))
            pid = data.get("pid")
            if pid:
                killed = _kill_process_tree(int(pid))
            _remove_session_profile(data.get("user_data_dir"))
        except Exception as e:
            logger.debug(f"Session teardown failed: {e}")

        try:
            SESSION_CONFIG_PATH.unlink(missing_ok=True)
        except Exception:
            pass

    if TREE_CACHE_PATH.exists():
        try:
            TREE_CACHE_PATH.unlink(missing_ok=True)
        except Exception:
            pass

    if ACT_STREAK_PATH.exists():
        try:
            ACT_STREAK_PATH.unlink(missing_ok=True)
        except Exception:
            pass

    return killed


def cmd_close(args: argparse.Namespace) -> int:
    """Handle the 'close' subcommand."""
    killed = close_cdp_session()
    if killed:
        print("Persistent Chromium session terminated successfully.")
    else:
        print("No active persistent Chromium session found.")
    return 0


def cmd_mode(args: argparse.Namespace) -> int:
    """Handle the 'mode' subcommand."""
    if args.new_mode:
        normalized = args.new_mode.strip().lower()
        if normalized in ("1", "default", "standard"):
            mode = "default"
        elif normalized in ("2", "arc", "arc-cua", "solari", "hybrid"):
            mode = "arc-cua"
        else:
            print(f"Error: Invalid mode '{args.new_mode}'. Use 'default' or 'arc-cua'.", file=sys.stderr)
            return 1

        path = set_current_mode(mode, global_scope=not args.project)
        scope_str = "project" if args.project else "global"
        print(f"Active CUA mode set to '{mode}' ({scope_str} config: {path})")
        return 0

    current = get_current_mode()
    desc = "Default (omp standard Chromium / Puppeteer)" if current == "default" else "ARC-CUA (Solari Hybrid Reflex / AXTree)"
    print(f"Active CUA mode: {current}")
    print(f"Description:     {desc}")
    print(f"Config path:     {USER_CONFIG_PATH if USER_CONFIG_PATH.exists() else '(default fallback)'}")
    return 0


def cmd_cdp(args: argparse.Namespace) -> int:
    """Handle the 'cdp' subcommand to probe endpoints."""
    from arc_cua.cdp_discovery import CDPDiscovery

    discovery = CDPDiscovery()
    spec = discovery.discover()
    print("CDP Endpoint Discovery:")
    print(f"  Endpoint URL:    {spec.endpoint_url}")
    print(f"  Transport Type:  {spec.transport_type}")
    print(f"  Is Mock:         {spec.is_mock}")
    print(f"  Description:     {spec.description}")
    if SESSION_CONFIG_PATH.exists():
        print(f"  Persistent file: {SESSION_CONFIG_PATH}")
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    """Handle the 'inspect' subcommand to extract sanitized AXTree."""
    from arc_cua.cdp_extractor import CDP_AXTree_Extractor

    extractor = CDP_AXTree_Extractor()

    if not args.url and args.mock:
        raw_nodes = extractor.create_mock_complex_page()
        tree = extractor.sanitize(raw_nodes)
        _print_tree(tree, args.format, settle_ms=args.settle_ms)
        return 0

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Error: Playwright is required for live inspection. (pip install playwright)", file=sys.stderr)
        return 1

    try:
        cdp_url = ensure_cdp_session(explicit_cdp=args.cdp, visible=args.visible)
    except ConnectionError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp_url)
        try:
            contexts = browser.contexts
            if contexts and contexts[0].pages:
                page = contexts[0].pages[0]
            else:
                page = browser.new_page()

            if args.url:
                page.goto(args.url, timeout=args.timeout_ms)
                page.wait_for_load_state("domcontentloaded", timeout=args.timeout_ms)

            tree, attempts = _settle_and_extract(page, extractor, args.settle_ms)

            # Cache action index map for subsequent `act` calls
            try:
                TREE_CACHE_PATH.write_text(json.dumps(tree.action_index_map, indent=2), encoding="utf-8")
            except Exception as e:
                logger.debug(f"Failed to write tree cache: {e}")

            _print_tree(tree, args.format, attempts=attempts, settle_ms=args.settle_ms)
        finally:
            browser.close()

    return 0


def _print_tree(
    tree: Any,
    output_format: str,
    attempts: int = 1,
    settle_ms: float = 0.0,
) -> None:
    """Format and print the sanitized tree.

    The YAML branch must emit the linearized node list: printing only the header left
    the perception payload unreachable from the CLI, reducing an agent's entire
    perception channel to a one-line summary (audit F-02).
    """
    if output_format == "json":
        output = {
            "raw_node_count": tree.raw_node_count,
            "pruned_node_count": tree.pruned_node_count,
            "actionable_count": tree.actionable_count,
            "extraction_latency_ms": round(tree.sanitization_latency_ms, 3),
            "truncated": tree.truncated,
            "estimated_tokens": tree.estimated_tokens,
            "truncation_notice": tree.truncation_notice,
            "dropped_actionable_count": tree.dropped_actionable_count,
            "dropped_node_count": tree.dropped_node_count,
            "settle_attempts": attempts,
            "nodes": tree.json_structured,
            "action_index_map": tree.action_index_map,
        }
        print(json.dumps(output, indent=2))
    else:
        header = f"# AXTree [Actionable: {tree.actionable_count} | Tokens: ~{tree.estimated_tokens} | Latency: {tree.sanitization_latency_ms:.2f}ms]"
        if tree.truncated:
            header += " | Truncated"
        print(header)

        if tree.yaml_linearized:
            print(tree.yaml_linearized)
        else:
            print("(empty tree)")

        # An empty tree is never a successful perception: say so rather than
        # reporting a blank page as a valid observation.
        if tree.actionable_count == 0:
            print(
                f"WARNING: no actionable nodes found after {attempts} extraction attempt(s) "
                f"within the {settle_ms:.0f}ms settle budget. The page may still be hydrating, "
                "may require authentication, or may render content the accessibility tree does "
                "not expose (canvas/WebGL). Re-run with a larger --settle-ms, or escalate to "
                "visual perception.",
                file=sys.stderr,
            )


def _update_act_noop_streak(target: str | None, verb: str, is_noop: bool) -> int:
    """Persist the consecutive no-op streak for `act` across CLI invocations.

    Each `act` call is a separate process, so the streak must outlive the process to be
    useful. The streak resets whenever a mutating action actually changes state, and
    tracks the target so a streak on one element does not mask progress on another.

    Args:
        target: Resolved locator for this action.
        verb: Action verb name.
        is_noop: True when the action succeeded but produced no state change.

    Returns:
        Updated consecutive no-op streak for this target.
    """
    key = f"{verb}:{target}"
    try:
        state = json.loads(ACT_STREAK_PATH.read_text(encoding="utf-8")) if ACT_STREAK_PATH.exists() else {}
    except Exception:
        state = {}

    if not isinstance(state, dict):
        state = {}

    streak = int(state.get(key, 0) or 0) + 1 if is_noop else 0
    state = {key: streak}

    try:
        ACT_STREAK_PATH.parent.mkdir(parents=True, exist_ok=True)
        ACT_STREAK_PATH.write_text(json.dumps(state), encoding="utf-8")
    except Exception as e:
        logger.debug(f"Failed to persist act streak: {e}")

    return streak


def cmd_act(args: argparse.Namespace) -> int:
    """Handle the 'act' subcommand to dispatch a deterministic reflex action (per-action latency reported)."""
    from arc_cua.playwright_executor import PlaywrightExecutor
    from arc_cua.executor_interface import ActionPayload, ActionVerb
    from arc_cua.state_verifier import StateVerifier
    from arc_cua.cdp_extractor import CDP_AXTree_Extractor

    verb_map = {
        "CLICK": ActionVerb.CLICK,
        "DBLCLICK": ActionVerb.DBLCLICK,
        "HOVER": ActionVerb.HOVER,
        "TYPE": ActionVerb.TYPE,
        "FILL": ActionVerb.FILL,
        "SELECT": ActionVerb.SELECT_OPTION,
        "SELECT_OPTION": ActionVerb.SELECT_OPTION,
        "PRESS_KEY": ActionVerb.PRESS_KEY,
        "SCROLL": ActionVerb.SCROLL,
        "WAIT": ActionVerb.WAIT_FOR_SELECTOR,
        "WAIT_FOR_SELECTOR": ActionVerb.WAIT_FOR_SELECTOR,
        "NAVIGATE": ActionVerb.NAVIGATE,
        "GOTO": ActionVerb.NAVIGATE,
    }
    verb = verb_map.get(args.action.upper())
    if not verb:
        print(f"Error: Unknown action verb '{args.action}'. Supported: {list(verb_map.keys())}", file=sys.stderr)
        return 1

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Error: Playwright is required for live actions.", file=sys.stderr)
        return 1

    executor = PlaywrightExecutor(default_timeout_ms=float(args.timeout_ms))
    verifier = StateVerifier()
    extractor = CDP_AXTree_Extractor()

    try:
        cdp_url = ensure_cdp_session(explicit_cdp=args.cdp, visible=args.visible)
    except ConnectionError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp_url)
        try:
            contexts = browser.contexts
            if contexts and contexts[0].pages:
                page = contexts[0].pages[0]
            else:
                page = browser.new_page()

            if args.url:
                page.goto(args.url)

            # Pre-action observation & live index extraction
            tree_before = _extract_page_tree(page, extractor)

            # Resolve target: prioritize live action map, fallback to cached tree
            active_map = tree_before.action_index_map
            if not active_map and TREE_CACHE_PATH.exists():
                try:
                    raw_cache = json.loads(TREE_CACHE_PATH.read_text(encoding="utf-8"))
                    active_map = {int(k): v for k, v in raw_cache.items()}
                except Exception:
                    pass

            target, action_idx = resolve_target(args.target, args.index, active_map)
            if (args.index is not None or (args.target and (args.target.startswith("@") or args.target.startswith("[#")))) and not target:
                print(f"Error: Action index {action_idx} could not be resolved to a locator in the current page.", file=sys.stderr)
                return 1

            payload = ActionPayload(
                verb=verb,
                target_selector=target,
                action_index=action_idx,
                value=args.value,
                timeout_ms=float(args.timeout_ms),
            )

            start = time.perf_counter()
            result = executor.execute(page, payload)
            elapsed_ms = (time.perf_counter() - start) * 1000.0

            # Post-action verification
            tree_after = _extract_page_tree(page, extractor)
            ver_res = verifier.verify(result, tree_before.yaml_linearized, tree_after.yaml_linearized)

            # Update cached tree
            try:
                TREE_CACHE_PATH.write_text(json.dumps(tree_after.action_index_map, indent=2), encoding="utf-8")
            except Exception:
                pass

            # A mutating action that reports success while changing nothing is a stall,
            # not progress. `act` runs no monitor loop, so without this the trajectory
            # cannot tell a delivered no-op from a real transition (audit F-05).
            neutral_verbs = {"WAIT", "WAIT_FOR_SELECTOR"}
            noop_streak = _update_act_noop_streak(
                target=target,
                verb=verb.name,
                is_noop=(
                    result.success
                    and not ver_res.state_changed
                    and not ver_res.url_changed
                    and verb.name not in neutral_verbs
                ),
            )

            out = {
                "success": result.success,
                "verb": verb.name,
                "target": target,
                "index": action_idx,
                "action_latency_ms": round(elapsed_ms, 2),
                "extraction_latency_ms": round(tree_before.sanitization_latency_ms, 3),
                "latency_ms": round(elapsed_ms, 2),
                "state_changed": ver_res.state_changed,
                "simhash_before": f"0x{ver_res.simhash_before:016x}",
                "simhash_after": f"0x{ver_res.simhash_after:016x}",
                "hamming_distance": ver_res.hamming_distance,
                "noop_streak": noop_streak,
                "stall_suspected": noop_streak >= ACT_STALL_THRESHOLD,
                "error": result.error_message,
            }
            # Surface executor metadata (scroll_mode/scroll_applied, click_type, ...) so a
            # delivered no-op is visible to the caller rather than hidden behind success:true.
            if result.metadata:
                out["metadata"] = result.metadata
            print(json.dumps(out, indent=2))

            if noop_streak >= ACT_STALL_THRESHOLD:
                print(
                    f"WARNING: {noop_streak} consecutive successful no-op actions on "
                    f"'{target}'. The action reports success but the page state, URL, and "
                    "DOM have not changed - the target is likely a wrong or inert element. "
                    "Escalate: re-inspect, or switch to visual perception.",
                    file=sys.stderr,
                )
            return 0 if result.success else 1
        finally:
            browser.close()


def cmd_run(args: argparse.Namespace) -> int:
    """Handle the 'run' subcommand to execute an autonomous hybrid task."""
    from arc_cua.hybrid_runner import HybridRunner
    from arc_cua.monitors.stuck_monitor import StuckMonitor
    from arc_cua.monitors.milestone_monitor import MilestoneMonitor
    from arc_cua.monitors.escalation_controller import EscalationController
    from arc_cua.cortex.mock_cortex import MockCortexClient
    from arc_cua.cortex.http_cortex import HttpCortexClient
    from arc_cua.cortex.real_llm_cortex import RealLLMCortexClient
    from arc_cua.telemetry import TelemetryCollector
    from arc_cua.schemas import ActionStep

    print(f"Initializing Hybrid CUA Runner for goal: '{args.goal}'")
    telemetry = TelemetryCollector()
    stuck_monitor = StuckMonitor(window_size=5, stuck_threshold=0.75)
    milestone_monitor = MilestoneMonitor()
    escalation_controller = EscalationController(
        max_escalations_per_task=3,
        max_recovery_attempts=2,
        cooldown_steps=1,
    )

    cortex_mode = args.cortex.lower()
    if cortex_mode == "real":
        cortex_client = RealLLMCortexClient()
    elif cortex_mode == "http":
        cortex_client = HttpCortexClient()
    else:
        cortex_client = MockCortexClient()

    runner = HybridRunner(
        telemetry=telemetry,
        stuck_monitor=stuck_monitor,
        milestone_monitor=milestone_monitor,
        escalation_controller=escalation_controller,
        cortex_client=cortex_client,
        cortex_mode=cortex_mode,
    )

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Error: Playwright is required for live autonomous execution.", file=sys.stderr)
        return 1

    cdp_url = ensure_cdp_session(explicit_cdp=None, visible=args.visible)

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp_url)
        try:
            contexts = browser.contexts
            page = contexts[0].pages[0] if contexts and contexts[0].pages else browser.new_page()
            if args.url:
                page.goto(args.url)

            initial_steps = [
                ActionStep(
                    step_number=1,
                    verb="WAIT",
                    target_selector=None,
                    value=None,
                    action_index=None,
                    latency_ms=0,
                    success=True,
                )
            ]

            result = runner.run_task(
                page=page,
                steps=initial_steps,
                task_goal=args.goal,
            )

            print("\n--- HYBRID RUN EXECUTION SUMMARY ---")
            print(f"  Success:               {result.success}")
            print(f"  Total Steps:           {result.total_steps}")
            print(f"  Reflex Steps:          {result.reflex_steps}")
            print(f"  Escalations Triggered: {result.escalations_triggered}")
            print(f"  Recoveries Attempted:  {result.recoveries_attempted}")
            print(f"  Recoveries Succeeded:  {result.recoveries_succeeded}")
            print(f"  Cumulative Cost:       ${result.cumulative_cost_usd:.6f}")
            return 0 if result.success else 1
        finally:
            browser.close()


def build_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="arc-cua",
        description="Solari / ARC Hybrid Computer Use Agent (CUA) Runtime CLI",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # mode
    p_mode = subparsers.add_parser("mode", help="Inspect or toggle CUA mode (default vs arc-cua)")
    p_mode.add_argument("new_mode", nargs="?", help="New mode: 'default' (1) or 'arc-cua' (2)")
    p_mode.add_argument("--project", action="store_true", help="Apply to project .omp/cua-mode.json instead of global user config")

    # cdp
    subparsers.add_parser("cdp", help="Probe and resolve active Chrome DevTools Protocol endpoints")

    # close
    subparsers.add_parser("close", help="Close the active persistent Chromium session")

    # inspect
    p_inspect = subparsers.add_parser("inspect", help="Extract token-budgeted AXTree (waits out SPA hydration; announces dropped nodes) with monotonic [#N] indices")
    p_inspect.add_argument("--url", help="Target URL to navigate to before inspection")
    p_inspect.add_argument("--cdp", help="Explicit CDP endpoint (ws:// or http://)")
    p_inspect.add_argument("--format", choices=["yaml", "json"], default="yaml", help="Output format (default: yaml)")
    p_inspect.add_argument("--visible", action="store_true", help="Launch visible browser instead of headless")
    p_inspect.add_argument("--mock", action="store_true", help="Inspect offline mock complex page fixture")
    p_inspect.add_argument("--timeout-ms", type=float, default=15000.0, help="Navigation timeout in ms")
    p_inspect.add_argument(
        "--settle-ms",
        type=float,
        default=5000.0,
        help="Budget for waiting out SPA hydration before extraction (default: 5000)",
    )

    # act
    p_act = subparsers.add_parser("act", help="Dispatch a deterministic reflex action (per-action latency reported)")
    p_act.add_argument("--action", required=True, help="Action verb: click, type, fill, select, scroll, goto, navigate, wait, press_key")
    p_act.add_argument("--index", type=int, help="Monotonic action index from inspect (e.g. 3)")
    p_act.add_argument("--target", help="Target locator: CSS selector, XPath, or @N / [#N] monotonic index")
    p_act.add_argument("--value", help="Value for type, select, goto, or scroll")
    p_act.add_argument("--url", help="Initial URL if opening fresh page")
    p_act.add_argument("--cdp", help="Explicit CDP endpoint to attach to")
    p_act.add_argument("--visible", action="store_true", help="Launch visible browser")
    p_act.add_argument("--timeout-ms", type=float, default=5000.0, help="Action timeout in ms")

    # run
    p_run = subparsers.add_parser("run", help="Run an autonomous task through the HybridRunner loop")
    p_run.add_argument("--goal", required=True, help="Task goal/instruction")
    p_run.add_argument("--url", help="Starting URL")
    p_run.add_argument("--cortex", choices=["mock", "real", "http"], default="mock", help="Cortex reasoning mode")
    p_run.add_argument("--visible", action="store_true", help="Launch visible browser")

    return parser


def main() -> int:
    """CLI entrypoint."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    parser = build_parser()
    if len(sys.argv) == 1:
        parser.print_help()
        return 0

    args = parser.parse_args()
    if args.command == "mode":
        return cmd_mode(args)
    elif args.command == "cdp":
        return cmd_cdp(args)
    elif args.command == "close":
        return cmd_close(args)
    elif args.command == "inspect":
        return cmd_inspect(args)
    elif args.command == "act":
        return cmd_act(args)
    elif args.command == "run":
        return cmd_run(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
