import os

from pr_comments.errors import PrCommentsError
from pr_comments.models import Provider


def resolve_github_token(token: str | None = None) -> str:
    if token and token.strip():
        return token.strip()
    for env_key in ("GITHUB_TOKEN", "GH_TOKEN"):
        val = os.environ.get(env_key)
        if val and val.strip():
            return val.strip()
    raise PrCommentsError(
        "GitHub token required. Set GITHUB_TOKEN or GH_TOKEN, or pass --token."
    )


def resolve_bitbucket_auth(
    *,
    token: str | None = None,
    username: str | None = None,
) -> tuple[str, str]:
    app_password = token.strip() if token and token.strip() else None
    if not app_password:
        app_password = os.environ.get("BITBUCKET_APP_PASSWORD")
        if app_password:
            app_password = app_password.strip() or None
    user = username.strip() if username and username.strip() else None
    if not user:
        user = os.environ.get("BITBUCKET_USERNAME")
        if user:
            user = user.strip() or None
    if not user or not app_password:
        raise PrCommentsError(
            "Bitbucket credentials required. Set BITBUCKET_USERNAME and "
            "BITBUCKET_APP_PASSWORD, or pass --username and --token."
        )
    return user, app_password


def resolve_auth(
    provider: Provider,
    *,
    token: str | None = None,
    username: str | None = None,
) -> tuple[str, str | None]:
    if provider == "github":
        return resolve_github_token(token), None
    user, password = resolve_bitbucket_auth(token=token, username=username)
    return user, password
