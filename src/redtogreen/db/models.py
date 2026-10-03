"""Database tables. Postgres in production, SQLite in unit tests (same models).

jobs               one row per failed CI run we try to fix
attempts           one row per fix attempt (the diff and the test result)
trace_steps        every node / LLM call / tool call, with tokens and milliseconds
webhook_deliveries GitHub delivery ids we already processed (deduplication)
"""

from datetime import UTC, datetime

from sqlalchemy import JSON, BigInteger, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("repo", "run_id", name="uq_jobs_repo_run"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    repo: Mapped[str] = mapped_column(String(200), index=True)
    run_id: Mapped[int] = mapped_column(BigInteger)
    head_sha: Mapped[str] = mapped_column(String(64))
    head_branch: Mapped[str] = mapped_column(String(255))
    pr_numbers: Mapped[list] = mapped_column(JSON, default=list)
    run_url: Mapped[str] = mapped_column(String(500), default="")
    # queued -> running -> pr_opened | gave_up | not_reproducible | superseded | error
    status: Mapped[str] = mapped_column(String(32), index=True, default="queued")
    explanation: Mapped[str] = mapped_column(Text, default="")
    diff: Mapped[str] = mapped_column(Text, default="")
    pr_url: Mapped[str] = mapped_column(String(500), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    attempts_used: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    requeues: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    attempts: Mapped[list["Attempt"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="Attempt.number")
    steps: Mapped[list["TraceStep"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="TraceStep.id")


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    diff: Mapped[str] = mapped_column(Text, default="")
    passed: Mapped[bool] = mapped_column(default=False)
    violations: Mapped[list] = mapped_column(JSON, default=list)
    test_summary: Mapped[str] = mapped_column(Text, default="")
    explanation: Mapped[str] = mapped_column(Text, default="")

    job: Mapped[Job] = relationship(back_populates="attempts")


class TraceStep(Base):
    __tablename__ = "trace_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    node: Mapped[str] = mapped_column(String(50))
    tool: Mapped[str] = mapped_column(String(100), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job: Mapped[Job] = relationship(back_populates="steps")


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    delivery_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event: Mapped[str] = mapped_column(String(50))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
