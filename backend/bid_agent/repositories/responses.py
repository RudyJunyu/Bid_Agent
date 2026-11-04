"""Requirement response matrix rows linked to bid versions."""
from __future__ import annotations

import json

from bid_agent.core.identity import Principal
from bid_agent.repositories.platform import NotFoundError, new_id, now, transaction
from bid_agent.repositories.workspace import check_access

RESPONSE_STATUSES = (
    'uncovered',
    'mapped',
    'drafted',
    'responded',
    'waived',
    'missing_material',
)
PRESERVED_STATUSES = {'responded', 'waived', 'missing_material'}


def public_row(row) -> dict:
    item = dict(row)
    item['is_mandatory'] = bool(item.get('is_mandatory'))
    item['missing_materials'] = json.loads(item.pop('missing_materials_json') or '[]')
    return item


def replace_matrix(
    *,
    project_id: str,
    bid_version_id: str,
    user: Principal,
    rows: list[dict],
) -> list[dict]:
    timestamp = now()
    with transaction(immediate=True) as conn:
        check_access(conn, project_id, user, write=True)
        bid = conn.execute(
            'SELECT id,project_id FROM bid_versions WHERE id=?',
            (bid_version_id,),
        ).fetchone()
        if not bid or bid['project_id'] != project_id:
            raise NotFoundError('标书版本不存在或不属于当前项目')

        existing = {
            row['requirement_item_id']: dict(row)
            for row in conn.execute(
                'SELECT * FROM requirement_responses WHERE bid_version_id=?',
                (bid_version_id,),
            ).fetchall()
        }
        keep_ids: set[str] = set()
        for item in rows:
            req_id = item['requirement_item_id']
            previous = existing.get(req_id)
            if previous and previous['response_status'] in PRESERVED_STATUSES:
                response_status = previous['response_status']
                response_summary = previous['response_summary'] or item.get('response_summary') or ''
                missing_materials = json.loads(previous['missing_materials_json'] or '[]')
                if item.get('missing_materials'):
                    # Merge newly inferred gaps without wiping human list.
                    merged = list(dict.fromkeys([*missing_materials, *item['missing_materials']]))
                    missing_materials = merged
                notes = previous['notes'] or item.get('notes') or ''
                section_id = previous['section_id'] or item.get('section_id')
                row_id = previous['id']
                created_by = previous['created_by']
                created_at = previous['created_at']
            else:
                response_status = item.get('response_status') or 'uncovered'
                response_summary = item.get('response_summary') or ''
                missing_materials = item.get('missing_materials') or []
                notes = item.get('notes') or ''
                section_id = item.get('section_id')
                row_id = (previous or {}).get('id') or new_id('rr')
                created_by = (previous or {}).get('created_by') or user.id
                created_at = (previous or {}).get('created_at') or timestamp

            if response_status not in RESPONSE_STATUSES:
                raise ValueError(f'非法响应状态：{response_status}')
            if section_id:
                section = conn.execute(
                    'SELECT id FROM bid_sections WHERE id=? AND bid_version_id=?',
                    (section_id, bid_version_id),
                ).fetchone()
                if not section:
                    raise ValueError('章节不属于当前标书版本')

            conn.execute(
                '''INSERT INTO requirement_responses(
                    id,project_id,bid_version_id,requirement_item_id,section_id,
                    response_status,is_mandatory,response_summary,missing_materials_json,
                    notes,created_by,created_at,updated_by,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(bid_version_id, requirement_item_id) DO UPDATE SET
                     section_id=excluded.section_id,
                     response_status=excluded.response_status,
                     is_mandatory=excluded.is_mandatory,
                     response_summary=excluded.response_summary,
                     missing_materials_json=excluded.missing_materials_json,
                     notes=excluded.notes,
                     updated_by=excluded.updated_by,
                     updated_at=excluded.updated_at''',
                (
                    row_id,
                    project_id,
                    bid_version_id,
                    req_id,
                    section_id,
                    response_status,
                    1 if item.get('is_mandatory') else 0,
                    response_summary,
                    json.dumps(missing_materials, ensure_ascii=False),
                    notes,
                    created_by,
                    created_at,
                    user.id,
                    timestamp,
                ),
            )
            keep_ids.add(req_id)

        stale = [req_id for req_id in existing if req_id not in keep_ids]
        for req_id in stale:
            conn.execute(
                '''DELETE FROM requirement_responses
                   WHERE bid_version_id=? AND requirement_item_id=?''',
                (bid_version_id, req_id),
            )
    return list_for_bid(bid_version_id, user)


