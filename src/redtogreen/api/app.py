"""HTTP server: GitHub webhook in, dashboard out.

POST /webhooks/github   GitHub calls this when a workflow run completes
POST /api/jobs          manual trigger (needs ADMIN_TOKEN)
GET  /api/jobs[/{id}]   JSON
GET  /                  dashboard (auto-refreshes with HTMX)
GET  /jobs/{id}         one job: attempts, diffs, full trace
GET  /health            liveness + database + Redis check
"""

import hmac
import json
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from redtogreen.config import Settings, get_settings
from redtogreen.db.models import Job, WebhookDelivery
from redtogreen.db.session import session_scope
from redtogreen.github.events import RunInfo, parse_workflow_run, verify_signature

HERE = Path(__file__).parent
templates = Jinja2Templates(directory=HERE / "templates")
FINISHED = ("pr_opened", "gave_up", "not_reproducible", "superseded", "error")


def get_session():
    with session_scope() as s:
        yield s


def enqueue(job_id: str, settings: Settings) -> None:
    from redtogreen.worker.queue import enqueue_job

    enqueue_job(job_id, settings)


def create_app(settings: Settings | None = None, enqueue_fn=enqueue) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="RedToGreen", version="0.1.0")
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    def new_job(session: Session, run: RunInfo) -> Job | None:
        job = Job(id=uuid.uuid4().hex[:12], repo=run.full_name, run_id=run.run_id, head_sha=run.head_sha,
                  head_branch=run.head_branch, pr_numbers=run.pr_numbers, run_url=run.html_url, status="queued")
        session.add(job)
        try:
            session.commit()  # unique (repo, run_id): the same run never becomes two jobs
        except IntegrityError:
            session.rollback()
            return None
        enqueue_fn(job.id, settings)
        return job

    # ------------------------------------------------------------------ webhook
    @app.post("/webhooks/github")
    async def github_webhook(
        request: Request,
        session: Session = Depends(get_session),
        x_github_event: str = Header(""),
        x_github_delivery: str = Header(""),
        x_hub_signature_256: str | None = Header(None),
    ):
        body = await request.body()
        if not verify_signature(settings.github_webhook_secret, body, x_hub_signature_256):
            raise HTTPException(401, "invalid signature")
        if x_github_event == "ping":
            return {"ok": True, "message": "pong"}

        # GitHub may deliver the same event more than once; each delivery id is processed once.
        if x_github_delivery:
            session.add(WebhookDelivery(delivery_id=x_github_delivery, event=x_github_event))
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                return {"ok": True, "message": "duplicate delivery ignored"}

        run, reason = parse_workflow_run(x_github_event, json.loads(body or b"{}"), settings)
        if run is None:
            return {"ok": True, "message": f"skipped: {reason}"}
        job = new_job(session, run)
        if job is None:
            return {"ok": True, "message": "a job for this run already exists"}
        return JSONResponse({"ok": True, "job_id": job.id}, status_code=202)

    # ------------------------------------------------------------------ JSON API
    class ManualJob(BaseModel):
        repo: str  # owner/name
        run_id: int
        head_sha: str
        head_branch: str
        pr_numbers: list[int] = []

    def require_admin(authorization: str = Header("")):
        expected = f"Bearer {settings.admin_token}"
        if not settings.admin_token or not hmac.compare_digest(authorization, expected):
            raise HTTPException(401, "admin token required")

    @app.post("/api/jobs", status_code=202, dependencies=[Depends(require_admin)])
    def create_job(body: ManualJob, session: Session = Depends(get_session)):
        owner, _, repo = body.repo.partition("/")
        job = new_job(session, RunInfo(owner, repo, body.run_id, body.head_sha, body.head_branch, body.pr_numbers))
        if job is None:
            raise HTTPException(409, "a job for this run already exists")
        return {"job_id": job.id}

    @app.get("/api/jobs")
    def list_jobs(session: Session = Depends(get_session), limit: int = 50):
        jobs = session.scalars(select(Job).order_by(Job.created_at.desc()).limit(min(limit, 200))).all()
        return [job_json(j) for j in jobs]

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str, session: Session = Depends(get_session)):
        job = load_job(session, job_id)
        data = job_json(job)
        data["attempts"] = [{"number": a.number, "passed": a.passed, "violations": a.violations, "diff": a.diff}
                            for a in job.attempts]
        data["trace"] = [{"attempt": s.attempt, "node": s.node, "tool": s.tool, "ms": s.ms, "ok": s.ok,
                          "tokens": s.input_tokens + s.output_tokens, "detail": s.detail} for s in job.steps]
        return data

    # ------------------------------------------------------------------ dashboard
    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request, session: Session = Depends(get_session)):
        return templates.TemplateResponse(request, "index.html", {"stats": stats(session), **jobs_ctx(session)})

    @app.get("/partials/jobs", response_class=HTMLResponse)
    def jobs_partial(request: Request, session: Session = Depends(get_session)):
        return templates.TemplateResponse(request, "_jobs.html", {"stats": stats(session), **jobs_ctx(session)})

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    def job_page(request: Request, job_id: str, session: Session = Depends(get_session)):
        return templates.TemplateResponse(request, "job.html", {"job": load_job(session, job_id)})

    # ------------------------------------------------------------------ health
    @app.get("/health")
    def health():
        checks = {"db": False, "redis": False}
        try:
            with session_scope() as s:
                s.execute(text("SELECT 1"))
            checks["db"] = True
        except Exception:
            pass
        try:
            from redtogreen.worker.queue import get_redis

            checks["redis"] = bool(get_redis(settings).ping())
        except Exception:
            pass
        ok = all(checks.values())
        return JSONResponse({"status": "ok" if ok else "degraded", **checks}, status_code=200 if ok else 503)

    return app


