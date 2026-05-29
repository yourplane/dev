from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pr_comments.auth import resolve_auth
from pr_comments.config import CONFIG_FILENAME, load_config, save_config
from pr_comments.parse import parse_pr_url
from pr_comments.dedupe import collect_existing_keys, workspace_has_pulled_comments
from pr_comments.errors import PrCommentsError
from pr_comments.format import format_comments_markdown
from pr_comments.models import CommentItem, WorkspaceConfig
from pr_comments.providers.bitbucket import fetch_bitbucket_comments
from pr_comments.providers.github import fetch_github_comments

INDEX_FILE = "index.txt"


@dataclass(frozen=True)
class PullResult:
    pr_url: str
    new_count: int
    output_filename: str | None
    markdown: str | None


def init_workspace(work_dir: Path, pr_url: str) -> WorkspaceConfig:
    work_dir = work_dir.resolve()
    if (work_dir / CONFIG_FILENAME).exists():
        raise PrCommentsError(
            f"Workspace already initialized ({CONFIG_FILENAME} exists in {work_dir})."
        )
    if workspace_has_pulled_comments(work_dir):
        raise PrCommentsError(
            "Cannot init: pulled PR comments already exist in this directory."
        )
    return save_config(work_dir, pr_url)


def _next_output_sequence(work_dir: Path) -> int:
    max_n = 0
    if work_dir.exists():
        for path in work_dir.iterdir():
            if not path.is_file():
                continue
            name = path.name
            if not name.endswith("-pr-comments.md"):
                continue
            try:
                n = int(name.split("-")[0])
                if n > max_n:
                    max_n = n
            except ValueError:
                pass
    return max_n + 1


def _write_default_output(work_dir: Path, markdown: str) -> str:
    work_dir.mkdir(parents=True, exist_ok=True)
    seq = _next_output_sequence(work_dir)
    filename = f"{seq:03d}-pr-comments.md"
    path = work_dir / filename
    path.write_text(markdown, encoding="utf-8")
    idx = work_dir / INDEX_FILE
    with open(idx, "a", encoding="utf-8") as f:
        f.write(filename + "\n")
    return filename


def _fetch_all_comments(
    cfg: WorkspaceConfig,
    token: str,
    username: str | None,
) -> list[CommentItem]:
    if cfg.provider == "github":
        raw = fetch_github_comments(token, cfg.owner, cfg.repo, cfg.pr_id)
    else:
        if username is None:
            raise PrCommentsError("Bitbucket username is required.")
        raw = fetch_bitbucket_comments(
            username, token, cfg.owner, cfg.repo, cfg.pr_id
        )
    return [
        CommentItem(kind=item["kind"], key=item["key"], payload=item["payload"])
        for item in raw
    ]


def pull_comments(
    work_dir: Path,
    *,
    pr_url: str | None = None,
    token: str | None = None,
    username: str | None = None,
    write_output: Callable[[str], str] | None = None,
) -> PullResult:
    work_dir = work_dir.resolve()
    if pr_url is not None:
        cfg = parse_pr_url(pr_url)
    else:
        cfg = load_config(work_dir)

    auth_user, auth_secret = resolve_auth(
        cfg.provider, token=token, username=username
    )
    if cfg.provider == "bitbucket":
        if auth_secret is None:
            raise PrCommentsError("Bitbucket app password is required.")
        bb_username = auth_user
        api_token = auth_secret
    else:
        bb_username = None
        api_token = auth_user

    known_keys = collect_existing_keys(work_dir)
    all_items = _fetch_all_comments(cfg, api_token, bb_username)
    new_items = [item for item in all_items if item.key not in known_keys]

    def _sort_key(item: CommentItem) -> tuple[str, str]:
        created = item.payload.get("created_at") or item.payload.get("created_on")
        return (str(created or ""), item.key)

    new_items.sort(key=_sort_key)

    if not new_items:
        return PullResult(
            pr_url=cfg.pr_url,
            new_count=0,
            output_filename=None,
            markdown=None,
        )

    markdown = format_comments_markdown(cfg.pr_url, cfg.pr_id, new_items)
    if write_output is not None:
        filename = write_output(markdown)
    else:
        filename = _write_default_output(work_dir, markdown)
    return PullResult(
        pr_url=cfg.pr_url,
        new_count=len(new_items),
        output_filename=filename,
        markdown=markdown,
    )
