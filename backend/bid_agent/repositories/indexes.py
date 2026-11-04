"""Retrieval index version records (B10 draft)."""
from __future__ import annotations

import json

from bid_agent.core.identity import Principal
from bid_agent.repositories.platform import NotFoundError, new_id, now, transaction
from bid_agent.repositories.workspace import check_access


def create_version(
    project_id: str,
    user: Principal,
    *,
    kind: str = 'keyword',
    corpus_stats: dict | None = None,
    notes: str = '',
    status: str = 'ready',
) -> dict:
    if kind not in {'keyword', 'hybrid'}:
        raise ValueError('kind 必须是 keyword／hybrid')
    if status not in {'building', 'ready', 'failed', 'retired'}:
        raise ValueError('status 无效')
    version_id = new_id('idx')
    timestamp = now()
    with transaction(immediate=True) as conn:
        check_access(conn, project_id, user, write=True)
        # Retire previous ready versions of the same kind.
        conn.execute(
            '''UPDATE index_versions SET status='retired'
               WHERE project_id=? AND kind=? AND status='ready' ''',
            (project_id, kind),
        )
        conn.execute(
            '''INSERT INTO index_versions(
                id,project_id,kind,status,corpus_stats_json,built_by,built_at,notes)
               VALUES(?,?,?,?,?,?,?,?)''',
            (
                version_id, project_id, kind, status,
                json.dumps(corpus_stats or {}, ensure_ascii=False),
                user.id, timestamp, notes or '',
            ),
        )
    return get_version(version_id, user)


def list_versions(project_id: str, user: Principal) -> list[dict]:
    with transaction() as conn:
        check_access(conn, project_id, user)
        rows = conn.execute(
            '''SELECT * FROM index_versions WHERE project_id=? ORDER BY built_at DESC''',
            (project_id,),
        ).fetchall()
        return [_public(row) for row in rows]


def latest_ready(project_id: str, user: Principal, *, kind: str = 'keyword') -> dict | None:
    with transaction() as conn:
        check_access(conn, project_id, user)
        row = conn.execute(
            '''SELECT * FROM index_versions
               WHERE project_id=? AND kind=? AND status='ready'
               ORDER BY built_at DESC LIMIT 1''',
            (project_id, kind),
        ).fetchone()
        return _public(row) if row else None


def get_version(version_id: str, user: Principal) -> dict:
    with transaction() as conn:
        row = conn.execute('SELECT * FROM index_versions WHERE id=?', (version_id,)).fetchone()
        if not row:
            raise NotFoundError('索引版本不存在')
        check_access(conn, row['project_id'], user)
        return _public(row)


def _public(row) -> dict:
    item = dict(row)
    item['corpus_stats'] = json.loads(item.pop('corpus_stats_json') or '{}')
    return item
