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
                    id,bid_version_id,section_key,title,level,sort_order,body_markdown)
                   VALUES(?,?,?,?,?,?,?)''',
                (
                    new_id('sec'),
                    bid_id,
                    section.get('section_key') or f's{index + 1}',
                    section.get('title') or f'章节 {index + 1}',
                    int(section.get('level') or 1),
                    int(section.get('sort_order', index)),
                    section.get('body_markdown') or '',
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
                '''SELECT id,section_key,title,level,sort_order,body_markdown
                   FROM bid_sections WHERE bid_version_id=? ORDER BY sort_order,title''',
                (bid_version_id,),
            ).fetchall()
        ]
        payload = dict(row)
        payload['outline_tree'] = json.loads(payload.pop('outline_json') or '{}')
        payload['score_coverage'] = json.loads(payload.pop('score_coverage_json') or '{}')
        payload['sections'] = sections
        return payload
