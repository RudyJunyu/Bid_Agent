"""Enterprise assets, immutable attachment versions, and project links."""
from __future__ import annotations

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

BUSINESS_TZ = ZoneInfo('Asia/Shanghai')

from bid_agent.core.identity import Principal
from bid_agent.repositories.platform import NotFoundError, new_id, now, transaction
from bid_agent.repositories.workspace import check_access

CATEGORIES = {
    'qualification', 'personnel', 'financial', 'performance', 'case', 'template', 'other',
}
STATUSES = {'draft', 'pending_review', 'active', 'expired', 'disabled'}
USABLE_STATUSES = {'active'}


def create_asset(
    user: Principal,
    *,
    category: str,
    title: str,
    subject_name: str = '',
    certificate_no: str = '',
    issuer: str = '',
    issued_on: str | None = None,
    expires_on: str | None = None,
    status: str = 'draft',
    review_notes: str = '',
    tags: list[str] | None = None,
    metadata: dict | None = None,
    organization_key: str = 'default',
) -> dict:
    if category not in CATEGORIES:
        raise ValueError(f'不支持的资产类别：{category}')
    if status not in STATUSES:
        raise ValueError(f'不支持的资产状态：{status}')
    title = (title or '').strip()
    if not title:
        raise ValueError('资产标题不能为空')
    asset_id = new_id('ea')
    timestamp = now()
    status = _effective_status(status, expires_on)
    with transaction(immediate=True) as conn:
        conn.execute(
            '''INSERT INTO enterprise_assets(
                id,organization_key,category,title,subject_name,certificate_no,issuer,
                issued_on,expires_on,status,review_notes,tags_json,metadata_json,
                created_by,created_at,updated_by,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (
                asset_id, organization_key, category, title, subject_name or '',
                certificate_no or '', issuer or '', issued_on, expires_on, status,
                review_notes or '', json.dumps(tags or [], ensure_ascii=False),
                json.dumps(metadata or {}, ensure_ascii=False),
                user.id, timestamp, user.id, timestamp,
            ),
        )
    return get_asset(asset_id, user)


def update_asset(
    asset_id: str,
    user: Principal,
    *,
    title: str | None = None,
    subject_name: str | None = None,
    certificate_no: str | None = None,
    issuer: str | None = None,
    issued_on: str | None = None,
    expires_on: str | None = None,
    status: str | None = None,
    review_notes: str | None = None,
    tags: list[str] | None = None,
    metadata: dict | None = None,
    clear_expires_on: bool = False,
) -> dict:
    timestamp = now()
    with transaction(immediate=True) as conn:
        row = conn.execute('SELECT * FROM enterprise_assets WHERE id=?', (asset_id,)).fetchone()
        if not row:
            raise NotFoundError('企业资产不存在')
        next_status = status if status is not None else row['status']
        if next_status not in STATUSES:
            raise ValueError(f'不支持的资产状态：{next_status}')
        next_expires = None if clear_expires_on else (
            expires_on if expires_on is not None else row['expires_on']
        )
        next_status = _effective_status(next_status, next_expires)
        conn.execute(
            '''UPDATE enterprise_assets SET
                 title=?, subject_name=?, certificate_no=?, issuer=?,
                 issued_on=?, expires_on=?, status=?, review_notes=?,
                 tags_json=?, metadata_json=?, updated_by=?, updated_at=?
               WHERE id=?''',
            (
                (title if title is not None else row['title']).strip() or row['title'],
                subject_name if subject_name is not None else row['subject_name'],
                certificate_no if certificate_no is not None else row['certificate_no'],
                issuer if issuer is not None else row['issuer'],
                issued_on if issued_on is not None else row['issued_on'],
                next_expires,
                next_status,
                review_notes if review_notes is not None else row['review_notes'],
                json.dumps(tags, ensure_ascii=False) if tags is not None else row['tags_json'],
                json.dumps(metadata, ensure_ascii=False) if metadata is not None else row['metadata_json'],
                user.id,
                timestamp,
                asset_id,
            ),
        )
    return get_asset(asset_id, user)


def get_asset(asset_id: str, user: Principal) -> dict:
    with transaction(immediate=True) as conn:
        row = conn.execute('SELECT * FROM enterprise_assets WHERE id=?', (asset_id,)).fetchone()
        if not row:
            raise NotFoundError('企业资产不存在')
        _refresh_expired(conn, row)
        row = conn.execute('SELECT * FROM enterprise_assets WHERE id=?', (asset_id,)).fetchone()
        versions = [
            dict(item)
            for item in conn.execute(
                '''SELECT id,asset_id,version,file_name,media_type,sha256,size_bytes,
                          created_by,created_at,notes
                   FROM enterprise_asset_versions WHERE asset_id=? ORDER BY version DESC''',
                (asset_id,),
            ).fetchall()
        ]
        payload = _public_asset(row)
        payload['versions'] = versions
        payload['latest_version'] = versions[0] if versions else None
        payload['usable'] = _is_usable(payload)
        return payload


def list_assets(
    user: Principal,
    *,
    category: str | None = None,
    status: str | None = None,
    usable_only: bool = False,
    query: str | None = None,
    organization_key: str = 'default',
    limit: int = 200,
) -> list[dict]:
    with transaction(immediate=True) as conn:
        _refresh_all_expired(conn, organization_key)
        clauses = ['organization_key=?']
        params: list[object] = [organization_key]
        if category:
            clauses.append('category=?')
            params.append(category)
        if status:
            clauses.append('status=?')
            params.append(status)
        if query:
            like = f'%{query.strip()}%'
            clauses.append('(title LIKE ? OR subject_name LIKE ? OR certificate_no LIKE ? OR issuer LIKE ?)')
            params.extend([like, like, like, like])
        params.append(limit)
        rows = conn.execute(
            f'''SELECT * FROM enterprise_assets
                WHERE {' AND '.join(clauses)}
                ORDER BY updated_at DESC LIMIT ?''',
            params,
        ).fetchall()
        result = []
        for row in rows:
            item = _public_asset(row)
            latest = conn.execute(
                '''SELECT id,asset_id,version,file_name,media_type,sha256,size_bytes,
                          created_by,created_at,notes
                   FROM enterprise_asset_versions WHERE asset_id=?
                   ORDER BY version DESC LIMIT 1''',
                (item['id'],),
            ).fetchone()
            item['latest_version'] = dict(latest) if latest else None
            item['usable'] = _is_usable(item)
            if usable_only and not item['usable']:
                continue
            result.append(item)
        return result


def add_version(
    asset_id: str,
    user: Principal,
    *,
    stored: dict,
    notes: str = '',
) -> dict:
    timestamp = now()
    with transaction(immediate=True) as conn:
        row = conn.execute('SELECT id FROM enterprise_assets WHERE id=?', (asset_id,)).fetchone()
        if not row:
            raise NotFoundError('企业资产不存在')
        existing = conn.execute(
            'SELECT id FROM enterprise_asset_versions WHERE asset_id=? AND sha256=?',
            (asset_id, stored['sha256']),
        ).fetchone()
        if existing:
            version = conn.execute(
                'SELECT * FROM enterprise_asset_versions WHERE id=?', (existing['id'],)
            ).fetchone()
            return dict(version)
        current = conn.execute(
            'SELECT COALESCE(MAX(version),0) AS max_version FROM enterprise_asset_versions WHERE asset_id=?',
            (asset_id,),
        ).fetchone()
        version_no = int(current['max_version'] or 0) + 1
        version_id = new_id('eav')
        conn.execute(
            '''INSERT INTO enterprise_asset_versions(
                id,asset_id,version,file_name,media_type,object_key,sha256,size_bytes,
                created_by,created_at,notes)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
            (
                version_id, asset_id, version_no, stored['file_name'], stored['media_type'],
                stored['object_key'], stored['sha256'], stored['size_bytes'],
                user.id, timestamp, notes or '',
            ),
        )
        conn.execute(
            'UPDATE enterprise_assets SET updated_by=?, updated_at=? WHERE id=?',
            (user.id, timestamp, asset_id),
        )
        version = conn.execute(
            'SELECT * FROM enterprise_asset_versions WHERE id=?', (version_id,)
        ).fetchone()
        return dict(version)


