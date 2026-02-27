#!/bin/bash
# Launch Cursor agent with chat ID for this task
# Prompt the agent to do the task described in task.md
exec cursor agent --force --resume d4bbd0b2-9e79-4320-8167-80be5a05953d "Read the task in task.md and do it"
