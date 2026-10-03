"""The two git operations the worker needs. The token is passed in the URL of each command and
never written to .git/config, so the sandbox (which can read the checkout) never sees it."""

import subprocess
from pathlib import Path


class GitError(Exception):
    pass


def _url(owner: str, repo: str, token: str) -> str:
    auth = f"x-access-token:{token}@" if token else ""
    return f"https://{auth}github.com/{owner}/{repo}.git"


def _run(args: list[str], token: str, cwd: Path | None = None) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False, timeout=300)
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip()
        if token:
            message = message.replace(token, "***")  # never leak the token into logs
        raise GitError(f"git {args[0]} failed: {message}")
    return result.stdout


def clone_at_sha(owner: str, repo: str, sha: str, dest: Path, token: str = "") -> None:
    """Shallow checkout of exactly the commit whose CI failed (not whatever main is now)."""
    dest.mkdir(parents=True, exist_ok=True)
    _run(["init", "-q"], token, cwd=dest)
    _run(["fetch", "-q", "--depth", "1", _url(owner, repo, token), sha], token, cwd=dest)
    _run(["checkout", "-q", "FETCH_HEAD"], token, cwd=dest)


def remote_head(owner: str, repo: str, branch: str, token: str = "") -> str:
    out = _run(["ls-remote", _url(owner, repo, token), f"refs/heads/{branch}"], token)
    return out.split()[0] if out.strip() else ""
