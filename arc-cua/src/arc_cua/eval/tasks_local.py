"""Local Synthetic Task Suite for ARC (Phase 4A).

Implements Task 4A.3:
- Provides at least 12 local evaluation tasks across 12 distinct categories.
- Covers healthy pathways, stuck states, missing locators, recovery flows, multi-step milestones,
  readiness-blocked elements, and intentional assertion failures.
- Uses typed ActionStep objects and EvalAssertion specifications.
- Runs entirely against tests/fixtures/eval_site.html without external network access.
"""

from __future__ import annotations

import pathlib
from typing import Dict, List, Optional

from ..schemas import ActionStep
from .schemas import AssertionType, ElementState, EvalAssertion, EvalTask

FIXTURE_PATH = pathlib.Path(__file__).parent.parent.parent.parent / "tests" / "fixtures" / "eval_site.html"
FIXTURE_URL = f"file://{FIXTURE_PATH.resolve().as_posix()}"


def get_fixture_url() -> str:
    """Return resolved file URL for the local evaluation fixture HTML."""
    return FIXTURE_URL


def create_local_tasks(fixture_url: Optional[str] = None) -> List[EvalTask]:
    """Instantiate the complete suite of local evaluation tasks."""
    url = fixture_url or get_fixture_url()

    tasks: List[EvalTask] = [
        # 1. Healthy Form Task
        EvalTask(
            task_id="task_healthy_form",
            name="Healthy Form Submission",
            category="healthy_form",
            description="Fills user name and email in the form and clicks submit.",
            start_url=url,
            action_steps=[
                ActionStep(
                    step_number=1,
                    verb="TYPE",
                    target_selector="input#user-name",
                    value="arc_tester",
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
                ActionStep(
                    step_number=2,
                    verb="TYPE",
                    target_selector="input#user-email",
                    value="tester@arc.local",
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
                ActionStep(
                    step_number=3,
                    verb="CLICK",
                    target_selector="button#submit-form-btn",
                    value=None,
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
            ],
            expected_assertions=[
                EvalAssertion(
                    type=AssertionType.VISIBLE_TEXT,
                    selector="div#form-result",
                    expected="Form submitted: arc_tester (tester@arc.local)",
                    description="Form result shows submitted username and email",
                ),
                EvalAssertion(
                    type=AssertionType.ELEMENT_STATE,
                    selector="div#form-result",
                    expected=ElementState.VISIBLE,
                    description="Form result container is visible",
                ),
            ],
            max_steps=10,
            tags=["healthy", "form", "baseline"],
        ),

        # 2. Healthy Navigation Task
        EvalTask(
            task_id="task_healthy_navigation",
            name="Healthy Tab Navigation",
            category="healthy_navigation",
            description="Navigates to the Settings view using navigation tab buttons.",
            start_url=url,
            action_steps=[
                ActionStep(
                    step_number=1,
                    verb="CLICK",
                    target_selector="button#nav-to-settings",
                    value=None,
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
            ],
            expected_assertions=[
                EvalAssertion(
                    type=AssertionType.VISIBLE_TEXT,
                    selector="div#current-view-title",
                    expected="View: Settings",
                    description="Active view title updates to Settings",
                ),
                EvalAssertion(
                    type=AssertionType.URL,
                    expected="#settings",
                    description="URL contains #settings anchor",
                ),
            ],
            max_steps=5,
            tags=["healthy", "navigation"],
        ),

        # 3. Healthy Select Dropdown Task
        EvalTask(
            task_id="task_healthy_dropdown",
            name="Healthy Dropdown Selection",
            category="healthy_dropdown",
            description="Selects high priority option in dropdown and applies it.",
            start_url=url,
            action_steps=[
                ActionStep(
                    step_number=1,
                    verb="SELECT",
                    target_selector="select#priority-select",
                    value="high",
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
                ActionStep(
                    step_number=2,
                    verb="CLICK",
                    target_selector="button#apply-priority-btn",
                    value=None,
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
            ],
            expected_assertions=[
                EvalAssertion(
                    type=AssertionType.VISIBLE_TEXT,
                    selector="div#dropdown-selected-value",
                    expected="Selected: high",
                    description="Dropdown indicator reflects selection",
                ),
                EvalAssertion(
                    type=AssertionType.VISIBLE_TEXT,
                    selector="div#priority-status",
                    expected="Priority set to high",
                    description="Priority status is updated",
                ),
            ],
            max_steps=5,
            tags=["healthy", "dropdown"],
        ),

        # 4. Healthy Scroll-to-Reveal Task
        EvalTask(
            task_id="task_healthy_scroll",
            name="Healthy Scroll and Click",
            category="healthy_scroll",
            description="Scrolls down past tall spacer and clicks revealed target.",
            start_url=url,
            action_steps=[
                ActionStep(
                    step_number=1,
                    verb="SCROLL",
                    target_selector=None,
                    value="down",
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
                ActionStep(
                    step_number=2,
                    verb="CLICK",
                    target_selector="button#revealed-target-btn",
                    value=None,
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
            ],
            expected_assertions=[
                EvalAssertion(
                    type=AssertionType.VISIBLE_TEXT,
                    selector="div#scroll-status",
                    expected="Revealed button clicked successfully",
                    description="Scroll status indicates click completion",
                ),
            ],
            max_steps=6,
            tags=["healthy", "scroll"],
        ),

        # 5. Healthy Input Validation Task
        EvalTask(
            task_id="task_healthy_input_validation",
            name="Healthy Input Validation",
            category="healthy_input_validation",
            description="Inputs valid 8-character token and verifies validation passed.",
            start_url=url,
            action_steps=[
                ActionStep(
                    step_number=1,
                    verb="TYPE",
                    target_selector="input#validated-input",
                    value="token_1234",
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
                ActionStep(
                    step_number=2,
                    verb="CLICK",
                    target_selector="button#validate-btn",
                    value=None,
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
            ],
            expected_assertions=[
                EvalAssertion(
                    type=AssertionType.VISIBLE_TEXT,
                    selector="div#validation-result",
                    expected="Validation Passed: token_1234",
                    description="Validation box confirms valid input",
                ),
                EvalAssertion(
                    type=AssertionType.INPUT_VALUE,
                    selector="input#validated-input",
                    expected="token_1234",
                    description="Input value is preserved",
                ),
            ],
            max_steps=5,
            tags=["healthy", "validation"],
        ),

        # 6. Stuck No-op Task
        EvalTask(
            task_id="task_stuck_noop",
            name="Stuck Loop on No-Op Element",
            category="stuck_noop",
            description="Repeatedly clicks inert button causing zero state changes.",
            start_url=url,
            action_steps=[
                ActionStep(
                    step_number=1,
                    verb="CLICK",
                    target_selector="button#noop-action-btn",
                    value=None,
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
                ActionStep(
                    step_number=2,
                    verb="CLICK",
                    target_selector="button#noop-action-btn",
                    value=None,
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
                ActionStep(
                    step_number=3,
                    verb="CLICK",
                    target_selector="button#noop-action-btn",
                    value=None,
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
            ],
            expected_assertions=[
                EvalAssertion(
                    type=AssertionType.VISIBLE_TEXT,
                    selector="div#noop-status",
                    expected="No-op State Unchanged",
                    description="Status remains unchanged",
                ),
            ],
            max_steps=5,
            tags=["stuck", "noop", "escalation_expected"],
        ),

        # 7. Stuck Missing Locator Task
        EvalTask(
            task_id="task_stuck_missing_locator",
            name="Stuck Missing Locator Failure",
            category="stuck_missing_locator",
            description="Attempts to click an element that does not exist in DOM.",
            start_url=url,
            action_steps=[
                ActionStep(
                    step_number=1,
                    verb="CLICK",
                    target_selector="button#non-existent-button-xyz",
                    value=None,
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
            ],
            expected_assertions=[
                EvalAssertion(
                    type=AssertionType.PAGE_TITLE,
                    expected="ARC Evaluation Suite",
                    description="Page title remains intact despite missing locator",
                ),
            ],
            max_steps=4,
            tags=["stuck", "missing_locator", "escalation_expected"],
        ),

        # 8. Recovery After No-op (Escalation & Recovery validation)
        # Intentionally fails in Reflex-only because recovery button is never clicked without Cortex!
        EvalTask(
            task_id="task_recovery_after_noop",
            name="Recovery After No-Op Stuck Loop",
            category="recovery_after_noop",
            description="Triggers stuck loop; Hybrid runner must escalate and execute recovery action.",
            start_url=url,
            action_steps=[
                ActionStep(
                    step_number=1,
                    verb="CLICK",
                    target_selector="button#stuck-trigger-btn",
                    value=None,
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
                ActionStep(
                    step_number=2,
                    verb="CLICK",
                    target_selector="button#stuck-trigger-btn",
                    value=None,
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
                ActionStep(
                    step_number=3,
                    verb="CLICK",
                    target_selector="button#stuck-trigger-btn",
                    value=None,
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
            ],
            expected_assertions=[
                EvalAssertion(
                    type=AssertionType.VISIBLE_TEXT,
                    selector="div#recovery-status",
                    expected="Recovery Succeeded: State Resumed",
                    description="Requires Cortex recovery to click recovery-action-btn",
                ),
            ],
            max_steps=8,
            tags=["recovery", "escalation", "hybrid_only_success"],
            metadata={
                "recovery_action": {
                    "verb": "CLICK",
                    "target": "button#recovery-action-btn",
                    "value": None,
                }
            },
        ),

        # 9. Recovery After Timeout / Obstacle
        # Second task intentionally failing without recovery!
        EvalTask(
            task_id="task_recovery_after_timeout",
            name="Recovery After Repeated Stagnation",
            category="recovery_after_timeout",
            description="Stagnates on inert element; verifies escalation recovery mechanism.",
            start_url=url,
            action_steps=[
                ActionStep(
                    step_number=1,
                    verb="CLICK",
                    target_selector="button#stuck-trigger-btn",
                    value=None,
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
                ActionStep(
                    step_number=2,
                    verb="CLICK",
                    target_selector="button#stuck-trigger-btn",
                    value=None,
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
                ActionStep(
                    step_number=3,
                    verb="CLICK",
                    target_selector="button#stuck-trigger-btn",
                    value=None,
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
            ],
            expected_assertions=[
                EvalAssertion(
                    type=AssertionType.VISIBLE_TEXT,
                    selector="div#recovery-status",
                    expected="Recovery Succeeded: State Resumed",
                    description="Requires Cortex recovery to execute recovery action",
                ),
            ],
            max_steps=8,
            tags=["recovery", "timeout", "hybrid_only_success"],
            metadata={
                "recovery_action": {
                    "verb": "CLICK",
                    "target": "button#recovery-action-btn",
                    "value": None,
                }
            },
        ),

        # 10. Milestone Progression Task (Validates MilestoneMonitor)
        EvalTask(
            task_id="task_milestone_multi_step",
            name="Multi-Step Milestone Progression",
            category="milestone_multi_step",
            description="Steps sequentially through 3 stages, each detecting a milestone progression.",
            start_url=url,
            action_steps=[
                ActionStep(
                    step_number=1,
                    verb="CLICK",
                    target_selector="button#milestone-step-1",
                    value=None,
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
                ActionStep(
                    step_number=2,
                    verb="CLICK",
                    target_selector="button#milestone-step-2",
                    value=None,
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
                ActionStep(
                    step_number=3,
                    verb="CLICK",
                    target_selector="button#milestone-step-3",
                    value=None,
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
            ],
            expected_assertions=[
                EvalAssertion(
                    type=AssertionType.VISIBLE_TEXT,
                    selector="div#milestone-indicator",
                    expected="Milestone 3 Completed - Workflow Done",
                    description="All 3 milestone stages completed",
                ),
                EvalAssertion(
                    type=AssertionType.STATE_HASH_CHANGED,
                    expected=True,
                    description="Final page hash has diverged from initial state",
                ),
            ],
            max_steps=6,
            tags=["milestone", "multi_step"],
        ),

        # 11. Second Milestone Validation Task (Multi-field form milestone progression)
        EvalTask(
            task_id="task_milestone_form_progression",
            name="Milestone Form Progress Tracking",
            category="milestone_multi_step",
            description="Tracks sequential progress across fields as distinct milestones.",
            start_url=url,
            action_steps=[
                ActionStep(
                    step_number=1,
                    verb="TYPE",
                    target_selector="input#user-name",
                    value="bob",
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
                ActionStep(
                    step_number=2,
                    verb="TYPE",
                    target_selector="input#user-email",
                    value="bob@arc.local",
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
                ActionStep(
                    step_number=3,
                    verb="CLICK",
                    target_selector="button#submit-form-btn",
                    value=None,
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
            ],
            expected_assertions=[
                EvalAssertion(
                    type=AssertionType.VISIBLE_TEXT,
                    selector="div#form-result",
                    expected="Form submitted: bob (bob@arc.local)",
                    description="Form completed through milestone stages",
                ),
                EvalAssertion(
                    type=AssertionType.STATE_HASH_CHANGED,
                    expected=True,
                    description="State hash changed after form submission",
                ),
            ],
            max_steps=6,
            tags=["milestone", "form"],
        ),

        # 12. Readiness Blocked Element Task
        EvalTask(
            task_id="task_readiness_blocked_element",
            name="Readiness Guard Blocked Element",
            category="readiness_blocked_element",
            description="Attempts interaction with hidden/zero-pixel element, triggering SessionGuard.",
            start_url=url,
            action_steps=[
                ActionStep(
                    step_number=1,
                    verb="CLICK",
                    target_selector="button#hidden-element",
                    value=None,
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
            ],
            expected_assertions=[
                EvalAssertion(
                    type=AssertionType.ELEMENT_STATE,
                    selector="button#hidden-element",
                    expected=ElementState.HIDDEN,
                    description="Hidden element is verified hidden",
                ),
            ],
            max_steps=4,
            tags=["readiness", "blocked", "escalation_expected"],
        ),

        # 13. Intentional Assertion Failure Task (Verifies assertion failure handling)
        EvalTask(
            task_id="task_assertion_failure",
            name="Intentional Assertion Failure Verification",
            category="assertion_failure",
            description="Executes action but checks an intentionally mismatched expected assertion.",
            start_url=url,
            action_steps=[
                ActionStep(
                    step_number=1,
                    verb="CLICK",
                    target_selector="button#nav-to-overview",
                    value=None,
                    action_index=None,
                    latency_ms=0,
                    success=True,
                ),
            ],
            expected_assertions=[
                EvalAssertion(
                    type=AssertionType.VISIBLE_TEXT,
                    selector="div#current-view-title",
                    expected="View: NonexistentViewThatWillFailAssertion",
                    description="Intentionally mismatched expected text to prove assertion failure detection",
                ),
            ],
            max_steps=4,
            tags=["assertion_failure", "negative_test"],
        ),
    ]

    return tasks


def get_task_by_id(task_id: str, fixture_url: Optional[str] = None) -> Optional[EvalTask]:
    """Retrieve an individual task by its unique ID."""
    for task in create_local_tasks(fixture_url):
        if task.task_id == task_id:
            return task
    return None


def get_tasks_by_category(category: str, fixture_url: Optional[str] = None) -> List[EvalTask]:
    """Retrieve all tasks matching a category name."""
    return [task for task in create_local_tasks(fixture_url) if task.category == category]
