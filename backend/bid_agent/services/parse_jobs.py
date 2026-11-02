"""A parse attempt can be executed independently of HTTP and of the queue transport."""
import json
import os
import threading

from bid_agent.infrastructure.object_store import object_store
from bid_agent.repositories import jobs
from bid_agent.schemas.documents import ParseOptions
from bid_agent.services.document_parser import parse_version


def safe_error(exc: Exception) -> str:
    message = str(exc) or exc.__class__.__name__
    for key, secret in os.environ.items():
        if secret and len(secret) >= 6 and key.endswith(('_KEY', '_TOKEN', '_PASSWORD')):
            message = message.replace(secret, '[redacted]')
    return message[:1000]


def execute_parse_job(job_id: str) -> bool:
    job = jobs.claim_job(job_id)
    if not job:
        return False  # Duplicate delivery or cancelled/terminal job.
    token, stopped = job['lease_token'], threading.Event()

    def heartbeat():
        while not stopped.wait(15):
            try:
                if not jobs.heartbeat(job_id, token):
                    return
            except Exception:
                # A failed heartbeat must not bypass the final fencing check.
                return

    thread = threading.Thread(target=heartbeat, daemon=True, name=f'heartbeat-{job_id}')
    thread.start()
    try:
        version = jobs.version_for_worker(job['document_version_id'])
        path = object_store.path(version['object_key'])
        options = ParseOptions.model_validate(json.loads(job['options_json']))
        result = parse_version(version, path, options,
            progress=lambda percent, stage: jobs.progress(job_id, token, percent, stage))
        return jobs.complete(job_id, token, result.model_dump(mode='json'))
    except Exception as exc:
        message = safe_error(exc)
        lowered = message.lower()
        transient = isinstance(exc, (TimeoutError, ConnectionError)) or any(
            text in lowered for text in ('timed out', 'timeout', '429', '502', '503', '504', 'connection error'))
        jobs.fail(job_id, token, 'upstream_unavailable' if transient else 'parse_failed', message, transient)
        return False
    finally:
        stopped.set()
        thread.join(timeout=2)
