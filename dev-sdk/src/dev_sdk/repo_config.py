"""Config file mapping repo shorthand to repo URLs."""

from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "dev"
CONFIG_FILE = CONFIG_DIR / "repos.json"


def _is_url(repo: str) -> bool:
    """True if repo looks like a URL (has scheme or git@)."""
    return "://" in repo or repo.startswith("git@")


def load_repos() -> dict[str, str]:
    """Load shorthand -> url mapping from config file. Returns {} if missing."""
    if not CONFIG_FILE.exists():
        return {}
    import json

    text = CONFIG_FILE.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def save_repos(repos: dict[str, str]) -> None:
    """Write shorthand -> url mapping to config file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    import json

    CONFIG_FILE.write_text(json.dumps(repos, indent=2), encoding="utf-8")


def resolve_repo(repo: str) -> str:
    """Resolve repo to a full URL. If repo looks like a URL, return as-is. Else look up in config."""
    if _is_url(repo):
        return repo
    repos = load_repos()
    if repo not in repos:
        raise ValueError(f"Unknown repo shorthand: {repo!r}. Add it with: dev repos add {repo} <url>")
    return repos[repo]


def remove_repo(name: str) -> bool:
    """Remove a shorthand from config. Returns True if it existed and was removed, False if not found."""
    repos = load_repos()
    if name not in repos:
        return False
    del repos[name]
    save_repos(repos)
    return True
