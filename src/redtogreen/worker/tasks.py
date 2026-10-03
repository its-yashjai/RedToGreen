"""What a worker does with one job id."""

import asyncio
from datetime import timedelta

from sqlalchemy import select, update

from redtogreen.config import Settings, get_settings
from redtogreen.db.models import Attempt, Job, TraceStep, utcnow
from redtogreen.db.session import session_scope
from redtogreen.github.events import RunInfo
from redtogreen.github.fixer import fix_github_run
from redtogreen.pipeline import FixOutcome
from redtogreen.tracing import Step, Tracer
from redtogreen.worker.queue import enqueue_job


def claim(job_id: str) -> bool:
    """Atomically move a job from 'queued' to 'running'. Only one worker can win, so a job that
    was enqueued twice (or redelivered) is never processed twice."""
    with session_scope() as s:
        result = s.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "queued")
            .values(status="running", started_at=utcnow())
        )
        return result.rowcount == 1


def db_sink(job_id: str):
    def write(step: Step) -> None:
        with session_scope() as s:
            s.add(TraceStep(job_id=job_id, attempt=step.attempt, node=step.node, tool=step.tool,
                            detail=step.detail[:4000], input_tokens=step.input_tokens,
                            output_tokens=step.output_tokens, ms=step.ms, ok=step.ok))
    return write


def save_outcome(job_id: str, outcome: FixOutcome) -> None:
    with session_scope() as s:
        job = s.get(Job, job_id)
        job.status = outcome.status
        job.explanation = outcome.explanation
        job.diff = outcome.diff
        job.pr_url = outcome.pr_url
        job.error = outcome.error
        job.attempts_used = outcome.attempts
        job.input_tokens = outcome.input_tokens
        job.output_tokens = outcome.output_tokens
        job.cost_usd = outcome.cost_usd
        job.duration_s = outcome.duration_s
        job.finished_at = utcnow()
        for h in outcome.history:
            s.add(Attempt(job_id=job_id, number=h["attempt"], diff=h.get("diff", ""), passed=h.get("passed", False),
                          violations=h.get("violations", []), test_summary=h.get("test_summary", "")[-6000:],
                          explanation=h.get("explanation", "")))


def process_job(job_id: str) -> str:
    settings = get_settings()
    if not claim(job_id):
        return "skipped: not in 'queued' state"
    with session_scope() as s:
        job = s.get(Job, job_id)
        owner, _, repo = job.repo.partition("/")
        run = RunInfo(owner=owner, repo=repo, run_id=job.run_id, head_sha=job.head_sha,
                      head_branch=job.head_branch, pr_numbers=list(job.pr_numbers or []), html_url=job.run_url)
    tracer = Tracer(sink=db_sink(job_id))
    try:
        outcome = asyncio.run(fix_github_run(run, settings, job_id=job_id, tracer=tracer))
    except Exception as exc:  # record the failure; never leave a job stuck in 'running'
        outcome = FixOutcome(status="error", error=f"{type(exc).__name__}: {exc}"[:4000],
                             input_tokens=tracer.input_tokens, output_tokens=tracer.output_tokens)
    save_outcome(job_id, outcome)
    return outcome.status


def requeue_stale_jobs(settings: Settings | None = None) -> int:
    """Crash recovery. A job 'running' for too long means its worker died (crash, deploy, OOM).
    Give it one more try; if it dies again, mark it as an error instead of looping forever."""
    settings = settings or get_settings()
    cutoff = utcnow() - timedelta(minutes=settings.stale_job_minutes)
    requeued = []
    with session_scope() as s:
        stale = s.scalars(select(Job).where(Job.status == "running", Job.started_at < cutoff)).all()
        for job in stale:
            if job.requeues >= 1:
                job.status, job.error, job.finished_at = "error", "worker died twice on this job", utcnow()
            else:
                job.status, job.requeues = "queued", job.requeues + 1
                requeued.append(job.id)
    for job_id in requeued:
        enqueue_job(job_id, settings)
    return len(requeued)