def get_version(version_id: str, user: Principal) -> dict:
    with transaction() as conn:
        row = conn.execute(
            '''SELECT v.*, a.organization_key
               FROM enterprise_asset_versions v
               JOIN enterprise_assets a ON a.id=v.asset_id
               WHERE v.id=?''',
            (version_id,),
        ).fetchone()
        if not row:
            raise NotFoundError('资产附件版本不存在')
        return dict(row)


def link_to_project(project_id: str, asset_id: str, user: Principal) -> dict:
    timestamp = now()
    with transaction(immediate=True) as conn:
        check_access(conn, project_id, user, write=True)
        asset = conn.execute('SELECT id FROM enterprise_assets WHERE id=?', (asset_id,)).fetchone()
        if not asset:
            raise NotFoundError('企业资产不存在')
        conn.execute(
            '''INSERT INTO project_asset_links(project_id,asset_id,linked_by,linked_at)
               VALUES(?,?,?,?)
               ON CONFLICT(project_id,asset_id) DO UPDATE SET
                 linked_by=excluded.linked_by, linked_at=excluded.linked_at''',
            (project_id, asset_id, user.id, timestamp),
        )
    return {'project_id': project_id, 'asset_id': asset_id, 'linked': True}


def unlink_from_project(project_id: str, asset_id: str, user: Principal) -> dict:
    with transaction(immediate=True) as conn:
        check_access(conn, project_id, user, write=True)
        conn.execute(
            'DELETE FROM project_asset_links WHERE project_id=? AND asset_id=?',
            (project_id, asset_id),
        )
    return {'project_id': project_id, 'asset_id': asset_id, 'linked': False}


