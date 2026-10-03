"""GitHub webhook handling: verify the signature, then decide if the event is worth a job."""

import hashlib
import hmac
from dataclasses import dataclass, field

from redtogreen.config import Settings


@dataclass
class RunInfo:
    owner: str
    repo: str
    run_id: int
    head_sha: str
    head_branch: str
    pr_numbers: list[int] = field(default_factory=list)
    workflow_name: str = ""
    html_url: str = ""

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


def verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """GitHub signs every delivery with HMAC-SHA256 using the webhook secret.
    Anyone can POST to our URL; only GitHub knows the secret. Fail closed if no secret is set."""
    if not secret or not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)  # constant time: no timing leaks


def parse_workflow_run(event: str, payload: dict, settings: Settings) -> tuple[RunInfo | None, str]:
    """Return (RunInfo, "") for a failed CI run we should fix, else (None, reason it was skipped)."""
    if event != "workflow_run":
        return None, f"ignored event '{event}'"
    if payload.get("action") != "completed":
        return None, "run not completed yet"
    run = payload.get("workflow_run") or {}
    if run.get("conclusion") != "failure":
        return None, f"conclusion is '{run.get('conclusion')}', not a failure"

    full_name = (payload.get("repository") or {}).get("full_name", "")
    allowed = settings.allowed_repo_set()
    if allowed and full_name.lower() not in allowed:
        return None, f"repository {full_name} is not in ALLOWED_REPOS"

    branch = run.get("head_branch") or ""
    if branch.startswith(settings.fix_branch_prefix):
        # Our own fix branch failed CI. Never fix our own fixes: that is how infinite loops start.
        return None, "failure on a RedToGreen fix branch (loop prevention)"

    head_repo = (run.get("head_repository") or {}).get("full_name")
    if head_repo and head_repo.lower() != full_name.lower():
        return None, "pull request from a fork (we cannot push to it, and its code is untrusted)"

    owner, _, repo = full_name.partition("/")
    return RunInfo(
        owner=owner,
        repo=repo,
        run_id=int(run["id"]),
        head_sha=run["head_sha"],
        head_branch=branch,
        pr_numbers=[pr["number"] for pr in run.get("pull_requests") or [] if "number" in pr],
        workflow_name=run.get("name", ""),
        html_url=run.get("html_url", ""),
    ), ""
