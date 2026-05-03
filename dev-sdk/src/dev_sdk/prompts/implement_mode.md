## Task context

Read the task context in the `comms` directory (files listed in `comms/index.txt`, **in order**). There may be new entries since you last read it—**double-check** `comms/index.txt` and read any new files before proceeding.

## Implementation

Implement the task as described in comms. Match existing code style and conventions in the workspace. Prefer minimal, focused changes.

### No nested git repository

If the task workspace has **no** direct child directory that is a git clone (no child directory containing `.git/`), this is an ops-only or no-repository task: complete the work at the task root (for example comms files, scripts, or other artifacts as the task requires). **Do not** run `dev create-pr`, GitHub pull-request flows, or other automation that assumes a nested git repository exists. **Do not** insist on `git fetch` / merge / push inside a repository subdirectory that is not present.

### Single nested git repository (typical code task)

If there is exactly one direct subdirectory under the task root that contains `.git/`, treat that directory as the git project for code changes. **Commit** your changes when the work is complete. Then, in that **nested git project directory** (not the task root): fetch from `origin`, merge `origin/main` into the current branch, then push the current branch to `origin`.

### Multiple nested repositories

If more than one nested git clone exists, avoid destructive git operations unless comms clearly identify which repository to use.

## Comms

Add implementation notes or results under `comms/` when appropriate and append new filenames to `comms/index.txt` per task conventions.
