"""Resolve per-task list status from command state and comms index."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from dev_sdk.question_schema import parse_question_output

_CANCELLED_ERRORS = frozenset({"Cancelled", "Cancelled."})


class TaskListStatus(str, Enum):
    IDLE = "idle"
    WORKER_ISSUE = "worker_issue"
    SYNCING = "syncing"
    RUNNING = "running"
    FAILED = "failed"
    WAITING_FOR_ANSWERS = "waiting_for_answers"
    READY_FOR_NEXT_STEP = "ready_for_next_step"
    PLAN_COMPLETE = "plan_complete"
    IMPLEMENT_COMPLETE = "implement_complete"
    MERGE_FROM_MAIN_COMPLETE = "merge_from_main_complete"
    USER_COMMENT = "user_comment"
    PR_COMMENTS = "pr_comments"
    BASH_COMPLETE = "bash_complete"


@dataclass(frozen=True)
class TaskStatusInput:
    active: bool = False
    command: str | None = None
    command_error: str | None = None
    queued: bool = False
    pending_state: str | None = None
    comms_index: tuple[str, ...] = ()
    latest_feed_comms_filename: str | None = None
    latest_question_content: str | None = None


def latest_feed_comms_filename(
    feed_entries: tuple[tuple[str, float], ...],
    *,
    suffix: str | None = None,
) -> str | None:
    """Return the feed comms id with the greatest created_at, optionally filtered by suffix."""
    entries = feed_entries
    if suffix is not None:
        entries = tuple((name, ts) for name, ts in feed_entries if name.endswith(suffix))
    if not entries:
        return None
    return max(entries, key=lambda item: (item[1], item[0]))[0]


def _latest_comms_filename(inp: TaskStatusInput) -> str | None:
    if inp.latest_feed_comms_filename:
        return inp.latest_feed_comms_filename
    return inp.comms_index[-1] if inp.comms_index else None


def is_cancelled_error(error: str | None) -> bool:
    return error in _CANCELLED_ERRORS if error else False


def _question_comms_status(content: str | None) -> TaskListStatus:
    if not content:
        return TaskListStatus.WAITING_FOR_ANSWERS
    payload, _errors = parse_question_output(content)
    if payload is None:
        return TaskListStatus.WAITING_FOR_ANSWERS
    if not payload.questions:
        return TaskListStatus.READY_FOR_NEXT_STEP
    return TaskListStatus.WAITING_FOR_ANSWERS


def resolve_task_list_status(inp: TaskStatusInput) -> TaskListStatus:
    """Apply priority ladder: worker offline → syncing → running → failed → waiting → complete → user activity → idle."""
    if inp.pending_state == "worker_offline":
        return TaskListStatus.WORKER_ISSUE

    if inp.pending_state == "syncing":
        return TaskListStatus.SYNCING

    if inp.active:
        return TaskListStatus.RUNNING

    if inp.queued:
        return TaskListStatus.WORKER_ISSUE

    if inp.command and not inp.active:
        return TaskListStatus.SYNCING

    if inp.command_error and not is_cancelled_error(inp.command_error):
        return TaskListStatus.FAILED

    latest = _latest_comms_filename(inp)
    if latest and latest.endswith("-agent-question.md"):
        return _question_comms_status(inp.latest_question_content)

    if latest and latest.endswith("-agent-plan.md"):
        return TaskListStatus.PLAN_COMPLETE
    if latest and latest.endswith("-agent-implement.md"):
        return TaskListStatus.IMPLEMENT_COMPLETE
    if latest and latest.endswith("-agent-merge-from-main.md"):
        return TaskListStatus.MERGE_FROM_MAIN_COMPLETE

    if latest and latest.endswith("-user.md"):
        return TaskListStatus.USER_COMMENT
    if latest and latest.endswith("-user-answers.md"):
        return TaskListStatus.USER_COMMENT
    if latest and latest.endswith("-agent-pr-comments.md"):
        return TaskListStatus.PR_COMMENTS
    if latest and latest.endswith("-user-bash.md"):
        return TaskListStatus.BASH_COMPLETE

    return TaskListStatus.IDLE


def task_status_input_from_command_body(
    body: dict,
    *,
    comms_index: list[str] | None = None,
    latest_feed_comms_filename: str | None = None,
    latest_question_content: str | None = None,
) -> TaskStatusInput:
    return TaskStatusInput(
        active=bool(body.get("active")),
        command=body.get("command"),
        command_error=body.get("command_error"),
        queued=bool(body.get("queued")),
        pending_state=body.get("pending_state"),
        comms_index=tuple(comms_index or ()),
        latest_feed_comms_filename=latest_feed_comms_filename,
        latest_question_content=latest_question_content,
    )


def enrich_task_status_input_with_comms(
    inp: TaskStatusInput,
    *,
    read_comms_file: Callable[[str], str | None] | None = None,
) -> TaskStatusInput:
    """Load agent-question comms content when the latest feed entry is a question file."""
    latest = _latest_comms_filename(inp)
    if not latest or not latest.endswith("-agent-question.md") or read_comms_file is None:
        return inp
    content = read_comms_file(latest)
    if content is None:
        return inp
    return TaskStatusInput(
        active=inp.active,
        command=inp.command,
        command_error=inp.command_error,
        queued=inp.queued,
        pending_state=inp.pending_state,
        comms_index=inp.comms_index,
        latest_feed_comms_filename=latest,
        latest_question_content=content,
    )
