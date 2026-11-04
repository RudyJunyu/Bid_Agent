"""Bid outline versions and section drafts."""
from __future__ import annotations

import json

from bid_agent.core.identity import Principal
from bid_agent.repositories.platform import NotFoundError, new_id, now, transaction
from bid_agent.repositories.workspace import check_access


def create_bid_version(
    project_id: str,
    user: Principal,
    *,
    title: str,
    outline_markdown: str,
    outline_tree: dict | list,
    score_coverage: dict,
    document_version_id: str | None = None,
    sections: list[dict] | None = None,
) -> dict:
    bid_id = new_id('bid')
    timestamp = now()
    with transaction(immediate=True) as conn:
        check_access(conn, project_id, user, write=True)
        if document_version_id:
            row = conn.execute(
                '''SELECT dv.id FROM document_versions dv
                   JOIN documents d ON d.id=dv.document_id
                   WHERE dv.id=? AND d.project_id=?''',
                (document_version_id, project_id),
            ).fetchone()
            if not row:
                raise NotFoundError('文档版本不存在或不属于当前项目')
        conn.execute(
            '''INSERT INTO bid_versions(
                id,project_id,document_version_id,title,outline_markdown,
                outline_json,score_coverage_json,created_by,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)''',
            (
                bid_id,
                project_id,
                document_version_id,
                title,
                outline_markdown,
                json.dumps(outline_tree, ensure_ascii=False),
                json.dumps(score_coverage, ensure_ascii=False),
                user.id,
                timestamp,
            ),
        )
        for index, section in enumerate(sections or []):
            conn.execute(
                '''INSERT INTO bid_sections(
                    id,bid_version_id,section_key,title,level,sort_order,
                    body_markdown,updated_at,updated_by)
                   VALUES(?,?,?,?,?,?,?,?,?)''',
                (
                    new_id('sec'),
                    bid_id,
                    section.get('section_key') or f's{index + 1}',
                    section.get('title') or f'章节 {index + 1}',
                    int(section.get('level') or 1),
                    int(section.get('sort_order', index)),
                    section.get('body_markdown') or '',
                    timestamp if (section.get('body_markdown') or '').strip() else None,
                    user.id if (section.get('body_markdown') or '').strip() else None,
                ),
            )
    return get_bid_version(bid_id, user)


def list_bid_versions(project_id: str, user: Principal) -> list[dict]:
    with transaction() as conn:
        check_access(conn, project_id, user)
        rows = conn.execute(
            '''SELECT id,project_id,document_version_id,title,created_by,created_at,
                      score_coverage_json
               FROM bid_versions WHERE project_id=? ORDER BY created_at DESC''',
            (project_id,),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            coverage = json.loads(item.pop('score_coverage_json') or '{}')
            item['score_coverage'] = {
                'coverage_rate': coverage.get('coverage_rate'),
                'covered': coverage.get('covered'),
                'total': coverage.get('total'),
            }
            stats = conn.execute(
                '''SELECT COUNT(*) AS total,
                          SUM(CASE WHEN TRIM(COALESCE(body_markdown,''))!='' THEN 1 ELSE 0 END) AS filled
                   FROM bid_sections WHERE bid_version_id=?''',
                (item['id'],),
            ).fetchone()
            total = int(stats['total'] or 0)
            filled = int(stats['filled'] or 0)
            item['content_stats'] = {
                'total': total,
                'filled': filled,
                'empty': total - filled,
            }
            result.append(item)
        return result


def get_bid_version(bid_version_id: str, user: Principal) -> dict:
    with transaction() as conn:
        row = conn.execute(
            'SELECT * FROM bid_versions WHERE id=?', (bid_version_id,)
        ).fetchone()
        if not row:
            raise NotFoundError('标书版本不存在')
        check_access(conn, row['project_id'], user)
        sections = [
            dict(item)
            for item in conn.execute(
                '''SELECT id,section_key,title,level,sort_order,body_markdown,
                          updated_at,updated_by
                   FROM bid_sections WHERE bid_version_id=? ORDER BY sort_order,title''',
                (bid_version_id,),
            ).fetchall()
        ]
        payload = dict(row)
        payload['outline_tree'] = json.loads(payload.pop('outline_json') or '{}')
        payload['score_coverage'] = json.loads(payload.pop('score_coverage_json') or '{}')
        payload['sections'] = sections
        payload['content_stats'] = _content_stats(sections)
        return payload


def get_section(section_id: str, user: Principal) -> dict:
    with transaction() as conn:
        return _load_section(conn, section_id, user, write=False)


def update_section(
    section_id: str,
    user: Principal,
    *,
    body_markdown: str,
    title: str | None = None,
) -> dict:
    timestamp = now()
    with transaction(immediate=True) as conn:
        section = _load_section(conn, section_id, user, write=True)
        new_title = title if title is not None else section['title']
        if not str(new_title or '').strip():
            raise ValueError('章节标题不能为空')
        conn.execute(
            '''UPDATE bid_sections
               SET body_markdown=?, title=?, updated_at=?, updated_by=?
               WHERE id=?''',
            (body_markdown or '', str(new_title).strip(), timestamp, user.id, section_id),
        )
    return get_section(section_id, user)


def _load_section(
    conn,
    section_id: str,
    user: Principal,
    *,
    write: bool,
) -> dict:
    row = conn.execute(
        '''SELECT s.id,s.bid_version_id,s.section_key,s.title,s.level,s.sort_order,
                  s.body_markdown,s.updated_at,s.updated_by,b.project_id,b.title AS bid_title
           FROM bid_sections s
           JOIN bid_versions b ON b.id=s.bid_version_id
           WHERE s.id=?''',
        (section_id,),
    ).fetchone()
    if not row:
        raise NotFoundError('章节不存在')
    check_access(conn, row['project_id'], user, write=write)
    return dict(row)


def _content_stats(sections: list[dict]) -> dict:
    total = len(sections)
    filled = sum(1 for item in sections if str(item.get('body_markdown') or '').strip())
    return {'total': total, 'filled': filled, 'empty': total - filled}
