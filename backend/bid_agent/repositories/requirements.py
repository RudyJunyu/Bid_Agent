"""Persist B07 requirement drafts linked to immutable document versions."""
import json

from bid_agent.repositories.platform import NotFoundError, new_id, now, transaction
from bid_agent.repositories.workspace import check_access, get_version


def public_item(row) -> dict:
    item = dict(row)
    item['source_refs'] = json.loads(item.pop('source_refs_json') or '[]')
    return item


def replace_drafts(*, project_id: str, document_version_id: str, job_id: str | None,
                   items: list[dict], user, extractor_version: str) -> list[dict]:
    with transaction(immediate=True) as conn:
        check_access(conn, project_id, user, write=True)
        version = conn.execute(
            '''SELECT v.id FROM document_versions v
               JOIN documents d ON d.id=v.document_id
               WHERE v.id=? AND d.project_id=?''',
            (document_version_id, project_id),
        ).fetchone()
        if not version:
            raise NotFoundError('文档版本不存在')
        # Keep human-confirmed rows; refresh drafts from this extractor only.
        conn.execute(
            '''DELETE FROM requirement_items
               WHERE document_version_id=? AND extractor_version=? AND review_status='draft' ''',
            (document_version_id, extractor_version),
        )
        timestamp = now()
        saved = []
        for item in items:
            item_id = item.get('id') or new_id('req')
            conn.execute(
                '''INSERT INTO requirement_items(
                    id,project_id,document_version_id,job_id,category,field_key,title,raw_text,
                    normalized_value,confidence,review_status,source_refs_json,extractor_version,
                    created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (
                    item_id, project_id, document_version_id, job_id,
                    item['category'], item.get('field_key'), item['title'], item['raw_text'],
                    item.get('normalized_value'), float(item.get('confidence') or 0),
                    item.get('review_status') or 'draft',
                    json.dumps(item.get('source_refs') or [], ensure_ascii=False),
                    extractor_version, item.get('created_at') or timestamp,
                    item.get('updated_at') or timestamp,
                ),
            )
            saved.append(item_id)
        rows = conn.execute(
            f'''SELECT * FROM requirement_items WHERE id IN ({','.join('?' for _ in saved)})
                ORDER BY category, created_at''',
            saved,
        ).fetchall() if saved else []
        return [public_item(row) for row in rows]


def latest_extractor_version(document_version_id: str, user) -> str | None:
    version = get_version(document_version_id, user)
    with transaction() as conn:
        check_access(conn, version['project_id'], user)
        row = conn.execute(
            '''SELECT extractor_version FROM requirement_items
               WHERE document_version_id=?
               ORDER BY updated_at DESC, created_at DESC LIMIT 1''',
            (document_version_id,),
        ).fetchone()
        return row['extractor_version'] if row else None


def list_for_version(
    document_version_id: str,
    user,
    category: str | None = None,
    extractor_version: str | None = None,
) -> list[dict]:
    version = get_version(document_version_id, user)
    with transaction() as conn:
        check_access(conn, version['project_id'], user)
        clauses = ['document_version_id=?']
        params: list = [document_version_id]
        if category:
            clauses.append('category=?')
            params.append(category)
        if extractor_version:
            clauses.append('extractor_version=?')
            params.append(extractor_version)
        rows = conn.execute(
            f'''SELECT * FROM requirement_items WHERE {' AND '.join(clauses)}
                ORDER BY category, created_at''',
            params,
        ).fetchall()
        return [public_item(row) for row in rows]


def update_review(item_id: str, review_status: str, normalized_value: str | None, user) -> dict:
    with transaction(immediate=True) as conn:
        row = conn.execute('SELECT * FROM requirement_items WHERE id=?', (item_id,)).fetchone()
        if not row:
            raise NotFoundError('要求条目不存在')
        check_access(conn, row['project_id'], user, write=True)
        value = normalized_value if normalized_value is not None else row['normalized_value']
        conn.execute(
            '''UPDATE requirement_items
               SET review_status=?, normalized_value=?, updated_at=?
               WHERE id=?''',
            (review_status, value, now(), item_id),
        )
        return public_item(conn.execute('SELECT * FROM requirement_items WHERE id=?', (item_id,)).fetchone())
