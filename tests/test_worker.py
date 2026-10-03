from datetime import timedelta

from redtogreen.db.models import Job, TraceStep, utcnow
from redtogreen.db.session import session_scope
from redtogreen.pipeline import FixOutcome
from redtogreen.tracing import Step
from redtogreen.worker import tasks


def add_job(job_id="j1", status="queued", **kw):
    run_id = abs(hash(job_id)) % 10_000_000
    with session_scope() as s:
        s.add(Job(id=job_id, repo="me/demo", run_id=run_id, head_sha="abc", head_branch="main", pr_numbers=[3],
                  status=status, **kw))


def test_claim_is_atomic(db):
    add_job()
    assert tasks.claim("j1") is True
    assert tasks.claim("j1") is False  # a second worker (or a duplicate message) loses


def test_process_job_saves_outcome_and_trace(db, monkeypatch):
    add_job()

    async def fake_fix(run, settings, job_id="", llm=None, tracer=None):
        assert run.full_name == "me/demo" and run.pr_numbers == [3]
        tracer.record(Step(attempt=1, node="llm", input_tokens=100, output_tokens=20))
        return FixOutcome(status="pr_opened", pr_url="https://github.com/me/demo/pull/9", attempts=1,
                          explanation="Root cause: x", diff="+fix", input_tokens=100, output_tokens=20,
                          history=[{"attempt": 1, "diff": "+fix", "passed": True, "violations": []}])

    monkeypatch.setattr(tasks, "fix_github_run", fake_fix)
    assert tasks.process_job("j1") == "pr_opened"
    with session_scope() as s:
        job = s.get(Job, "j1")
        assert job.status == "pr_opened" and job.pr_url.endswith("/pull/9")
        assert len(job.attempts) == 1 and job.attempts[0].passed
        assert s.query(TraceStep).count() == 1
    assert tasks.process_job("j1").startswith("skipped")  # already processed


def test_crash_is_recorded_not_stuck(db, monkeypatch):
    add_job()

    async def boom(*args, **kwargs):
        raise RuntimeError("docker is down")

    monkeypatch.setattr(tasks, "fix_github_run", boom)
    assert tasks.process_job("j1") == "error"
    with session_scope() as s:
        assert "docker is down" in s.get(Job, "j1").error


def test_requeue_stale_jobs(db, settings, monkeypatch):
    old = utcnow() - timedelta(hours=2)
    add_job("fresh", status="running", started_at=utcnow())
    add_job("stale", status="running", started_at=old)
    add_job("twice", status="running", started_at=old, requeues=1)
    add_job("lost", status="queued", created_at=old)  # saved while Redis was down
    add_job("new", status="queued")
    enqueued = []
    monkeypatch.setattr(tasks, "enqueue_job", lambda job_id, s: enqueued.append(job_id))
    assert tasks.requeue_stale_jobs(settings) == 2
    assert sorted(enqueued) == ["lost", "stale"]
    with session_scope() as s:
        assert s.get(Job, "fresh").status == "running"
        assert s.get(Job, "stale").status == "queued"
        assert s.get(Job, "twice").status == "error"
