"""Project stage gates (requirements → outline → generate → check → export)."""
from __future__ import annotations

from bid_agent.core.identity import Principal
from bid_agent.repositories.platform import now, transaction
from bid_agent.repositories.workspace import check_access

STAGES = (
    ('requirements', '要求确认'),
    ('outline', '目录确认'),
    ('generate', '章节生成'),
    ('check', '合规审查'),
    ('export', '成品导出'),
)
STAGE_KEYS = [key for key, _ in STAGES]
STAGE_LABELS = dict(STAGES)


def list_stages(project_id: str, user: Principal) -> list[dict]:
    with transaction() as conn:
        check_access(conn, project_id, user)
        rows = {
            row['stage']: dict(row)
            for row in conn.execute(
                'SELECT * FROM project_stages WHERE project_id=?', (project_id,)
            ).fetchall()
        }
    result = []
    for key, label in STAGES:
        row = rows.get(key)
        result.append({
            'stage': key,
            'label': label,
            'status': (row or {}).get('status') or 'pending',
            'reviewer_id': (row or {}).get('reviewer_id'),
            'notes': (row or {}).get('notes') or '',
            'updated_at': (row or {}).get('updated_at'),
            'passed': ((row or {}).get('status') in {'passed', 'skipped'}),
        })
    return result


def is_passed(project_id: str, stage: str, user: Principal | None = None) -> bool:
    if stage not in STAGE_KEYS:
        raise ValueError(f'未知阶段：{stage}')
    with transaction() as conn:
        if user is not None:
            check_access(conn, project_id, user)
        row = conn.execute(
            'SELECT status FROM project_stages WHERE project_id=? AND stage=?',
            (project_id, stage),
        ).fetchone()
    return bool(row and row['status'] in {'passed', 'skipped'})


def require_passed(project_id: str, stage: str, user: Principal) -> None:
    if not is_passed(project_id, stage, user):
        label = STAGE_LABELS.get(stage, stage)
        raise ValueError(f'阶段闸门未通过：{label}（{stage}）')


def mark_stage(
    project_id: str,
    stage: str,
    user: Principal,
    *,
    status: str = 'passed',
    notes: str = '',
) -> dict:
    if stage not in STAGE_KEYS:
        raise ValueError(f'未知阶段：{stage}')
    if status not in {'passed', 'skipped', 'pending'}:
        raise ValueError('status 必须是 passed／skipped／pending')
    timestamp = now()
    with transaction(immediate=True) as conn:
        check_access(conn, project_id, user, write=True)
        if status == 'pending':
            conn.execute(
                'DELETE FROM project_stages WHERE project_id=? AND stage=?',
                (project_id, stage),
            )
        else:
            conn.execute(
                '''INSERT INTO project_stages(project_id,stage,status,reviewer_id,notes,updated_at)
                   VALUES(?,?,?,?,?,?)
                   ON CONFLICT(project_id,stage) DO UPDATE SET
                     status=excluded.status,
                     reviewer_id=excluded.reviewer_id,
                     notes=excluded.notes,
                     updated_at=excluded.updated_at''',
                (project_id, stage, status, user.id, notes or '', timestamp),
            )
    return next(item for item in list_stages(project_id, user) if item['stage'] == stage)


def ensure_project_exists(project_id: str, user: Principal) -> None:
    with transaction() as conn:
        check_access(conn, project_id, user)
