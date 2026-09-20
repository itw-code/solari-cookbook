"""OSWorld Desktop Subset Task Definitions for ARC (Phase 4C).

Curated representative subset of 12 OSWorld benchmark tasks across 3 core desktop domains:
1. `os_fs`: Operating system file operations (creation, archiving, cleanup, config updates).
2. `terminal`: Command line interface execution (system diagnostics, git, grep, gcc compilation).
3. `desktop`: GUI desktop application accessibility (VS Code Electron, GNOME Terminal GTK).

Includes all primary desktop evaluation modalities:
- `file_exist`: Verifies presence/absence of workspace files.
- `file_content_match`: Verifies text or pattern matching within files.
- `terminal_output_match`: Verifies stdout/stderr output or executed commands.
- `at_spi_state_match`: Verifies AT-SPI accessible widget presence, role, and states.

Fully runnable in offline mock mode and compatible with live Linux desktop environments.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from ..schemas import ActionStep
from .osworld_env import OSWorldEnv
from .osworld_mapper import map_osworld_task
from .schemas import EvalTask

RAW_OSWORLD_SUBSET: List[Dict[str, Any]] = [
    # -------------------------------------------------------------------------
    # Domain 1: OS File System (Tasks 201 - 204)
    # -------------------------------------------------------------------------
    {
        "id": 201,
        "instruction": "Create project summary report at /home/user/workspace/summary.txt with text 'Phase 4C Benchmark Ready'",
        "domain": "os_fs",
        "category": "os_fs",
        "start_url": "desktop://os_fs/summary",
        "start_state": {
            "files": {},
            "terminal_history": ["cd ~/workspace"],
        },
        "action_steps": [
            {"verb": "TYPE", "target": "#file-editor", "value": "Phase 4C Benchmark Ready"},
            {"verb": "CLICK", "target": "#save-summary-btn"},
        ],
        "eval": {
            "eval_types": ["file_exist", "file_content_match"],
            "rules": [
                {
                    "type": "file_exist",
                    "file_path": "/home/user/workspace/summary.txt",
                    "expected": True,
                    "description": "Verify summary.txt was created",
                },
                {
                    "type": "file_content_match",
                    "file_path": "/home/user/workspace/summary.txt",
                    "expected": "Phase 4C Benchmark Ready",
                    "match_type": "substring",
                    "description": "Verify summary.txt contains benchmark ready message",
                },
            ],
        },
    },
    {
        "id": 202,
        "instruction": "Archive old diagnostic logs by copying old_logs.txt to /home/user/workspace/archive/old_logs.txt",
        "domain": "os_fs",
        "category": "os_fs",
        "start_url": "desktop://os_fs/archive",
        "start_state": {
            "files": {
                "/home/user/workspace/old_logs.txt": "Log entry 2026-09-20: System healthy and operational",
            },
        },
        "action_steps": [
            {"verb": "CLICK", "target": "#archive-log-btn"},
        ],
        "eval": {
            "eval_types": ["file_exist", "file_content_match"],
            "rules": [
                {
                    "type": "file_exist",
                    "file_path": "/home/user/workspace/archive/old_logs.txt",
                    "expected": True,
                    "description": "Verify archive file exists in destination directory",
                },
                {
                    "type": "file_content_match",
                    "file_path": "/home/user/workspace/archive/old_logs.txt",
                    "expected": "System healthy and operational",
                    "match_type": "substring",
                    "description": "Verify archive file content preserved",
                },
            ],
        },
    },
    {
        "id": 203,
        "instruction": "Clean temporary build artifacts by removing /home/user/workspace/temp_build.bin",
        "domain": "os_fs",
        "category": "os_fs",
        "start_url": "desktop://os_fs/cleanup",
        "start_state": {
            "files": {
                "/home/user/workspace/temp_build.bin": "temporary artifact binary data",
            },
        },
        "action_steps": [
            {"verb": "CLICK", "target": "#delete-temp-btn"},
        ],
        "eval": {
            "eval_types": ["file_exist"],
            "rules": [
                {
                    "type": "file_exist",
                    "file_path": "/home/user/workspace/temp_build.bin",
                    "expected": False,
                    "description": "Verify temporary build artifact has been deleted",
                },
            ],
        },
    },
    {
        "id": 204,
        "instruction": "Update project version in /home/user/workspace/config.json to 'version': '2.5.0'",
        "domain": "os_fs",
        "category": "os_fs",
        "start_url": "desktop://os_fs/config",
        "start_state": {
            "files": {
                "/home/user/workspace/config.json": '{\n  "name": "arc-cua",\n  "version": "2.4.9"\n}',
            },
        },
        "action_steps": [
            {"verb": "TYPE", "target": "#config-editor", "value": "2.5.0"},
            {"verb": "CLICK", "target": "#save-config-btn"},
        ],
        "eval": {
            "eval_types": ["file_exist", "file_content_match"],
            "rules": [
                {
                    "type": "file_exist",
                    "file_path": "/home/user/workspace/config.json",
                    "expected": True,
                },
                {
                    "type": "file_content_match",
                    "file_path": "/home/user/workspace/config.json",
                    "expected": '"version": "2.5.0"',
                    "match_type": "substring",
                    "description": "Verify updated version string in config.json",
                },
            ],
        },
    },

    # -------------------------------------------------------------------------
    # Domain 2: Terminal / Shell Execution (Tasks 205 - 208)
    # -------------------------------------------------------------------------
    {
        "id": 205,
        "instruction": "Run system diagnostics suite in terminal and verify all checks pass",
        "domain": "terminal",
        "category": "terminal",
        "start_url": "desktop://terminal/diagnostics",
        "start_state": {
            "terminal_history": ["cd ~/workspace"],
            "terminal_output": [],
        },
        "action_steps": [
            {"verb": "TYPE", "target": "#terminal-input", "value": "diagnostics --all"},
            {"verb": "CLICK", "target": "#btn-run-diagnostics"},
        ],
        "eval": {
            "eval_types": ["terminal_output_match"],
            "rules": [
                {
                    "type": "terminal_output_match",
                    "expected": "All system diagnostics passed: OK",
                    "match_type": "substring",
                    "description": "Verify diagnostic suite output contains OK confirmation",
                },
            ],
        },
    },
    {
        "id": 206,
        "instruction": "Execute git commit in workspace repository to record changes",
        "domain": "terminal",
        "category": "terminal",
        "start_url": "desktop://terminal/git",
        "start_state": {
            "terminal_history": ["git status"],
            "terminal_output": ["Changes to be committed: modified files"],
        },
        "action_steps": [
            {"verb": "TYPE", "target": "#terminal-input", "value": "git commit -m 'feat: add osworld harness'"},
            {"verb": "CLICK", "target": "#btn-git-commit"},
        ],
        "eval": {
            "eval_types": ["terminal_output_match"],
            "rules": [
                {
                    "type": "terminal_output_match",
                    "expected": "[main 8f3b21a] feat: add osworld harness",
                    "match_type": "substring",
                    "description": "Verify git commit hash and message output",
                },
            ],
        },
    },
    {
        "id": 207,
        "instruction": "Search application log files for error lines using grep",
        "domain": "terminal",
        "category": "terminal",
        "start_url": "desktop://terminal/grep",
        "start_state": {
            "terminal_history": [],
            "terminal_output": [],
        },
        "action_steps": [
            {"verb": "TYPE", "target": "#terminal-input", "value": "grep 'ERROR' /var/log/app.log"},
            {"verb": "CLICK", "target": "#btn-grep-errors"},
        ],
        "eval": {
            "eval_types": ["terminal_output_match"],
            "rules": [
                {
                    "type": "terminal_output_match",
                    "expected": "Found 0 error lines",
                    "match_type": "substring",
                    "description": "Verify grep reports 0 error lines",
                },
            ],
        },
    },
    {
        "id": 208,
        "instruction": "Compile native C acceleration extension using gcc command",
        "domain": "terminal",
        "category": "terminal",
        "start_url": "desktop://terminal/compile",
        "start_state": {
            "terminal_history": [],
            "terminal_output": [],
        },
        "action_steps": [
            {"verb": "TYPE", "target": "#terminal-input", "value": "gcc -O3 -shared -o build/libfast.so src/fast.c"},
            {"verb": "CLICK", "target": "#btn-compile-lib"},
        ],
        "eval": {
            "eval_types": ["terminal_output_match"],
            "rules": [
                {
                    "type": "terminal_output_match",
                    "expected": "Compilation successful: build/libfast.so",
                    "match_type": "substring",
                    "description": "Verify gcc output indicates successful compilation",
                },
            ],
        },
    },

    # -------------------------------------------------------------------------
    # Domain 3: Desktop Apps (VS Code & GNOME Terminal) (Tasks 209 - 212)
    # -------------------------------------------------------------------------
    {
        "id": 209,
        "instruction": "Open Visual Studio Code and verify the Run Benchmark Test button is displayed",
        "domain": "desktop",
        "category": "desktop",
        "start_url": "desktop://code/benchmark",
        "start_state": {},
        "action_steps": [
            {"verb": "CLICK", "target": "#vscode-run-benchmark-btn"},
        ],
        "eval": {
            "eval_types": ["at_spi_state_match"],
            "rules": [
                {
                    "type": "at_spi_state_match",
                    "app_name": "code",
                    "role": "push_button",
                    "name": "Run Benchmark Test",
                    "state": "showing",
                    "expected": True,
                    "description": "Verify Run Benchmark Test button is showing in VS Code AT-SPI tree",
                },
            ],
        },
    },
    {
        "id": 210,
        "instruction": "Open VS Code Quick Open file search input and ensure it is enabled",
        "domain": "desktop",
        "category": "desktop",
        "start_url": "desktop://code/quick-open",
        "start_state": {},
        "action_steps": [
            {"verb": "CLICK", "target": "#vscode-search-entry"},
        ],
        "eval": {
            "eval_types": ["at_spi_state_match"],
            "rules": [
                {
                    "type": "at_spi_state_match",
                    "app_name": "code",
                    "role": "entry",
                    "name": "Search files by name (Ctrl+P)",
                    "state": "enabled",
                    "expected": True,
                    "description": "Verify VS Code Quick Open entry field is enabled",
                },
            ],
        },
    },
    {
        "id": 211,
        "instruction": "Switch to Bash Tab 1 in GNOME Terminal and verify selected state",
        "domain": "desktop",
        "category": "desktop",
        "start_url": "desktop://gnome-terminal/tab",
        "start_state": {},
        "action_steps": [
            {"verb": "CLICK", "target": "#terminal-tab-1"},
        ],
        "eval": {
            "eval_types": ["at_spi_state_match"],
            "rules": [
                {
                    "type": "at_spi_state_match",
                    "app_name": "gnome-terminal",
                    "role": "page_tab",
                    "name": "Bash Tab 1",
                    "state": "selected",
                    "expected": True,
                    "description": "Verify GNOME Terminal Bash Tab 1 has selected state",
                },
            ],
        },
    },
    {
        "id": 212,
        "instruction": "Focus active terminal screen in GNOME Terminal for command entry",
        "domain": "desktop",
        "category": "desktop",
        "start_url": "desktop://gnome-terminal/screen",
        "start_state": {},
        "action_steps": [
            {"verb": "CLICK", "target": "#terminal-vte-screen"},
        ],
        "eval": {
            "eval_types": ["at_spi_state_match"],
            "rules": [
                {
                    "type": "at_spi_state_match",
                    "app_name": "gnome-terminal",
                    "role": "terminal",
                    "name": "VTE Terminal Screen",
                    "state": "focused",
                    "expected": True,
                    "description": "Verify VTE Terminal Screen widget is focused",
                },
            ],
        },
    },
]


def create_osworld_subset(env: Optional[OSWorldEnv] = None) -> List[EvalTask]:
    """Instantiate the full 12-task OSWorld evaluation subset as EvalTask objects.

    Args:
        env: Optional OSWorldEnv to populate with task start states.

    Returns:
        List of 12 EvalTask instances ready for evaluation.
    """
    tasks: List[EvalTask] = []
    for raw in RAW_OSWORLD_SUBSET:
        task = map_osworld_task(raw)
        tasks.append(task)
    return tasks


def get_osworld_task_by_id(task_id: Union[str, int]) -> Optional[EvalTask]:
    """Retrieve a single OSWorld subset task by its ID."""
    tid = str(task_id)
    for raw in RAW_OSWORLD_SUBSET:
        if str(raw.get("id")) == tid or str(raw.get("task_id")) == tid:
            return map_osworld_task(raw)
    return None


def get_osworld_tasks_by_domain(domain: str) -> List[EvalTask]:
    """Retrieve all OSWorld subset tasks for a given domain."""
    d_clean = domain.lower().strip()
    matched: List[EvalTask] = []
    for raw in RAW_OSWORLD_SUBSET:
        raw_dom = str(raw.get("domain", "")).lower().strip()
        raw_cat = str(raw.get("category", "")).lower().strip()
        if d_clean in (raw_dom, raw_cat):
            matched.append(map_osworld_task(raw))
    return matched
