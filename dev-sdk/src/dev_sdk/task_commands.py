"""Task async command identifiers (dev-server / UI)."""

from enum import Enum


class TaskCommand(str, Enum):
    QUESTION = "question"
    PLAN_IMPLEMENT = "plan-implement"
    IMPLEMENT = "implement"
    DO = "do"
    BASH = "bash"
    MERGE_FROM_MAIN = "merge-from-main"
