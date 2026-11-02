"""Recover stale jobs and publish the transactional outbox to Redis/Celery."""
import logging
import signal
import threading
import tempfile
from pathlib import Path

from bid_agent.repositories import jobs

logger = logging.getLogger(__name__)


def dispatch_once(publish=None) -> bool:
    if publish is None:
        from bid_agent.worker import parse_document
        publish = lambda job_id: parse_document.apply_async(args=[job_id], retry=False)
    event = jobs.claim_outbox()
    if not event:
        return False
    try:
        publish(event['job_id'])
    except Exception as exc:
        jobs.finish_delivery(event, error=exc.__class__.__name__)
        logger.warning('Outbox delivery failed for %s: %s', event['job_id'], exc.__class__.__name__)
    else:
        jobs.finish_delivery(event)
    return True


def main():
    logging.basicConfig(level=logging.INFO)
    stopped = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopped.set())
    while not stopped.is_set():
        try:
            (Path(tempfile.gettempdir()) / 'dispatcher-heartbeat').touch()
            jobs.recover_stale_jobs()
            if dispatch_once():
                continue
        except Exception:
            logger.exception('Dispatcher iteration failed')
        stopped.wait(1)


if __name__ == '__main__':
    main()
