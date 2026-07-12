#!/usr/bin/env python3
"""Remove stray index.txt comms feed entries and scrub polluted cloud indexes."""

from __future__ import annotations

import os
import sys


def main() -> int:
    table_name = os.environ.get("DEV_CLOUD_TABLE", "dev-cloud")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "dev-cloud-control", "src"))
    from dev_cloud_control.store import COMMS_INDEX_FILE, CloudStore, scrub_comms_index_content

    store = CloudStore()
    removed_feed = 0
    scrubbed_index = 0
    for task_name in store.list_tasks():
        feed_items = store.list_feed_items(task_name)
        for fi in feed_items:
            if fi.type == "comms" and fi.id == COMMS_INDEX_FILE:
                store.delete_feed_item(task_name, COMMS_INDEX_FILE)
                removed_feed += 1
                print(f"removed feed {COMMS_INDEX_FILE} for {task_name}")
        raw = store.get_comms(task_name, COMMS_INDEX_FILE)
        if raw is None:
            continue
        cleaned = scrub_comms_index_content(raw)
        if cleaned != raw:
            store.put_comms(task_name, COMMS_INDEX_FILE, cleaned, origin="cloud")
            scrubbed_index += 1
            print(f"scrubbed index for {task_name}")
    print(
        f"done: removed_feed={removed_feed} scrubbed_index={scrubbed_index} table={table_name}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
