# pr-comments

Standalone CLI and library for incrementally pulling pull-request review comments from **GitHub** or **Bitbucket Cloud**.

Use it on its own (no dev stack required), or as a library from other tools.

## Core concepts

### Workspace

Run commands from a directory that acts as your **workspace**. All config and pulled comment files live in that directory (typically the current working directory).

| File | Purpose |
|------|---------|
| `pr-comments.json` | Created by `init`: PR URL, provider, and parsed identifiers |
| `NNN-pr-comments.md` | One file per pull that found new comments (`001`, `002`, …) |
| `index.txt` | Optional ordered list of pull files (appended automatically) |

### Incremental pull

Each comment gets a stable hidden key embedded in the Markdown:

```markdown
[//]: # (pr_comment_key: review:991)
```

On every `pull`, the tool scans existing files in the workspace, skips comments already saved, fetches the rest from the provider API, and writes a new numbered file only when there are new comments.

Legacy HTML markers (`<!-- pr_comment_key: ... -->`) are still recognized.

### Providers

| Provider | PR URL example |
|----------|----------------|
| GitHub | `https://github.com/acme/repo/pull/42` |
| Bitbucket Cloud | `https://bitbucket.org/workspace/repo/pull-requests/7` |

GitHub keys use `review:` / `issue:` prefixes. Bitbucket keys use `bb:inline:` / `bb:general:`.

## Installation

From the dev monorepo (development):

```bash
cd dev
uv sync
```

Or install the package directly:

```bash
pip install ./pr-comments
```

## Usage

```bash
mkdir ~/reviews/feature-x && cd ~/reviews/feature-x

# One-time setup
pr-comments init https://github.com/acme/repo/pull/42

# Repeat as review progresses
export GITHUB_TOKEN=ghp_...
pr-comments pull
```

Bitbucket Cloud:

```bash
pr-comments init https://bitbucket.org/workspace/repo/pull-requests/7
export BITBUCKET_USERNAME=me BITBUCKET_APP_PASSWORD=...
pr-comments pull
```

### Commands

**`pr-comments init <pr-url>`**

Parse and validate the PR URL, write `pr-comments.json`. Fails if the workspace is already initialized or if pulled comment files already exist in the directory.

**`pr-comments pull`**

Load workspace config, authenticate, fetch comments, dedupe against prior files, and write `NNN-pr-comments.md` when there are new comments.

Options:

- `--work-dir PATH` — workspace directory (default: `.`)
- `--token TOKEN` — GitHub PAT or Bitbucket app password (overrides env)
- `--username USER` — Bitbucket username (or `BITBUCKET_USERNAME`)

### Authentication

No AWS or shared bot config is required. Credentials come from the environment or flags:

| Provider | Environment | Flags |
|----------|-------------|-------|
| GitHub | `GITHUB_TOKEN` or `GH_TOKEN` | `--token` |
| Bitbucket Cloud | `BITBUCKET_USERNAME` + `BITBUCKET_APP_PASSWORD` | `--username` + `--token` |

For local GitHub use you can pipe `gh auth token`:

```bash
export GITHUB_TOKEN="$(gh auth token)"
pr-comments pull
```

GitHub tokens need permission to read pull requests. Bitbucket app passwords need `read:pullrequest:bitbucket`.

## Library API

```python
from pathlib import Path
from pr_comments import PullResult, init_workspace, pull_comments

init_workspace(Path("."), "https://github.com/acme/repo/pull/42")
result: PullResult = pull_comments(Path("."), token="ghp_...")
# result.pr_url, result.new_count, result.output_filename, result.markdown
```

Pass `write_output=callable` to control where Markdown is written (used by the dev stack to route output into task comms).

## Python API errors

Operations raise `pr_comments.PrCommentsError` on validation or API failures.
