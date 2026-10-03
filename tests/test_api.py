import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from redtogreen.api.app import create_app
from redtogreen.db.models import Job
from redtogreen.db.session import session_scope

SECRET = "webhook-secret"


@pytest.fixture
def client(db, settings):
    enqueued = []
    s = settings.model_copy(update={"github_webhook_secret": SECRET, "admin_token": "admin"})
    app = create_app(s, enqueue_fn=lambda job_id, _settings: enqueued.append(job_id))
    c = TestClient(app)
    c.enqueued = enqueued
    return c


def failed_run_payload(run_id=111, branch="main", conclusion="failure"):
    return {
        "action": "completed",
        "repository": {"full_name": "me/demo"},
        "workflow_run": {"id": run_id, "head_sha": "abc1234def", "head_branch": branch, "conclusion": conclusion,
                         "pull_requests": [], "head_repository": {"full_name": "me/demo"}, "html_url": "u"},
    }


def post(client, payload, event="workflow_run", delivery="d-1", secret=SECRET):
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post("/webhooks/github", content=body, headers={
        "X-GitHub-Event": event, "X-GitHub-Delivery": delivery, "X-Hub-Signature-256": sig,
        "Content-Type": "application/json"})


def test_rejects_bad_signature(client):
    assert post(client, failed_run_payload(), secret="wrong").status_code == 401


def test_ping(client):
    assert post(client, {}, event="ping").json()["message"] == "pong"


def test_failed_run_creates_and_enqueues_job(client):
    r = post(client, failed_run_payload())
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    assert client.enqueued == [job_id]
    with session_scope() as s:
        job = s.get(Job, job_id)
        assert (job.repo, job.run_id, job.status) == ("me/demo", 111, "queued")


def test_duplicate_delivery_and_duplicate_run(client):
    assert post(client, failed_run_payload(), delivery="same").status_code == 202
    assert "duplicate delivery" in post(client, failed_run_payload(), delivery="same").json()["message"]
    # a different delivery for the same run (e.g. a redelivery from GitHub's UI) is still one job
    assert "already exists" in post(client, failed_run_payload(), delivery="other").json()["message"]
    assert len(client.enqueued) == 1


def test_queue_down_returns_503_and_keeps_the_job(db, settings):
    def broken_enqueue(job_id, _settings):
        raise ConnectionError("redis down")

    s = settings.model_copy(update={"github_webhook_secret": SECRET})
    c = TestClient(create_app(s, enqueue_fn=broken_enqueue))
    r = post(c, failed_run_payload())
    assert r.status_code == 503
    with session_scope() as session:
        assert session.query(Job).one().status == "queued"  # the recovery sweep will enqueue it


def test_skips_success_and_own_branches(client):
    assert "skipped" in post(client, failed_run_payload(conclusion="success"), delivery="a").json()["message"]
    assert "loop" in post(client, failed_run_payload(branch="redtogreen/run-1"), delivery="b").json()["message"]
    assert client.enqueued == []


def test_manual_job_needs_admin_token(client):
    body = {"repo": "me/demo", "run_id": 5, "head_sha": "abc", "head_branch": "main"}
    assert client.post("/api/jobs", json=body).status_code == 401
    r = client.post("/api/jobs", json=body, headers={"Authorization": "Bearer admin"})
    assert r.status_code == 202 and client.enqueued


def test_retry_finished_job(client):
    job_id = post(client, failed_run_payload()).json()["job_id"]
    auth = {"Authorization": "Bearer admin"}
    assert client.post(f"/api/jobs/{job_id}/retry", headers=auth).status_code == 409  # still queued
    with session_scope() as s:
        s.get(Job, job_id).status = "error"
    assert client.post(f"/api/jobs/{job_id}/retry").status_code == 401
    assert client.post(f"/api/jobs/{job_id}/retry", headers=auth).status_code == 202
    assert client.enqueued == [job_id, job_id]


def test_dashboard_and_job_pages(client):
    job_id = post(client, failed_run_payload()).json()["job_id"]
    assert job_id in client.get("/").text
    assert client.get(f"/jobs/{job_id}").status_code == 200
    assert client.get("/api/jobs").json()[0]["id"] == job_id
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "queued"
    assert client.get("/api/jobs/nope").status_code == 404
    assert "PRs opened" in client.get("/partials/jobs").text
