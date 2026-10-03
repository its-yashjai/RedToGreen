import hashlib
import hmac

from redtogreen.github.events import parse_workflow_run, verify_signature


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def payload(**run_overrides):
    run = {
        "id": 111, "head_sha": "abc123", "head_branch": "main", "conclusion": "failure", "name": "tests",
        "html_url": "https://github.com/me/demo/actions/runs/111", "pull_requests": [{"number": 7}],
        "head_repository": {"full_name": "me/demo"},
    }
    run.update(run_overrides)
    return {"action": "completed", "workflow_run": run, "repository": {"full_name": "me/demo"}}


def test_signature():
    body = b'{"x": 1}'
    assert verify_signature("s3cret", body, sign("s3cret", body))
    assert not verify_signature("s3cret", body, sign("wrong", body))
    assert not verify_signature("s3cret", body, None)
    assert not verify_signature("", body, sign("", body))  # no secret configured: fail closed


def test_failed_run_becomes_runinfo(settings):
    run, reason = parse_workflow_run("workflow_run", payload(), settings)
    assert reason == ""
    assert (run.full_name, run.run_id, run.head_sha, run.pr_numbers) == ("me/demo", 111, "abc123", [7])


def test_skips(settings):
    cases = {
        "ignored event": ("push", payload()),
        "not a failure": ("workflow_run", payload(conclusion="success")),
        "loop prevention": ("workflow_run", payload(head_branch="redtogreen/run-5")),
        "fork": ("workflow_run", payload(head_repository={"full_name": "stranger/demo"})),
    }
    for expected, (event, body) in cases.items():
        run, reason = parse_workflow_run(event, body, settings)
        assert run is None and expected in reason, (expected, reason)


def test_allowlist(settings):
    strict = settings.model_copy(update={"allowed_repos": "me/other"})
    run, reason = parse_workflow_run("workflow_run", payload(), strict)
    assert run is None and "ALLOWED_REPOS" in reason
