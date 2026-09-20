"""OSWorld Desktop Environment Adapter for ARC (Phase 4C).

Manages the desktop interaction environment for OSWorld benchmark tasks across:
- AT-SPI D-Bus accessibility perception (GTK, Qt, Electron)
- Local File System (workspace files, configs, scripts)
- Terminal / Shell execution (commands, stdout/stderr history)

Supports two operating modes:
1. `mock`: Fully offline in-memory file system, simulated terminal outputs,
   and deterministic AT-SPI desktop hierarchy (suitable for 100% CI compliance).
2. `live`: Connects to real Linux desktop (X11/Xvfb, D-Bus org.a11y.Bus),
   real host file system, and subprocess terminal execution.
"""

from __future__ import annotations

import copy
import logging
import os
import pathlib
import posixpath
import re
import shlex
import subprocess
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, Union

from ..at_spi_bridge import AT_SPI_Bridge, DesktopNode, SerializedDesktopTree

logger = logging.getLogger("arc_cua.eval.osworld_env")


def _normalize_path(path: str) -> str:
    """Normalize POSIX-style path for consistent lookup across OS platforms."""
    # Convert Windows backslashes if present
    clean = path.replace("\\", "/").strip()
    # Normalize path segments while keeping leading slash
    is_abs = clean.startswith("/")
    norm = posixpath.normpath(clean)
    if is_abs and not norm.startswith("/"):
        norm = "/" + norm
    return norm