def load_job(session: Session, job_id: str) -> Job:
    job = session.scalars(
        select(Job).where(Job.id == job_id).options(selectinload(Job.attempts), selectinload(Job.steps))
    ).first()
    if job is None:
        raise HTTPException(404, "job not found")
    return job


def job_json(j: Job) -> dict:
    return {
        "id": j.id, "repo": j.repo, "run_id": j.run_id, "head_sha": j.head_sha, "head_branch": j.head_branch,
        "status": j.status, "pr_url": j.pr_url, "explanation": j.explanation, "error": j.error,
        "attempts_used": j.attempts_used, "tokens": j.input_tokens + j.output_tokens,
        "cost_usd": round(j.cost_usd, 5), "duration_s": round(j.duration_s, 1),
        "created_at": j.created_at.isoformat() if j.created_at else None,
    }


def jobs_ctx(session: Session) -> dict:
    return {"jobs": session.scalars(select(Job).order_by(Job.created_at.desc()).limit(50)).all()}


def stats(session: Session) -> dict:
    rows = dict(session.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    finished = sum(v for k, v in rows.items() if k in FINISHED)
    fixed = rows.get("pr_opened", 0)
    avg_cost = session.scalar(select(func.avg(Job.cost_usd)).where(Job.status.in_(FINISHED))) or 0.0
    avg_time = session.scalar(select(func.avg(Job.duration_s)).where(Job.status == "pr_opened")) or 0.0
    return {
        "total": sum(rows.values()),
        "active": rows.get("queued", 0) + rows.get("running", 0),
        "fixed": fixed,
        "fix_rate": f"{fixed / finished:.0%}" if finished else "–",
        "avg_cost": f"${avg_cost:.4f}",
        "avg_time": f"{avg_time:.0f}s" if avg_time else "–",
    }


def factory() -> FastAPI:
    """Used by uvicorn: `uvicorn redtogreen.api.app:factory --factory`."""
    return create_app()
