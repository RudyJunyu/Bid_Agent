"""Export artifact metadata."""
from __future__ import annotations

from bid_agent.core.identity import Principal
from bid_agent.repositories.platform import NotFoundError, new_id, now, transaction
from bid_agent.repositories.workspace import check_access


def create_artifact(
    project_id: str,
    user: Principal,
    *,
    bid_version_id: str,
    file_name: str,
    object_key: str,
    sha256: str,
    size_bytes: int,
    kind: str = 'docx',
    force_skip_gate: bool = False,
    notes: str = '',
) -> dict:
    artifact_id = new_id('exp')
    timestamp = now()
    with transaction(immediate=True) as conn:
        check_access(conn, project_id, user, write=True)
        bid = conn.execute(
            'SELECT id FROM bid_versions WHERE id=? AND project_id=?',
            (bid_version_id, project_id),
        ).fetchone()
        if not bid:
            raise NotFoundError('标书版本不存在')
        conn.execute(
            '''INSERT INTO export_artifacts(
                id,project_id,bid_version_id,kind,file_name,object_key,sha256,size_bytes,
                created_by,created_at,force_skip_gate,notes)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
            (
                artifact_id,
                project_id,
                bid_version_id,
                kind,
                file_name,
                object_key,
                sha256,
                size_bytes,
                user.id,
                timestamp,
                1 if force_skip_gate else 0,
                notes or '',
            ),
        )
    return get_artifact(artifact_id, user)


def list_artifacts(project_id: str, user: Principal) -> list[dict]:
    with transaction() as conn:
        check_access(conn, project_id, user)
        rows = conn.execute(
            '''SELECT id,project_id,bid_version_id,kind,file_name,sha256,size_bytes,
                      created_by,created_at,force_skip_gate,notes
               FROM export_artifacts WHERE project_id=? ORDER BY created_at DESC''',
            (project_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_artifact(artifact_id: str, user: Principal) -> dict:
    with transaction() as conn:
        row = conn.execute(
            'SELECT * FROM export_artifacts WHERE id=?', (artifact_id,)
        ).fetchone()
        if not row:
            raise NotFoundError('导出物不存在')
        check_access(conn, row['project_id'], user)
        return dict(row)
