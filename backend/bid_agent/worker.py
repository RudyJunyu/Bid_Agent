"""Celery worker: celery -A bid_agent.worker:app worker --concurrency=1."""
import os
from celery import Celery
from celery.signals import worker_process_init

from bid_agent.core import settings  # noqa: F401

app = Celery('bid_agent', broker=os.getenv('BID_REDIS_URL', 'redis://redis:6379/0'))
app.conf.update(
    task_default_queue='bid-parse',
    task_serializer='json', accept_content=['json'],
    task_ignore_result=True, task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_connection_timeout=5,
    broker_transport_options={'visibility_timeout': 2400, 'socket_connect_timeout': 5, 'socket_timeout': 5},
    task_soft_time_limit=1900, task_time_limit=2000,
)


@worker_process_init.connect
def initialize_worker(**kwargs):
    # The API runs migrations before Compose starts workers. No schema writers here.
    from bid_agent.core.settings import DB_PATH
    if not DB_PATH.exists():
        raise RuntimeError('Initialize the API database before starting workers')


@app.task(name='bid_agent.parse_document', ignore_result=True)
def parse_document(job_id: str):
    from bid_agent.services.parse_jobs import execute_parse_job
    return execute_parse_job(job_id)