def list_for_bid(bid_version_id: str, user: Principal) -> list[dict]:
    with transaction() as conn:
        bid = conn.execute(
            'SELECT project_id FROM bid_versions WHERE id=?',
            (bid_version_id,),
        ).fetchone()
        if not bid:
            raise NotFoundError('标书版本不存在')
        check_access(conn, bid['project_id'], user)
        rows = conn.execute(
            '''SELECT rr.*,
                      ri.category AS requirement_category,
                      ri.title AS requirement_title,
                      ri.raw_text AS requirement_raw_text,
                      ri.normalized_value AS requirement_value,
                      ri.review_status AS requirement_review_status,
                      ri.field_key AS requirement_field_key,
                      ri.source_refs_json AS requirement_source_refs_json,
                      bs.section_key AS section_key,
                      bs.title AS section_title,
                      bs.body_markdown AS section_body_markdown
               FROM requirement_responses rr
               JOIN requirement_items ri ON ri.id=rr.requirement_item_id
               LEFT JOIN bid_sections bs ON bs.id=rr.section_id
               WHERE rr.bid_version_id=?
               ORDER BY rr.is_mandatory DESC, ri.category, ri.created_at''',
            (bid_version_id,),
        ).fetchall()
        result = []
        for row in rows:
            item = public_row(row)
            item['requirement_source_refs'] = json.loads(
                item.pop('requirement_source_refs_json') or '[]'
            )
            body = item.pop('section_body_markdown', None)
            item['section_has_body'] = bool(str(body or '').strip())
            result.append(item)
        return result


def get_response(response_id: str, user: Principal) -> dict:
    with transaction() as conn:
        row = conn.execute(
            '''SELECT rr.*,
                      ri.category AS requirement_category,
                      ri.title AS requirement_title,
                      ri.raw_text AS requirement_raw_text,
                      ri.normalized_value AS requirement_value,
                      ri.review_status AS requirement_review_status,
                      ri.field_key AS requirement_field_key,
                      ri.source_refs_json AS requirement_source_refs_json,
                      bs.section_key AS section_key,
                      bs.title AS section_title,
                      bs.body_markdown AS section_body_markdown
               FROM requirement_responses rr
               JOIN requirement_items ri ON ri.id=rr.requirement_item_id
               LEFT JOIN bid_sections bs ON bs.id=rr.section_id
               WHERE rr.id=?''',
            (response_id,),
        ).fetchone()
        if not row:
            raise NotFoundError('响应矩阵条目不存在')
        check_access(conn, row['project_id'], user)
        item = public_row(row)
        item['requirement_source_refs'] = json.loads(
            item.pop('requirement_source_refs_json') or '[]'
        )
        body = item.pop('section_body_markdown', None)
        item['section_has_body'] = bool(str(body or '').strip())
        return item


def update_response(
    response_id: str,
    user: Principal,
    *,
    response_status: str | None = None,
    section_id: str | None = None,
    clear_section: bool = False,
    response_summary: str | None = None,
    missing_materials: list[str] | None = None,
    notes: str | None = None,
    is_mandatory: bool | None = None,
) -> dict:
    timestamp = now()
    with transaction(immediate=True) as conn:
        row = conn.execute(
            'SELECT * FROM requirement_responses WHERE id=?',
            (response_id,),
        ).fetchone()
        if not row:
            raise NotFoundError('响应矩阵条目不存在')
        check_access(conn, row['project_id'], user, write=True)

        status = response_status if response_status is not None else row['response_status']
        if status not in RESPONSE_STATUSES:
            raise ValueError(f'非法响应状态：{status}')

        next_section = row['section_id']
        if clear_section:
            next_section = None
        elif section_id is not None:
            section = conn.execute(
                'SELECT id FROM bid_sections WHERE id=? AND bid_version_id=?',
                (section_id, row['bid_version_id']),
            ).fetchone()
            if not section:
                raise ValueError('章节不属于当前标书版本')
            next_section = section_id

        materials = (
            json.dumps(missing_materials, ensure_ascii=False)
            if missing_materials is not None
            else row['missing_materials_json']
        )
        conn.execute(
            '''UPDATE requirement_responses SET
                 response_status=?,
                 section_id=?,
                 response_summary=?,
                 missing_materials_json=?,
                 notes=?,
                 is_mandatory=?,
                 updated_by=?,
                 updated_at=?
               WHERE id=?''',
            (
                status,
                next_section,
                row['response_summary'] if response_summary is None else response_summary,
                materials,
                row['notes'] if notes is None else notes,
                row['is_mandatory'] if is_mandatory is None else (1 if is_mandatory else 0),
                user.id,
                timestamp,
                response_id,
            ),
        )
    return get_response(response_id, user)
