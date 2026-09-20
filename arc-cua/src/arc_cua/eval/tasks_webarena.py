"""WebArena Subset Task Definitions for ARC (Phase 4B).

Curated representative subset of 12 WebArena tasks across 3 core domains:
- Reddit (Postmill forum)
- Shopping (OneStopShop / Magento)
- GitLab (Code repository & issue tracker)

Includes all primary evaluation modalities:
- url_match: Verifies target page navigation
- string_match: Verifies content rendering
- program_html: Verifies backend state persistence via database queries

Fully runnable in offline mock mode and compatible with live WebArena containers.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..schemas import ActionStep
from .schemas import EvalTask
from .webarena_env import WebArenaEnv
from .webarena_mapper import map_webarena_task

RAW_WEBARENA_SUBSET: List[Dict[str, Any]] = [
    # -------------------------------------------------------------------------
    # Reddit Domain (Tasks 101 - 104)
    # -------------------------------------------------------------------------
    {
        "task_id": 101,
        "intent": "Search for discussion posts in the technology subreddit",
        "start_url": "__REDDIT__/f/technology",
        "sites": ["reddit"],
        "require_login": False,
        "eval": {
            "eval_types": ["url_match", "string_match"],
            "reference_url": "__REDDIT__/f/technology",
            "url_note": "exact",
            "reference_answers": {
                "fuzzy_match": ["Welcome to Arc Research", "Initial discussion thread"]
            },
        },
    },
    {
        "task_id": 102,
        "intent": "Post a comment 'Helpful analysis on the architecture' on the first post",
        "start_url": "__REDDIT__/f/technology/1",
        "sites": ["reddit"],
        "require_login": True,
        "eval": {
            "eval_types": ["program_html", "string_match"],
            "program_html": [
                {
                    "point": "db",
                    "locator": "SELECT count(*) as count FROM reddit_comments WHERE post_id = 1 AND content LIKE '%Helpful analysis%'",
                    "expected": 1,
                }
            ],
            "reference_answers": {"fuzzy_match": ["Helpful analysis on the architecture"]},
        },
    },
    {
        "task_id": 103,
        "intent": "Navigate to the admin user profile and view recent submissions",
        "start_url": "__REDDIT__/user/admin",
        "sites": ["reddit"],
        "require_login": False,
        "eval": {
            "eval_types": ["url_match", "string_match"],
            "reference_url": "__REDDIT__/user/admin",
            "url_note": "exact",
            "reference_answers": {"fuzzy_match": ["admin", "Submissions"]},
        },
    },
    {
        "task_id": 104,
        "intent": "Create a new discussion post titled 'Benchmarking CUA Agents' in general subforum",
        "start_url": "__REDDIT__/submit",
        "sites": ["reddit"],
        "require_login": True,
        "eval": {
            "eval_types": ["program_html"],
            "program_html": [
                {
                    "point": "db",
                    "locator": "SELECT count(*) as count FROM reddit_posts WHERE title = 'Benchmarking CUA Agents' AND subforum = 'general'",
                    "expected": 1,
                }
            ],
        },
    },
    # -------------------------------------------------------------------------
    # Shopping Domain (Tasks 201 - 204)
    # -------------------------------------------------------------------------
    {
        "task_id": 201,
        "intent": "Search for Ultra Slim Laptop in the store catalog",
        "start_url": "__SHOPPING__/catalogsearch/result?q=laptop",
        "sites": ["shopping"],
        "require_login": False,
        "eval": {
            "eval_types": ["url_match", "string_match"],
            "reference_url": "__SHOPPING__/catalogsearch/result?q=laptop",
            "url_note": "exact",
            "reference_answers": {"fuzzy_match": ["Ultra Slim Laptop", "$999.99"]},
        },
    },
    {
        "task_id": 202,
        "intent": "Add the Ultra Slim Laptop to the shopping cart",
        "start_url": "__SHOPPING__/products/ultra-slim-laptop",
        "sites": ["shopping"],
        "require_login": False,
        "eval": {
            "eval_types": ["program_html", "string_match"],
            "program_html": [
                {
                    "point": "db",
                    "locator": "SELECT count(*) as count FROM shopping_cart WHERE product_id = 'SKU-LAPTOP-01'",
                    "expected": 1,
                }
            ],
            "reference_answers": {"fuzzy_match": ["Added to cart"]},
        },
    },
    {
        "task_id": 203,
        "intent": "Navigate to the shopping cart page and verify items summary",
        "start_url": "__SHOPPING__/checkout/cart",
        "sites": ["shopping"],
        "require_login": False,
        "eval": {
            "eval_types": ["url_match", "string_match"],
            "reference_url": "__SHOPPING__/checkout/cart",
            "url_note": "exact",
            "reference_answers": {"fuzzy_match": ["Shopping Cart", "Order Summary"]},
        },
    },
    {
        "task_id": 204,
        "intent": "Complete checkout order for customer tester@arc.local",
        "start_url": "__SHOPPING__/checkout/onepage",
        "sites": ["shopping"],
        "require_login": True,
        "eval": {
            "eval_types": ["program_html", "url_match"],
            "reference_url": "__SHOPPING__/checkout/onepage/success",
            "url_note": "exact",
            "program_html": [
                {
                    "point": "db",
                    "locator": "SELECT count(*) as count FROM shopping_orders WHERE order_number = 'ORD-2026-001' AND customer_email = 'tester@arc.local'",
                    "expected": 1,
                }
            ],
        },
    },
    # -------------------------------------------------------------------------
    # GitLab Domain (Tasks 301 - 304)
    # -------------------------------------------------------------------------
    {
        "task_id": 301,
        "intent": "Find and view issue #1 in core engine repository",
        "start_url": "__GITLAB__/core/engine/issues/1",
        "sites": ["gitlab"],
        "require_login": False,
        "eval": {
            "eval_types": ["url_match", "string_match"],
            "reference_url": "__GITLAB__/core/engine/issues/1",
            "url_note": "exact",
            "reference_answers": {
                "fuzzy_match": ["Fix memory leak in buffer pool", "High priority bug"]
            },
        },
    },
    {
        "task_id": 302,
        "intent": "Create a new issue titled 'Add telemetry monitoring for CUA' in core engine",
        "start_url": "__GITLAB__/core/engine/issues/new",
        "sites": ["gitlab"],
        "require_login": True,
        "eval": {
            "eval_types": ["program_html"],
            "program_html": [
                {
                    "point": "db",
                    "locator": "SELECT count(*) as count FROM gitlab_issues WHERE title = 'Add telemetry monitoring for CUA'",
                    "expected": 1,
                }
            ],
        },
    },
    {
        "task_id": 303,
        "intent": "Navigate to the open merge requests view in core engine repository",
        "start_url": "__GITLAB__/core/engine/-/merge_requests",
        "sites": ["gitlab"],
        "require_login": False,
        "eval": {
            "eval_types": ["url_match", "string_match"],
            "reference_url": "__GITLAB__/core/engine/-/merge_requests",
            "url_note": "exact",
            "reference_answers": {"fuzzy_match": ["Merge Requests", "core/engine"]},
        },
    },
    {
        "task_id": 304,
        "intent": "Create a merge request from branch feature/eval into main",
        "start_url": "__GITLAB__/core/engine/-/merge_requests/new",
        "sites": ["gitlab"],
        "require_login": True,
        "eval": {
            "eval_types": ["program_html"],
            "program_html": [
                {
                    "point": "db",
                    "locator": "SELECT count(*) as count FROM gitlab_merge_requests WHERE source_branch = 'feature/eval' AND target_branch = 'main'",
                    "expected": 1,
                }
            ],
        },
    },
]

# Action steps for testing mock task execution deterministically
MOCK_TASK_ACTIONS: Dict[int, List[ActionStep]] = {
    101: [],
    102: [
        ActionStep(step_number=1, verb="TYPE", target_selector="textarea#comment-body", value="Helpful analysis on the architecture", action_index=None, latency_ms=0, success=True),
        ActionStep(step_number=2, verb="CLICK", target_selector="button#submit-comment", value=None, action_index=None, latency_ms=0, success=True),
    ],
    103: [],
    104: [
        ActionStep(step_number=1, verb="TYPE", target_selector="input#post-title", value="Benchmarking CUA Agents", action_index=None, latency_ms=0, success=True),
        ActionStep(step_number=2, verb="CLICK", target_selector="button#submit-post", value=None, action_index=None, latency_ms=0, success=True),
    ],
    201: [],
    202: [
        ActionStep(step_number=1, verb="CLICK", target_selector="button#add-to-cart", value=None, action_index=None, latency_ms=0, success=True),
    ],
    203: [],
    204: [
        ActionStep(step_number=1, verb="CLICK", target_selector="button#place-order", value=None, action_index=None, latency_ms=0, success=True),
    ],
    301: [],
    302: [
        ActionStep(step_number=1, verb="TYPE", target_selector="input#issue-title", value="Add telemetry monitoring for CUA", action_index=None, latency_ms=0, success=True),
        ActionStep(step_number=2, verb="CLICK", target_selector="button#create-issue", value=None, action_index=None, latency_ms=0, success=True),
    ],
    303: [],
    304: [
        ActionStep(step_number=1, verb="TYPE", target_selector="input#branch-source", value="feature/eval", action_index=None, latency_ms=0, success=True),
        ActionStep(step_number=2, verb="CLICK", target_selector="button#create-mr", value=None, action_index=None, latency_ms=0, success=True),
    ],
}

def create_webarena_subset(env: Optional[WebArenaEnv] = None) -> List[EvalTask]:
    """Instantiate the 12 curated WebArena subset tasks as EvalTask instances."""
    tasks: List[EvalTask] = []
    for raw in RAW_WEBARENA_SUBSET:
        task_id_num = raw.get("task_id", 0)
        actions = MOCK_TASK_ACTIONS.get(task_id_num, [])
        task = map_webarena_task(raw, env=env, action_steps=actions)
        tasks.append(task)
    return tasks


def get_webarena_task_by_id(
    task_id: str,
    env: Optional[WebArenaEnv] = None,
) -> Optional[EvalTask]:
    """Retrieve a single WebArena subset task by ID (e.g. 'webarena_101' or '101')."""
    target = task_id.lower()
    if not target.startswith("webarena_") and target.isdigit():
        target = f"webarena_{target}"

    for t in create_webarena_subset(env=env):
        if t.task_id.lower() == target:
            return t
    return None


def get_webarena_tasks_by_domain(
    domain: str,
    env: Optional[WebArenaEnv] = None,
) -> List[EvalTask]:
    """Retrieve all subset tasks belonging to a specific domain (reddit, shopping, gitlab)."""
    domain_norm = domain.lower()
    return [t for t in create_webarena_subset(env=env) if t.category.lower() == domain_norm]
