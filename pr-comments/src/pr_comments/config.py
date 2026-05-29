import json
from pathlib import Path

from pr_comments.errors import PrCommentsError
from pr_comments.models import Provider, WorkspaceConfig
from pr_comments.parse import parse_pr_url

CONFIG_FILENAME = "pr-comments.json"


def config_path(work_dir: Path) -> Path:
    return work_dir / CONFIG_FILENAME


def load_config(work_dir: Path) -> WorkspaceConfig:
    path = config_path(work_dir)
    if not path.is_file():
        raise PrCommentsError(
            f"No workspace config at {path}. Run `pr-comments init <pr-url>` first."
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise PrCommentsError(f"Invalid config file {path}: {e}") from e
    if not isinstance(raw, dict):
        raise PrCommentsError(f"Expected JSON object in {path}")
    pr_url = raw.get("pr_url")
    provider = raw.get("provider")
    owner = raw.get("owner")
    repo = raw.get("repo")
    pr_id = raw.get("pr_id")
    if not all(isinstance(x, str) for x in (pr_url, provider, owner, repo)):
        raise PrCommentsError(f"Missing or invalid fields in {path}")
    if provider not in ("github", "bitbucket"):
        raise PrCommentsError(f"Unknown provider {provider!r} in {path}")
    if not isinstance(pr_id, int):
        raise PrCommentsError(f"Missing or invalid pr_id in {path}")
    return WorkspaceConfig(
        pr_url=pr_url,
        provider=provider,  # type: ignore[arg-type]
        owner=owner,
        repo=repo,
        pr_id=pr_id,
    )


def save_config(work_dir: Path, pr_url: str) -> WorkspaceConfig:
    cfg = parse_pr_url(pr_url)
    work_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "pr_url": cfg.pr_url,
        "provider": cfg.provider,
        "owner": cfg.owner,
        "repo": cfg.repo,
        "pr_id": cfg.pr_id,
    }
    config_path(work_dir).write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )
    return cfg
