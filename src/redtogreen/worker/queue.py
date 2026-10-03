"""The job queue (Redis + RQ).

Why a queue: GitHub expects a webhook reply within ~10 seconds, but a fix takes minutes.
The API saves the job, puts its id on the queue and answers 202 at once. Workers pull ids
off the queue and do the slow work. More load? Start more workers.
"""

from redis import Redis
from rq import Queue

from redtogreen.config import Settings


def get_redis(settings: Settings) -> Redis:
    return Redis.from_url(settings.redis_url)


def get_queue(settings: Settings) -> Queue:
    return Queue(settings.queue_name, connection=get_redis(settings), default_timeout=settings.job_timeout_s)


def enqueue_job(job_id: str, settings: Settings) -> None:
    get_queue(settings).enqueue(
        "redtogreen.worker.tasks.process_job",
        job_id,
        job_id=f"fix-{job_id}",
        job_timeout=settings.job_timeout_s,  # hard stop for a stuck job
        result_ttl=86_400,
        failure_ttl=7 * 86_400,
    )
