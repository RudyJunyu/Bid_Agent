"""Transactional job state and outbox. Redis delivery is at-least-once; commits are fenced."""
import hashlib
import json
import time
from datetime import datetime, timezone

from bid_agent.repositories.platform import ConflictError, NotFoundError, new_id, now, transaction
from bid_agent.repositories.workspace import check_access

TERMINAL = {'succeeded', 'failed', 'cancelled'}
LEASE_SECONDS = 60


def _event(conn, job_id: str, event_type: str, **payload) -> None:
    conn.execute('INSERT INTO job_events(job_id,event_type,payload_json,created_at) VALUES(?,?,?,?)',
                 (job_id, event_type, json.dumps(payload, ensure_ascii=False), now()))


def _enqueue(conn, job_id: str, available_at: float = 0) -> None:
    conn.execute('INSERT INTO outbox_events(id,job_id,available_at,created_at) VALUES(?,?,?,?)',
                 (new_id('evt'), job_id, available_at, now()))


def public_job(row) -> dict:
    result = dict(row)
    result['options'] = json.loads(result.pop('options_json'))
    for field in ('lease_token', 'lease_expires_at', 'request_hash'):
        result.pop(field, None)
    result['retryable'] = bool(result['retryable'])
    return result


def create_job(version_id: str, options: dict, idempotency_key: str, user) -> tuple[dict, bool]:
    canonical = json.dumps({'version_id': version_id, 'options': options}, sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    with transaction(immediate=True) as conn:
        version = conn.execute('''SELECT d.project_id FROM document_versions v JOIN documents d ON d.id=v.document_id
            WHERE v.id=?''', (version_id,)).fetchone()
        if not version:
            raise NotFoundError('文档版本不存在')
        project_id = version['project_id']
        check_access(conn, project_id, user, write=True)
        existing = conn.execute('SELECT * FROM jobs WHERE project_id=? AND idempotency_key=?',
                                (project_id, idempotency_key)).fetchone()
        if existing:
            if existing['request_hash'] != digest:
                raise ConflictError('幂等键已用于不同的解析参数或文档版本')
            return public_job(existing), False
        job_id, timestamp = new_id('job'), now()
        conn.execute('''INSERT INTO jobs(id,project_id,document_version_id,status,options_json,idempotency_key,
            request_hash,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)''',
            (job_id, project_id, version_id, 'queued', json.dumps(options), idempotency_key, digest, user.id, timestamp, timestamp))
        _event(conn, job_id, 'queued', status='queued', progress=0)
        # A database rollback also removes the message. Publish only after this transaction commits.
        _enqueue(conn, job_id)
        return public_job(conn.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()), True


def get_job(job_id: str, user, *, write=False) -> dict:
    with transaction() as conn:
        row = conn.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if not row:
            raise NotFoundError('任务不存在')
        check_access(conn, row['project_id'], user, write=write)
        return public_job(row)


def list_jobs(project_id: str, user, limit: int = 100) -> list[dict]:
    with transaction() as conn:
        check_access(conn, project_id, user)
        return [public_job(row) for row in conn.execute('SELECT * FROM jobs WHERE project_id=? ORDER BY created_at DESC LIMIT ?',
                                                       (project_id, limit))]


def events(job_id: str, user, after: int, limit: int = 200) -> list[dict]:
    get_job(job_id, user)
    with transaction() as conn:
        return [{**dict(row), 'payload': json.loads(row['payload_json'])} for row in conn.execute(
            'SELECT sequence,event_type,payload_json,created_at FROM job_events WHERE job_id=? AND sequence>? ORDER BY sequence LIMIT ?',
            (job_id, after, limit))]


def get_result(job_id: str, user) -> dict:
    job = get_job(job_id, user)
    if job['status'] != 'succeeded':
        raise ConflictError('任务尚未成功完成')
    with transaction() as conn:
        row = conn.execute('SELECT id,result_json,created_at FROM parsed_documents WHERE job_id=?', (job_id,)).fetchone()
        if not row:
            raise NotFoundError('解析结果不存在')
        return {'id': row['id'], 'created_at': row['created_at'], **json.loads(row['result_json'])}


def cancel_job(job_id: str, user) -> dict:
    with transaction(immediate=True) as conn:
        row = conn.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if not row:
            raise NotFoundError('任务不存在')
        check_access(conn, row['project_id'], user, write=True)
        if row['status'] in TERMINAL or row['status'] == 'cancelling':
            return public_job(row)
        status = 'cancelling' if row['status'] == 'running' else 'cancelled'
        conn.execute('UPDATE jobs SET status=?,stage=?,updated_at=? WHERE id=?', (status, status, now(), job_id))
        conn.execute("UPDATE outbox_events SET status='cancelled' WHERE job_id=? AND status IN ('pending','publishing')", (job_id,))
        _event(conn, job_id, status, status=status)
        return public_job(conn.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())


def retry_job(job_id: str, user) -> dict:
    with transaction(immediate=True) as conn:
        row = conn.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if not row:
            raise NotFoundError('任务不存在')
        check_access(conn, row['project_id'], user, write=True)
        if row['status'] not in {'failed', 'cancelled'}:
            raise ConflictError('只有失败或已取消的任务可以重试')
        conn.execute('''UPDATE jobs SET status='queued',stage='queued',progress=0,lease_token=NULL,lease_expires_at=NULL,
            available_at=0,max_attempts=attempts+3,error_code=NULL,error_message=NULL,retryable=0,updated_at=? WHERE id=?''', (now(), job_id))
        _enqueue(conn, job_id)
        _event(conn, job_id, 'retried', status='queued', previous_attempts=row['attempts'])
        return public_job(conn.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())


def claim_job(job_id: str) -> dict | None:
    with transaction(immediate=True) as conn:
        row = conn.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if not row or row['status'] not in {'queued', 'retry_wait'} or row['available_at'] > time.time():
            return None
        token = new_id('lease')
        conn.execute('''UPDATE jobs SET status='running',stage='starting',attempts=attempts+1,lease_token=?,
            lease_expires_at=?,updated_at=? WHERE id=?''', (token, time.time()+LEASE_SECONDS, now(), job_id))
        _event(conn, job_id, 'running', status='running', attempt=row['attempts']+1)
        return dict(conn.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())


def heartbeat(job_id: str, token: str) -> bool:
    with transaction(immediate=True) as conn:
        result = conn.execute('''UPDATE jobs SET lease_expires_at=? WHERE id=? AND lease_token=?
            AND status IN ('running','cancelling')''', (time.time()+LEASE_SECONDS, job_id, token))
        return result.rowcount == 1


def progress(job_id: str, token: str, percent: int, stage: str) -> None:
    with transaction(immediate=True) as conn:
        result = conn.execute('''UPDATE jobs SET progress=?,stage=?,updated_at=?
            WHERE id=? AND lease_token=? AND status='running' ''', (percent, stage, now(), job_id, token))
        if result.rowcount:
            _event(conn, job_id, 'progress', status='running', progress=percent, stage=stage)


def _cancel_if_requested(conn, job_id: str, token: str) -> bool:
    row = conn.execute('SELECT status,lease_token FROM jobs WHERE id=?', (job_id,)).fetchone()
    if not row or row['lease_token'] != token:
        return True
    if row['status'] == 'cancelling':
        conn.execute("UPDATE jobs SET status='cancelled',stage='cancelled',lease_token=NULL,lease_expires_at=NULL,updated_at=? WHERE id=?",
                     (now(), job_id))
        _event(conn, job_id, 'cancelled', status='cancelled')
        return True
    return row['status'] != 'running'


def complete(job_id: str, token: str, result: dict) -> bool:
    with transaction(immediate=True) as conn:
        if _cancel_if_requested(conn, job_id, token):
            return False
        row = conn.execute('SELECT document_version_id FROM jobs WHERE id=?', (job_id,)).fetchone()
        conn.execute('INSERT INTO parsed_documents VALUES(?,?,?,?,?,?)',
                     (new_id('parsed'), job_id, row['document_version_id'], result['parser_version'],
                      json.dumps(result, ensure_ascii=False), now()))
        conn.execute('''UPDATE jobs SET status='succeeded',stage='succeeded',progress=100,lease_token=NULL,
            lease_expires_at=NULL,error_code=NULL,error_message=NULL,retryable=0,updated_at=? WHERE id=?''', (now(), job_id))
        _event(conn, job_id, 'succeeded', status='succeeded', progress=100)
        return True


def fail(job_id: str, token: str, code: str, message: str, retryable: bool) -> None:
    with transaction(immediate=True) as conn:
        if _cancel_if_requested(conn, job_id, token):
            return
        row = conn.execute('SELECT attempts,max_attempts FROM jobs WHERE id=?', (job_id,)).fetchone()
        retry = retryable and row['attempts'] < row['max_attempts']
        status = 'retry_wait' if retry else 'failed'
        available_at = time.time() + min(120, 5 * 2**min(row['attempts'], 5)) if retry else 0
        conn.execute('''UPDATE jobs SET status=?,stage=?,error_code=?,error_message=?,retryable=?,
            available_at=?,lease_token=NULL,lease_expires_at=NULL,updated_at=? WHERE id=?''',
            (status, status, code, message[:1000], retryable, available_at, now(), job_id))
        _event(conn, job_id, status, status=status, error_code=code, message=message[:1000], retryable=retryable)
        if retry:
            _enqueue(conn, job_id, available_at)


def recover_stale_jobs() -> int:
    """Worker death and lost broker deliveries are recovered using database state."""
    recovered = 0
    with transaction(immediate=True) as conn:
        for row in conn.execute("SELECT * FROM jobs WHERE status IN ('running','cancelling') AND lease_expires_at<?", (time.time(),)).fetchall():
            if row['status'] == 'cancelling':
                state = 'cancelled'
            else:
                state = 'queued' if row['attempts'] < row['max_attempts'] else 'failed'
            conn.execute('''UPDATE jobs SET status=?,stage=?,lease_token=NULL,lease_expires_at=NULL,
                error_code='worker_lost',error_message='解析进程失去心跳',retryable=1,updated_at=? WHERE id=?''',
                (state, state, now(), row['id']))
            if state == 'queued':
                _enqueue(conn, row['id'])
            _event(conn, row['id'], 'recovered', status=state, reason='worker_lost')
            recovered += 1
        threshold = datetime.fromtimestamp(time.time()-120, timezone.utc).isoformat()
        rows = conn.execute('''SELECT j.id FROM jobs j WHERE j.status IN ('queued','retry_wait') AND j.available_at<=?
            AND j.updated_at<? AND NOT EXISTS(SELECT 1 FROM outbox_events o WHERE o.job_id=j.id AND o.status IN ('pending','publishing'))''',
            (time.time(), threshold)).fetchall()
        for row in rows:
            _enqueue(conn, row['id'])
            conn.execute('UPDATE jobs SET updated_at=? WHERE id=?', (now(), row['id']))
            _event(conn, row['id'], 'redispatched', status='queued', reason='delivery_not_claimed')
            recovered += 1
    return recovered


def claim_outbox() -> dict | None:
    with transaction(immediate=True) as conn:
        row = conn.execute('''SELECT o.* FROM outbox_events o JOIN jobs j ON j.id=o.job_id
            WHERE j.status IN ('queued','retry_wait') AND o.available_at<=?
            AND (o.status='pending' OR (o.status='publishing' AND o.lease_expires_at<?)) ORDER BY o.created_at LIMIT 1''',
            (time.time(), time.time())).fetchone()
        if not row:
            return None
        token = new_id('delivery')
        conn.execute("UPDATE outbox_events SET status='publishing',lease_token=?,lease_expires_at=?,attempts=attempts+1 WHERE id=?",
                     (token, time.time()+30, row['id']))
        return {**dict(row), 'lease_token': token}


def finish_delivery(event: dict, error: str | None = None) -> None:
    with transaction(immediate=True) as conn:
        if error:
            conn.execute('''UPDATE outbox_events SET status='pending',available_at=?,last_error=?,lease_token=NULL,
                lease_expires_at=NULL WHERE id=? AND lease_token=? AND status='publishing' ''',
                (time.time()+10, error[:500], event['id'], event['lease_token']))
        else:
            conn.execute('''UPDATE outbox_events SET status='published',published_at=?,last_error=NULL,
                lease_token=NULL,lease_expires_at=NULL WHERE id=? AND lease_token=? AND status='publishing' ''',
                (now(), event['id'], event['lease_token']))


def version_for_worker(version_id: str) -> dict:
    with transaction() as conn:
        row = conn.execute('SELECT * FROM document_versions WHERE id=?', (version_id,)).fetchone()
        if not row:
            raise NotFoundError('任务原件版本已不存在')
        return dict(row)
