"""GitHub bot (org -> Secrets Manager secret) configuration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

DEFAULT_BOTS_PATH = Path.home() / ".config" / "git-auth" / "bots.json"


class BotsConfigStore(Protocol):
    def load_bots(self) -> list[dict[str, str]]: ...

    def save_bots(self, bots: list[dict[str, str]]) -> None: ...


class FileBotsConfigStore:
    """Local file at ~/.config/git-auth/bots.json."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or DEFAULT_BOTS_PATH

    def load_bots(self) -> list[dict[str, str]]:
        if not self._path.is_file():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if not isinstance(raw, dict):
            return []
        bots = raw.get("bots")
        if not isinstance(bots, list):
            return []
        out: list[dict[str, str]] = []
        for entry in bots:
            if not isinstance(entry, dict):
                continue
            org = entry.get("org")
            secret = entry.get("secret")
            if isinstance(org, str) and isinstance(secret, str) and org.strip() and secret.strip():
                out.append({"org": org.strip(), "secret": secret.strip()})
        return out

    def save_bots(self, bots: list[dict[str, str]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps({"bots": bots}, indent=2) + "\n",
            encoding="utf-8",
        )


def secret_name_for_owner(bots: list[dict[str, str]], owner: str) -> str:
    """Resolve Secrets Manager secret name for a GitHub owner."""
    owner_lower = owner.lower()
    for entry in bots:
        org = entry.get("org", "")
        secret = entry.get("secret", "")
        if org.lower() == owner_lower:
            return secret
    raise ValueError(f"No GitHub bot secret configured for owner {owner!r}")