def list_for_project(
    project_id: str,
    user: Principal,
    *,
    usable_only: bool = False,
) -> list[dict]:
    with transaction(immediate=True) as conn:
        check_access(conn, project_id, user)
        _refresh_all_expired(conn, 'default')
        rows = conn.execute(
            '''SELECT a.*, l.linked_at, l.linked_by
               FROM project_asset_links l
               JOIN enterprise_assets a ON a.id=l.asset_id
               WHERE l.project_id=?
               ORDER BY l.linked_at DESC''',
            (project_id,),
        ).fetchall()
        result = []
        for row in rows:
            item = _public_asset(row)
            item['linked_at'] = row['linked_at']
            item['linked_by'] = row['linked_by']
            latest = conn.execute(
                '''SELECT id,asset_id,version,file_name,media_type,sha256,size_bytes,
                          created_by,created_at,notes
                   FROM enterprise_asset_versions WHERE asset_id=?
                   ORDER BY version DESC LIMIT 1''',
                (item['id'],),
            ).fetchone()
            item['latest_version'] = dict(latest) if latest else None
            item['usable'] = _is_usable(item)
            if usable_only and not item['usable']:
                continue
            result.append(item)
        return result


def _public_asset(row) -> dict:
    item = dict(row)
    item['tags'] = json.loads(item.pop('tags_json') or '[]')
    item['metadata'] = json.loads(item.pop('metadata_json') or '{}')
    item['expired'] = _is_past(item.get('expires_on'))
    return item


def _is_usable(asset: dict) -> bool:
    if asset.get('status') not in USABLE_STATUSES:
        return False
    if _is_past(asset.get('expires_on')):
        return False
    return True


def _effective_status(status: str, expires_on: str | None) -> str:
    if status == 'disabled':
        return status
    if _is_past(expires_on):
        return 'expired'
    if status == 'expired' and not _is_past(expires_on):
        return 'active'
    return status


def _business_today() -> date:
    return datetime.now(BUSINESS_TZ).date()


def _is_past(expires_on: str | None) -> bool:
    if not expires_on:
        return False
    try:
        day = date.fromisoformat(str(expires_on)[:10])
    except ValueError:
        return False
    # Certificate is usable through the expiry calendar day in Asia/Shanghai.
    return day < _business_today()


def _refresh_expired(conn, row) -> None:
    if row['status'] in {'disabled', 'draft', 'pending_review'}:
        return
    if _is_past(row['expires_on']) and row['status'] != 'expired':
        conn.execute(
            'UPDATE enterprise_assets SET status=?, updated_at=? WHERE id=?',
            ('expired', now(), row['id']),
        )


def _refresh_all_expired(conn, organization_key: str) -> None:
    today = _business_today().isoformat()
    conn.execute(
        '''UPDATE enterprise_assets
           SET status='expired', updated_at=?
           WHERE organization_key=? AND status='active'
             AND expires_on IS NOT NULL AND expires_on < ?''',
        (now(), organization_key, today),
    )
