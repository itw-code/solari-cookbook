"""OSWorld Desktop Evaluation Runner for ARC (Phase 4C).

Coordinates execution of OSWorld benchmark tasks through the Arc HybridRunner:
1. Initializes and manages OSWorldEnv (live or mock).
2. Resets desktop environment state (files, terminal, AT-SPI) before each task.
3. Executes action steps via HybridRunner (with AT-SPI perception and monitors).
4. Evaluates OSWorld assertions (file_exist, file_content_match, terminal_output_match,
   at_spi_state_match) via OSWorldAssertionAdapter.
5. Produces structured EvalResult objects conforming to Phase 4A schemas.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from ..cortex.mock_cortex import MockCortexClient
from ..datasets.trajectory_collector import TrajectoryCollector
from ..schemas import ActionStep
from .cost import CostLedger
from .osworld_assertions import OSWorldAssertionAdapter
from .osworld_env import OSWorldEnv
from .runner import EvalCortexClient, EvalRunner, MockEvalLocator, MockEvalPage
from .schemas import EvalAssertion, EvalAssertionResult, EvalResult, EvalTask

logger = logging.getLogger("arc_cua.eval.osworld_runner")


class MockOSWorldPage(MockEvalPage):
    """Deterministic mock page representing desktop GUI and terminal interaction."""

    def __init__(
        self,
        initial_url: str = "desktop://os_fs",
        env: Optional[OSWorldEnv] = None,
    ):
        """Initialize mock desktop page.

        Args:
            initial_url: Starting desktop URI.
            env: Optional OSWorldEnv to synchronize state mutations.
        """
        super().__init__(initial_url=initial_url)
        self.env = env
        self._inputs: Dict[str, str] = {
            "#file-editor": "Phase 4C Benchmark Ready",
            "#config-editor": "2.5.0",
            "#terminal-input": "",
        }
        self._texts: Dict[str, str] = {
            "title": "OSWorld Desktop Environment",
            "status": "Ready",
        }

    def handle_fill(self, selector: str, value: str) -> None:
        """Handle typing into desktop input fields."""
        sel = selector.lower()
        for k in self._inputs:
            if k in sel or sel in k:
                self._inputs[k] = value
                return
        self._inputs[selector] = value

    def handle_click(self, selector: str) -> None:
        """Simulate desktop GUI clicks and execute corresponding environment mutations."""
        sel = selector.lower()
        if not self.env:
            return

        # Domain 1: OS File System Actions
        if "save-summary-btn" in sel:
            content = self._inputs.get("#file-editor", "Phase 4C Benchmark Ready")
            self.env.write_file("/home/user/workspace/summary.txt", content)
            self._texts["status"] = "Summary saved successfully"

        elif "archive-log-btn" in sel:
            src = "/home/user/workspace/old_logs.txt"
            dst = "/home/user/workspace/archive/old_logs.txt"
            if self.env.file_exists(src):
                content = self.env.read_file(src)
                self.env.write_file(dst, content)
            else:
                self.env.write_file(dst, "Log entry 2026-09-20: System healthy and operational")
            self._texts["status"] = "Logs archived"

        elif "delete-temp-btn" in sel:
            self.env.delete_file("/home/user/workspace/temp_build.bin")
            self._texts["status"] = "Temporary build cleaned"

        elif "save-config-btn" in sel:
            version_val = self._inputs.get("#config-editor", "2.5.0")
            cfg = json.dumps({"name": "arc-cua", "version": version_val}, indent=2)
            self.env.write_file("/home/user/workspace/config.json", cfg)
            self._texts["status"] = f"Config saved with version {version_val}"

        # Domain 2: Terminal / Shell Actions
        elif "run-diagnostics" in sel:
            self.env.append_terminal_output("Running comprehensive system diagnostics...")
            self.env.append_terminal_output("All system diagnostics passed: OK")
            self._texts["status"] = "Diagnostics completed"

        elif "git-commit" in sel:
            self.env.append_terminal_output("[main 8f3b21a] feat: add osworld harness\n 1 file changed, 10 insertions(+)")
            self._texts["status"] = "Git commit recorded"

        elif "grep-errors" in sel:
            self.env.append_terminal_output("Found 0 error lines")
            self._texts["status"] = "Grep completed"

        elif "compile-lib" in sel:
            self.env.append_terminal_output("Compilation successful: build/libfast.so")
            self._texts["status"] = "Compilation completed"

        elif "terminal-execute-btn" in sel:
            cmd = self._inputs.get("#terminal-input", "").strip()
            if cmd:
                if "diagnostics" in cmd:
                    self.env.append_terminal_output("All system diagnostics passed: OK")
                elif "commit" in cmd:
                    self.env.append_terminal_output("[main 8f3b21a] feat: add osworld harness")
                elif "grep" in cmd:
                    self.env.append_terminal_output("Found 0 error lines")
                elif "gcc" in cmd or "clang" in cmd:
                    self.env.append_terminal_output("Compilation successful: build/libfast.so")
                else:
                    self.env.execute_command(cmd)

        # Domain 3: Desktop Apps AT-SPI Actions
        elif "vscode-run-benchmark-btn" in sel:
            self.env.update_widget_state(
                app_name="code",
                role="push_button",
                name="Run Benchmark Test",
                add_states=["showing", "visible", "enabled"],
            )
            self._texts["status"] = "Benchmark initiated in VS Code"

        elif "vscode-search-entry" in sel:
            self.env.update_widget_state(
                app_name="code",
                role="entry",
                name="Search files by name (Ctrl+P)",
                add_states=["focused", "enabled"],
            )
            self._texts["status"] = "Search entry focused"

        elif "terminal-tab-1" in sel:
            self.env.update_widget_state(
                app_name="gnome-terminal",
                role="page_tab",
                name="Bash Tab 1",
                add_states=["selected", "showing"],
            )
            self._texts["status"] = "Switched to Bash Tab 1"

        elif "terminal-vte-screen" in sel:
            self.env.update_widget_state(
                app_name="gnome-terminal",
                role="terminal",
                name="VTE Terminal Screen",
                add_states=["focused", "active"],
            )
            self._texts["status"] = "Terminal screen focused"


class OSWorldRunner:
    """Execution and evaluation harness for OSWorld benchmark tasks."""

    def __init__(
        self,
        mode: str = "hybrid",
        env: Optional[OSWorldEnv] = None,
        mock_mode: Optional[bool] = None,
        cost_ledger: Optional[CostLedger] = None,
        trajectory_collector: Optional[TrajectoryCollector] = None,
        cortex_client: Optional[EvalCortexClient] = None,
        skip_unsupported_assertions: bool = True,
        reset_between_tasks: bool = True,
    ):
        """Initialize the OSWorld Runner.

        Args:
            mode: Runner mode ('hybrid' or 'reflex').
            env: Optional OSWorldEnv instance.
            mock_mode: If True, forces offline mock desktop environment.
            cost_ledger: Cost accounting ledger.
            trajectory_collector: Optional trajectory recorder.
            cortex_client: Optional mock cortex client.
            skip_unsupported_assertions: Whether to mark unsupported assertions passed.
            reset_between_tasks: Whether to reset environment between tasks.
        """
        self.mode = mode.lower()
        if env is not None:
            self.env = env
        else:
            env_mode = "mock" if (mock_mode is None or mock_mode is True) else "live"
            self.env = OSWorldEnv(mode=env_mode)

        self.mock_mode = (self.env.mode == "mock") if mock_mode is None else mock_mode
        self.cost_ledger = cost_ledger or CostLedger()
        self.trajectory_collector = trajectory_collector
        self.cortex_client = cortex_client or EvalCortexClient()
        self.skip_unsupported_assertions = skip_unsupported_assertions
        self.reset_between_tasks = reset_between_tasks

        # OSWorld assertion adapter
        self.assertion_adapter = OSWorldAssertionAdapter(
            env=self.env,
            skip_unsupported=self.skip_unsupported_assertions,
        )

        # Underlying EvalRunner
        self.eval_runner = EvalRunner(
            mode=self.mode,
            headless=True,
            mock_mode=self.mock_mode,
            cost_ledger=self.cost_ledger,
            trajectory_collector=self.trajectory_collector,
            cortex_client=self.cortex_client,
        )

    def run_task(self, task: EvalTask, page: Optional[Any] = None) -> EvalResult:
        """Run an individual OSWorld task and evaluate its assertions.

        Args:
            task: The EvalTask specification to run.
            page: Optional pre-existing page or desktop mock session.

        Returns:
            Structured EvalResult.
        """
        t0 = time.perf_counter()

        # 1. Reset environment if requested
        if self.reset_between_tasks:
            start_state = task.metadata.get("start_state", {})
            init_files = start_state.get("files")
            init_hist = start_state.get("terminal_history")
            init_out = start_state.get("terminal_output")
            self.env.reset(
                initial_files=init_files,
                initial_terminal_history=init_hist,
                initial_terminal_output=init_out,
            )

        # 2. Acquire or construct page / desktop session
        active_page = page
        browser = None
        pw = None

        if active_page is None:
            if self.mock_mode:
                active_page = MockOSWorldPage(initial_url=task.start_url, env=self.env)
            else:
                active_page, browser, pw = self.eval_runner._acquire_page(
                    task.start_url, None
                )

        # 3. Run task actions through EvalRunner (HybridRunner or ReflexRunner)
        base_result = self.eval_runner.run_task(task, page=active_page)

        # 4. Evaluate OSWorld assertions via OSWorldAssertionAdapter
        assertion_results = self.assertion_adapter.evaluate_all(task.expected_assertions)

        # 5. Determine overall task success
        all_passed = all(a.passed for a in assertion_results) if assertion_results else True
        task_success = all_passed and not base_result.aborted

        duration_ms = (time.perf_counter() - t0) * 1000.0

        # Clean up live page if dynamically launched
        if page is None and not self.mock_mode:
            self.eval_runner._release_page(active_page, browser, pw)

        return EvalResult(
            task_id=task.task_id,
            success=task_success,
            total_steps=base_result.total_steps,
            reflex_steps=base_result.reflex_steps,
            escalations=base_result.escalations,
            recoveries_attempted=base_result.recoveries_attempted,
            recoveries_succeeded=base_result.recoveries_succeeded,
            milestones_detected=base_result.milestones_detected,
            aborted=base_result.aborted,
            abort_reason=base_result.abort_reason,
            duration_ms=duration_ms,
            cost_usd=base_result.cost_usd,
            telemetry_summary=base_result.telemetry_summary,
            assertion_results=assertion_results,
            mode=self.mode,
            completed_steps=base_result.completed_steps,
            final_state_hash=base_result.final_state_hash,
            metadata={
                "osworld": True,
                "domain": task.category,
                "assertions_count": len(assertion_results),
                "passed_assertions_count": sum(1 for a in assertion_results if a.passed),
            },
        )

    def run_all(self, tasks: Sequence[EvalTask]) -> List[EvalResult]:
        """Execute a batch of OSWorld tasks sequentially.

        Args:
            tasks: Sequence of EvalTasks to evaluate.

        Returns:
            List of resulting EvalResult instances.
        """
        results: List[EvalResult] = []
        for task in tasks:
            logger.info("Executing OSWorld task: %s - %s", task.task_id, task.name)
            res = self.run_task(task)
            results.append(res)
        return results
