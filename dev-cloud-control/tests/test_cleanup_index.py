"""Tests for comms index scrubbing."""

from dev_cloud_control.store import scrub_comms_index_content


def test_scrub_index_removes_self_reference_and_dedupes() -> None:
    raw = "001-user.md\nindex.txt\n001-user.md\n002-agent.md\n"
    assert scrub_comms_index_content(raw) == "001-user.md\n002-agent.md\n"
