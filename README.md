# dev

CLI for managing AI developer tasks with Cursor agent integration. Tasks live under `~/tasks` (or `DEV_TASKS_DIR`).

## Install

```bash
cd /path/to/dev
pip install -e ".[dev]"
```

Or with tox only for testing:

```bash
pip install -e .
tox
```

## Usage

Create a new task (creates a subdirectory, task file, agent chat, launch script, and clones the repo):

```bash
dev create "My task title" --repo https://github.com/user/repo.git --description "Implement feature X and add tests."
```

Options:

- `--repo` / `-r`: Git repository URL (required).
- `--description` / `-d`: Task description/goal (required).
- `--tasks-dir`: Override tasks root (default: `~/tasks`). Can set `DEV_TASKS_DIR` instead.

The command:

1. Creates `~/tasks/<slug>/` from the task title.
2. Writes `task.md` with the title and description.
3. Runs `cursor agent create-chat`, saves the chat ID, and writes `launch-agent.sh` to resume that chat.
4. Clones the repo into `~/tasks/<slug>/<slug>/`.

Resume the agent for a task:

```bash
~/tasks/<task-slug>/launch-agent.sh
```

## Development

Run tests:

```bash
tox
```

Test a single Python version:

```bash
tox -e py311
```