class OSWorldEnv:
    """Environment adapter managing desktop state for OSWorld tasks."""

    def __init__(
        self,
        mode: str = "mock",
        initial_files: Optional[Dict[str, Union[str, bytes]]] = None,
        initial_terminal_history: Optional[List[str]] = None,
        initial_terminal_output: Optional[List[str]] = None,
        at_spi_bridge: Optional[AT_SPI_Bridge] = None,
        base_dir: Optional[str] = None,
    ):
        """Initialize the OSWorld Desktop Environment.

        Args:
            mode: Operating mode ('mock', 'live', or 'auto').
            initial_files: Baseline files for in-memory or live testbed.
            initial_terminal_history: Baseline terminal command history.
            initial_terminal_output: Baseline terminal output buffer.
            at_spi_bridge: Optional custom AT_SPI_Bridge instance.
            base_dir: Optional base directory for live mode file operations.
        """
        req_mode = mode.lower()
        if req_mode == "auto":
            # Detect whether we have real AT-SPI / X11 environment
            has_x11 = bool(os.environ.get("DISPLAY"))
            has_dbus = bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS") or os.environ.get("AT_SPI_BUS_ADDRESS"))
            self.mode = "live" if (has_x11 and has_dbus) else "mock"
        else:
            self.mode = req_mode

        self.base_dir = base_dir or os.getcwd()

        # In-memory mock file system: normalized_path -> content (str)
        self._mock_fs: Dict[str, str] = {}
        # Terminal execution tracking
        self._terminal_history: List[str] = []
        self._terminal_output: List[str] = []

        # Baseline snapshots for environment reset
        self._baseline_files: Dict[str, str] = {}
        self._baseline_terminal_history: List[str] = []
        self._baseline_terminal_output: List[str] = []

        # Custom command dispatch table for mock shell simulation
        self._mock_command_handlers: Dict[str, Callable[[str], Tuple[int, str]]] = {}

        # AT-SPI accessibility bridge
        if at_spi_bridge is not None:
            self.at_spi_bridge = at_spi_bridge
        else:
            bridge_mode = "real" if self.mode == "live" else "mock"
            self.at_spi_bridge = AT_SPI_Bridge(mode=bridge_mode)

        # Populate initial state
        if initial_files:
            for p, content in initial_files.items():
                norm = _normalize_path(p)
                text = content if isinstance(content, str) else content.decode("utf-8", errors="replace")
                self._mock_fs[norm] = text
                self._baseline_files[norm] = text
                if self.mode == "live":
                    self._write_live_file(p, text)

        if initial_terminal_history:
            self._terminal_history.extend(initial_terminal_history)
            self._baseline_terminal_history.extend(initial_terminal_history)

        if initial_terminal_output:
            self._terminal_output.extend(initial_terminal_output)
            self._baseline_terminal_output.extend(initial_terminal_output)

        logger.info("OSWorldEnv initialized in mode='%s' (files=%d, term_history=%d)",
                    self.mode, len(self._mock_fs), len(self._terminal_history))

    # -------------------------------------------------------------------------
    # File System Operations (Mock & Live)
    # -------------------------------------------------------------------------

    def _resolve_live_path(self, path: str) -> pathlib.Path:
        """Resolve a path to a safe live filesystem location."""
        p = pathlib.Path(path)
        if p.is_absolute():
            # In live mode within container/microVM, absolute paths are used directly
            return p
        return pathlib.Path(self.base_dir) / p

    def _write_live_file(self, path: str, content: str) -> None:
        """Write a file to the host filesystem."""
        target = self._resolve_live_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def write_file(self, path: str, content: Union[str, bytes]) -> None:
        """Create or overwrite a file in the environment.

        Args:
            path: Target file path.
            content: Text or binary content.
        """
        text = content if isinstance(content, str) else content.decode("utf-8", errors="replace")
        norm = _normalize_path(path)
        self._mock_fs[norm] = text

        if self.mode == "live":
            self._write_live_file(path, text)

    def read_file(self, path: str) -> str:
        """Read content of a file in the environment.

        Args:
            path: File path to read.

        Returns:
            File content as text.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        norm = _normalize_path(path)
        if self.mode == "mock":
            if norm in self._mock_fs:
                return self._mock_fs[norm]
            raise FileNotFoundError(f"Mock file not found: {path} (normalized: {norm})")

        # Live mode
        target = self._resolve_live_path(path)
        if not target.exists():
            # Fallback to mock fs if set
            if norm in self._mock_fs:
                return self._mock_fs[norm]
            raise FileNotFoundError(f"Live file not found: {target}")
        return target.read_text(encoding="utf-8", errors="replace")

    def file_exists(self, path: str) -> bool:
        """Check whether a file exists in the environment.

        Args:
            path: File path to check.

        Returns:
            True if the file exists, False otherwise.
        """
        norm = _normalize_path(path)
        if self.mode == "mock":
            return norm in self._mock_fs

        # Live mode
        target = self._resolve_live_path(path)
        if target.exists():
            return True
        return norm in self._mock_fs

    def delete_file(self, path: str) -> bool:
        """Delete a file from the environment.

        Args:
            path: File path to delete.

        Returns:
            True if file existed and was deleted, False otherwise.
        """
        norm = _normalize_path(path)
        existed = False
        if norm in self._mock_fs:
            del self._mock_fs[norm]
            existed = True

        if self.mode == "live":
            target = self._resolve_live_path(path)
            if target.exists():
                try:
                    target.unlink()
                    existed = True
                except OSError as e:
                    logger.warning("Failed to delete live file %s: %s", target, e)

        return existed

    def list_files(self, directory: str = "/") -> List[str]:
        """List files located under a directory prefix.

        Args:
            directory: Directory path prefix.

        Returns:
            List of matching normalized file paths.
        """
        norm_dir = _normalize_path(directory).rstrip("/")
        if self.mode == "mock":
            if not norm_dir or norm_dir == "/":
                return sorted(list(self._mock_fs.keys()))
            prefix = norm_dir + "/"
            return sorted([p for p in self._mock_fs if p.startswith(prefix) or p == norm_dir])

        # Live mode
        target = self._resolve_live_path(directory)
        if not target.exists() or not target.is_dir():
            return []
        return sorted([_normalize_path(str(p)) for p in target.glob("**/*") if p.is_file()])

    # -------------------------------------------------------------------------
    # Terminal / Shell Operations
    # -------------------------------------------------------------------------

    def register_command_handler(
        self,
        command_prefix: str,
        handler: Callable[[str], Tuple[int, str]],
    ) -> None:
        """Register a custom handler for simulated shell commands in mock mode."""
        self._mock_command_handlers[command_prefix.strip()] = handler

    def execute_command(self, command: str, timeout_sec: float = 10.0) -> Tuple[int, str]:
        """Execute a shell command in the desktop environment.

        Args:
            command: Shell command string.
            timeout_sec: Execution timeout in seconds.

        Returns:
            Tuple of (exit_code, output_text).
        """
        stripped_cmd = command.strip()
        self._terminal_history.append(stripped_cmd)

        if self.mode == "live":
            try:
                proc = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec,
                    cwd=self.base_dir,
                )
                out = (proc.stdout or "") + (proc.stderr or "")
                if out:
                    self._terminal_output.append(out.rstrip())
                return proc.returncode, out
            except subprocess.TimeoutExpired:
                err = f"Command timed out after {timeout_sec}s: {command}"
                self._terminal_output.append(err)
                return 124, err
            except Exception as e:
                err = f"Execution error: {e}"
                self._terminal_output.append(err)
                return 1, err

        # Mock mode execution simulation
        # 1. Check custom command handlers
        for prefix, handler in self._mock_command_handlers.items():
            if stripped_cmd == prefix or stripped_cmd.startswith(prefix + " "):
                code, out = handler(stripped_cmd)
                if out:
                    self._terminal_output.append(out.rstrip())
                return code, out

        # 2. Built-in mock shell command interpreters
        code, out = self._interpret_mock_command(stripped_cmd)
        if out:
            self._terminal_output.append(out.rstrip())
        return code, out

    def _interpret_mock_command(self, cmd: str) -> Tuple[int, str]:
        """Simulate execution of basic shell commands in mock mode."""
        # Redirection check: cmd > file or cmd >> file
        if " > " in cmd or " >> " in cmd:
            append = " >> " in cmd
            parts = cmd.split(" >> " if append else " > ", 1)
            sub_cmd = parts[0].strip()
            target_file = parts[1].strip().strip('"').strip("'")

            # Execute sub-command to get output to write
            sub_code, sub_out = self._interpret_mock_command(sub_cmd)
            existing = ""
            if append and self.file_exists(target_file):
                try:
                    existing = self.read_file(target_file)
                except Exception:
                    existing = ""
            new_content = existing + sub_out if append else sub_out
            self.write_file(target_file, new_content)
            return 0, ""

        # echo command
        if cmd.startswith("echo "):
            raw = cmd[5:].strip()
            # Strip quotes
            if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
                raw = raw[1:-1]
            return 0, raw + "\n"

        # cat command
        if cmd.startswith("cat "):
            target = cmd[4:].strip().strip('"').strip("'")
            if self.file_exists(target):
                return 0, self.read_file(target)
            return 1, f"cat: {target}: No such file or directory\n"

        # touch command
        if cmd.startswith("touch "):
            target = cmd[6:].strip().strip('"').strip("'")
            if not self.file_exists(target):
                self.write_file(target, "")
            return 0, ""

        # rm command
        if cmd.startswith("rm "):
            args = cmd.split()
            target = args[-1].strip('"').strip("'")
            self.delete_file(target)
            return 0, ""

        # mkdir command
        if cmd.startswith("mkdir "):
            return 0, ""

        # git status / commit / diff mocks
        if cmd.startswith("git "):
            if "commit" in cmd:
                return 0, "[main 8f3b21a] feat: add osworld harness\n 1 file changed, 10 insertions(+)"
            if "status" in cmd:
                return 0, "On branch main\nnothing to commit, working tree clean"
            return 0, "git command executed successfully"

        # python command
        if cmd.startswith("python") or cmd.startswith("python3"):
            return 0, "Python execution finished with exit code 0"

        # gcc / clang command
        if cmd.startswith("gcc ") or cmd.startswith("clang "):
            return 0, "Compilation successful: build/libfast.so"

        # grep command
        if cmd.startswith("grep "):
            return 0, "Found 0 error lines"

        # Default fallback output for mock shell
        return 0, f"Executed: {cmd}"

    def append_terminal_output(self, output: str) -> None:
        """Directly append output text to the terminal output buffer."""
        self._terminal_output.append(output.rstrip())

    def get_terminal_output(self) -> str:
        """Get the full terminal output buffer as a single string."""
        return "\n".join(self._terminal_output)

    def get_terminal_history(self) -> List[str]:
        """Get the list of commands executed in the terminal session."""
        return list(self._terminal_history)

    def clear_terminal(self) -> None:
        """Clear the terminal output and history buffers."""
        self._terminal_history.clear()
        self._terminal_output.clear()

    # -------------------------------------------------------------------------
    # AT-SPI Perception & Accessibility
    # -------------------------------------------------------------------------

    def get_desktop_tree(self) -> SerializedDesktopTree:
        """Acquire the serialized AT-SPI accessibility hierarchy."""
        return self.at_spi_bridge.get_desktop_tree()

    def find_nodes(
        self,
        app_name: Optional[str] = None,
        role: Optional[str] = None,
        name: Optional[str] = None,
        state: Optional[str] = None,
    ) -> List[DesktopNode]:
        """Find accessible widgets in the desktop hierarchy matching query criteria.

        Args:
            app_name: Target application name (e.g., 'code', 'gnome-terminal').
            role: Semantic AT-SPI role (e.g., 'push_button', 'terminal', 'entry').
            name: Exact or substring widget name/label.
            state: Accessibility state (e.g., 'focused', 'showing', 'visible').

        Returns:
            List of matching DesktopNode objects.
        """
        # Query root applications from bridge
        apps = self.at_spi_bridge._query_desktop_applications()
        matches: List[DesktopNode] = []

        def _traverse(node: DesktopNode) -> None:
            match = True
            if app_name and node.app_name.lower() != app_name.lower():
                match = False
            if role and node.role.lower() != role.lower():
                match = False
            if name:
                if name.lower() not in (node.name or "").lower():
                    match = False
            if state:
                if state.lower() not in [s.lower() for s in node.states]:
                    match = False

            if match:
                matches.append(node)

            for child in node.children:
                _traverse(child)

        for app in apps:
            _traverse(app)

        return matches

    def update_widget_state(
        self,
        app_name: str,
        role: Optional[str] = None,
        name: Optional[str] = None,
        add_states: Optional[List[str]] = None,
        remove_states: Optional[List[str]] = None,
    ) -> bool:
        """Update states of matching widgets in mock mode for simulated desktop interaction.

        Args:
            app_name: Target application name.
            role: Target widget role.
            name: Target widget name.
            add_states: States to append (e.g. ['focused', 'active']).
            remove_states: States to remove (e.g. ['focused']).

        Returns:
            True if at least one widget was updated, False otherwise.
        """
        if self.mode != "mock":
            # Live state cannot be directly mutated via AT-SPI client
            return False

        # Find matching nodes and modify states in place
        apps = self.at_spi_bridge._query_desktop_applications()
        updated = False

        def _traverse(node: DesktopNode) -> None:
            nonlocal updated
            match = True
            if node.app_name.lower() != app_name.lower():
                match = False
            if role and node.role.lower() != role.lower():
                match = False
            if name and name.lower() not in (node.name or "").lower():
                match = False

            if match:
                if add_states:
                    for s in add_states:
                        if s not in node.states:
                            node.states.append(s)
                            updated = True
                if remove_states:
                    for s in remove_states:
                        if s in node.states:
                            node.states.remove(s)
                            updated = True

            for child in node.children:
                _traverse(child)

        for app in apps:
            _traverse(app)

        return updated

    # -------------------------------------------------------------------------
    # Environment Reset & Snapshotting
    # -------------------------------------------------------------------------

    def reset(
        self,
        initial_files: Optional[Dict[str, Union[str, bytes]]] = None,
        initial_terminal_history: Optional[List[str]] = None,
        initial_terminal_output: Optional[List[str]] = None,
    ) -> None:
        """Reset the environment state back to initial baseline or new definitions.

        Args:
            initial_files: Optional new baseline files.
            initial_terminal_history: Optional new baseline terminal history.
            initial_terminal_output: Optional new baseline terminal output.
        """
        # 1. Reset mock file system
        self._mock_fs.clear()
        target_files = initial_files if initial_files is not None else self._baseline_files
        for p, content in target_files.items():
            norm = _normalize_path(p)
            text = content if isinstance(content, str) else content.decode("utf-8", errors="replace")
            self._mock_fs[norm] = text
            if self.mode == "live":
                self._write_live_file(p, text)

        # 2. Reset terminal state
        self._terminal_history.clear()
        self._terminal_output.clear()
        target_hist = initial_terminal_history if initial_terminal_history is not None else self._baseline_terminal_history
        target_out = initial_terminal_output if initial_terminal_output is not None else self._baseline_terminal_output
        self._terminal_history.extend(target_hist)
        self._terminal_output.extend(target_out)

        # 3. Reset AT-SPI bridge if mock
        if self.mode == "mock":
            # Reinitialize default mock bridge to restore pristine widget trees
            self.at_spi_bridge = AT_SPI_Bridge(mode="mock")

        logger.debug("OSWorldEnv reset completed (files=%d)", len(self._mock_fs))

    def snapshot(self) -> Dict[str, Any]:
        """Capture a full snapshot of the current environment state."""
        return {
            "mode": self.mode,
            "mock_fs": copy.deepcopy(self._mock_fs),
            "terminal_history": list(self._terminal_history),
            "terminal_output": list(self._terminal_output),
        }

    def restore(self, snap: Dict[str, Any]) -> None:
        """Restore environment state from a previous snapshot."""
        self._mock_fs = copy.deepcopy(snap.get("mock_fs", {}))
        self._terminal_history = list(snap.get("terminal_history", []))
        self._terminal_output = list(snap.get("terminal_output", []))
        if self.mode == "mock":
            self.at_spi_bridge = AT_SPI_Bridge(mode="mock")
