"""Resolve per-task list status from command state and comms index."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

_CANCELLED_ERRORS = frozenset({"Cancelled", "Cancelled."})


class TaskListStatus(str, Enum):
    IDLE = "idle"
    WORKER_ISSUE = "worker_issue"
    RUNNING = "running"
    FAILED = "failed"
    WAITING_FOR_ANSWERS = "waiting_for_answers"
    PLAN_COMPLETE = "plan_complete"
    IMPLEMENT_COMPLETE = "implement_complete"
    MERGE_FROM_MAIN_COMPLETE = "merge_from_main_complete"


@dataclass(frozen=True)
class TaskStatusInput:
    active: bool = False
    command: str | None = None
    command_error: str | None = None
    queued: bool = False
    pending_state: str | None = None
    comms_index: tuple[str, ...] = ()


def is_cancelled_error(error: str | None) -> bool:
    return error in _CANCELLED_ERRORS if error else False


def resolve_task_list_status(inp: TaskStatusInput) -> TaskListStatus:
    """Apply priority ladder: worker issue → running → failed → waiting → complete → idle."""
    if inp.queued or inp.pending_state == "worker_offline":
        return TaskListStatus.WORKER_ISSUE

    if inp.active or inp.pending_state == "syncing":
        return TaskListStatus.RUNNING
    if inp.command and not inp.active:
        return TaskListStatus.RUNNING

    if inp.command_error and not is_cancelled_error(inp.command_error):
        return TaskListStatus.FAILED

    latest = inp.comms_index[-1] if inp.comms_index else None
    if latest and latest.endswith("-agent-question.md"):
        return TaskListStatus.WAITING_FOR_ANSWERS
    if latest and latest.endswith("-agent-plan.md"):
        return TaskListStatus.PLAN_COMPLETE
    if latest and latest.endswith("-agent-implement.md"):
        return TaskListStatus.IMPLEMENT_COMPLETE
    if latest and latest.endswith("-agent-merge-from-main.md"):
        return TaskListStatus.MERGE_FROM_MAIN_COMPLETE

    return TaskListStatus.IDLE


def task_status_input_from_command_body(
    body: dict,
    *,
    comms_index: list[str] | None = None,
) -> TaskStatusInput:
    return TaskStatusInput(
        active=bool(body.get("active")),
        command=body.get("command"),
        command_error=body.get("command_error"),
        queued=bool(body.get("queued")),
        pending_state=body.get("pending_state"),
        comms_index=tuple(comms_index or ()),
    )
