"""Append-only audit log for review and gate actions."""
from __future__ import annotations

import json

from bid_agent.core.identity import Principal
from bid_agent.repositories.platform import new_id, now, transaction
from bid_agent.repositories.workspace import check_access


def record(
    *,
    actor: Principal,
    action: str,
    object_type: str,
    object_id: str,
    summary: str,
    project_id: str | None = None,
    detail: dict | None = None,
    conn=None,
) -> dict:
    payload = {
        'id': new_id('aud'),
        'project_id': project_id,
        'actor_id': actor.id,
        'action': action,
        'object_type': object_type,
        'object_id': object_id,
        'summary': summary,
        'detail_json': json.dumps(detail or {}, ensure_ascii=False),
        'created_at': now(),
    }
    if conn is not None:
        conn.execute(
            '''INSERT INTO audit_logs(
                id,project_id,actor_id,action,object_type,object_id,summary,detail_json,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)''',
            (
                payload['id'], payload['project_id'], payload['actor_id'], payload['action'],
                payload['object_type'], payload['object_id'], payload['summary'],
                payload['detail_json'], payload['created_at'],
            ),
        )
        return _public(payload)
    with transaction(immediate=True) as tx:
        if project_id:
            check_access(tx, project_id, actor, write=True)
        tx.execute(
            '''INSERT INTO audit_logs(
                id,project_id,actor_id,action,object_type,object_id,summary,detail_json,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)''',
            (
                payload['id'], payload['project_id'], payload['actor_id'], payload['action'],
                payload['object_type'], payload['object_id'], payload['summary'],
                payload['detail_json'], payload['created_at'],
            ),
        )
    return _public(payload)


def list_for_project(
    project_id: str,
    user: Principal,
    *,
    object_type: str | None = None,
    object_id: str | None = None,
    limit: int = 100,
) -> list[dict]:
    with transaction() as conn:
        check_access(conn, project_id, user)
        clauses = ['project_id=?']
        params: list[object] = [project_id]
        if object_type:
            clauses.append('object_type=?')
            params.append(object_type)
        if object_id:
            clauses.append('object_id=?')
            params.append(object_id)
        params.append(limit)
        rows = conn.execute(
            f'''SELECT * FROM audit_logs WHERE {' AND '.join(clauses)}
                ORDER BY created_at DESC LIMIT ?''',
            params,
        ).fetchall()
        return [_public(dict(row)) for row in rows]


def _public(row: dict) -> dict:
    item = dict(row)
    item['detail'] = json.loads(item.pop('detail_json') or '{}')
    return item
