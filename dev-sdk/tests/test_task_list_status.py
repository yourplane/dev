"""Tests for task list status resolution."""

from dev_sdk.task_list_status import (
    TaskListStatus,
    TaskStatusInput,
    is_cancelled_error,
    resolve_task_list_status,
    task_status_input_from_command_body,
)


def test_idle_when_no_signals() -> None:
    assert resolve_task_list_status(TaskStatusInput()) == TaskListStatus.IDLE


def test_worker_issue_when_queued() -> None:
    inp = TaskStatusInput(queued=True, command="create-task", pending_state="syncing")
    assert resolve_task_list_status(inp) == TaskListStatus.WORKER_ISSUE


def test_worker_issue_when_worker_offline_even_if_active() -> None:
    inp = TaskStatusInput(active=True, command="implement", pending_state="worker_offline")
    assert resolve_task_list_status(inp) == TaskListStatus.WORKER_ISSUE


def test_running_when_active() -> None:
    inp = TaskStatusInput(active=True, command="implement")
    assert resolve_task_list_status(inp) == TaskListStatus.RUNNING


def test_running_when_syncing_pending() -> None:
    inp = TaskStatusInput(command="question", pending_state="syncing")
    assert resolve_task_list_status(inp) == TaskListStatus.RUNNING


def test_running_when_pending_command() -> None:
    inp = TaskStatusInput(command="question")
    assert resolve_task_list_status(inp) == TaskListStatus.RUNNING


def test_failed_when_command_error() -> None:
    inp = TaskStatusInput(command_error="agent boom")
    assert resolve_task_list_status(inp) == TaskListStatus.FAILED


def test_cancelled_error_is_not_failed() -> None:
    for err in ("Cancelled", "Cancelled."):
        inp = TaskStatusInput(command_error=err)
        assert resolve_task_list_status(inp) == TaskListStatus.IDLE


def test_waiting_when_latest_comms_is_question() -> None:
    inp = TaskStatusInput(comms_index=("001-user.md", "002-agent-question.md"))
    assert resolve_task_list_status(inp) == TaskListStatus.WAITING_FOR_ANSWERS


def test_plan_complete_from_latest_comms() -> None:
    inp = TaskStatusInput(comms_index=("001-user.md", "002-agent-plan.md"))
    assert resolve_task_list_status(inp) == TaskListStatus.PLAN_COMPLETE


def test_implement_complete_from_latest_comms() -> None:
    inp = TaskStatusInput(comms_index=("003-agent-implement.md",))
    assert resolve_task_list_status(inp) == TaskListStatus.IMPLEMENT_COMPLETE


def test_merge_from_main_complete_from_latest_comms() -> None:
    inp = TaskStatusInput(comms_index=("004-agent-merge-from-main.md",))
    assert resolve_task_list_status(inp) == TaskListStatus.MERGE_FROM_MAIN_COMPLETE


def test_running_beats_failed() -> None:
    inp = TaskStatusInput(active=True, command="implement", command_error="old failure")
    assert resolve_task_list_status(inp) == TaskListStatus.RUNNING


def test_running_beats_waiting() -> None:
    inp = TaskStatusInput(
        active=True,
        command="question",
        comms_index=("002-agent-question.md",),
    )
    assert resolve_task_list_status(inp) == TaskListStatus.RUNNING


def test_failed_beats_waiting() -> None:
    inp = TaskStatusInput(
        command_error="boom",
        comms_index=("002-agent-question.md",),
    )
    assert resolve_task_list_status(inp) == TaskListStatus.FAILED


def test_task_status_input_from_command_body() -> None:
    body = {
        "active": False,
        "command": "question",
        "command_error": None,
        "queued": True,
        "pending_state": "worker_offline",
    }
    inp = task_status_input_from_command_body(body, comms_index=["001-user.md"])
    assert inp.queued is True
    assert inp.pending_state == "worker_offline"
    assert inp.comms_index == ("001-user.md",)


def test_is_cancelled_error() -> None:
    assert is_cancelled_error("Cancelled") is True
    assert is_cancelled_error("Cancelled.") is True
    assert is_cancelled_error("boom") is False
    assert is_cancelled_error(None) is False
