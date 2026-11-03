"""Persisted compliance review runs and findings."""
from __future__ import annotations

import json

from bid_agent.core.identity import Principal
from bid_agent.repositories.platform import NotFoundError, new_id, now, transaction
from bid_agent.repositories.workspace import check_access


def create_run(
    project_id: str,
    user: Principal,
    *,
    checker_version: str,
    summary: dict,
    findings: list[dict],
    bid_version_id: str | None = None,
    document_version_id: str | None = None,
) -> dict:
    run_id = new_id('rr')
    timestamp = now()
    with transaction(immediate=True) as conn:
        check_access(conn, project_id, user, write=True)
        conn.execute(
            '''INSERT INTO compliance_runs(
                id,project_id,bid_version_id,document_version_id,checker_version,
                status,summary_json,created_by,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)''',
            (
                run_id,
                project_id,
                bid_version_id,
                document_version_id,
                checker_version,
                'completed',
                json.dumps(summary, ensure_ascii=False),
                user.id,
                timestamp,
            ),
        )
        for finding in findings:
            conn.execute(
                '''INSERT INTO compliance_findings(
                    id,run_id,project_id,check_name,severity,title,detail,
                    requirement_item_id,section_key,evidence_json,decision_status,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                (
                    new_id('rf'),
                    run_id,
                    project_id,
                    finding.get('check_name') or 'unknown',
                    finding.get('severity') or 'info',
                    finding.get('title') or '检查项',
                    finding.get('detail') or '',
                    finding.get('requirement_item_id'),
                    finding.get('section_key'),
                    json.dumps(finding.get('evidence') or [], ensure_ascii=False),
                    'open',
                    timestamp,
                ),
            )
    return get_run(run_id, user)


def list_runs(project_id: str, user: Principal, *, limit: int = 20) -> list[dict]:
    with transaction() as conn:
        check_access(conn, project_id, user)
        rows = conn.execute(
            '''SELECT id,project_id,bid_version_id,document_version_id,checker_version,
                      status,summary_json,created_by,created_at
               FROM compliance_runs WHERE project_id=? ORDER BY created_at DESC LIMIT ?''',
            (project_id, limit),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item['summary'] = json.loads(item.pop('summary_json') or '{}')
            result.append(item)
        return result


def get_run(run_id: str, user: Principal) -> dict:
    with transaction() as conn:
        row = conn.execute('SELECT * FROM compliance_runs WHERE id=?', (run_id,)).fetchone()
        if not row:
            raise NotFoundError('审查任务不存在')
        check_access(conn, row['project_id'], user)
        findings = [
            _public_finding(item)
            for item in conn.execute(
                '''SELECT * FROM compliance_findings WHERE run_id=?
                   ORDER BY CASE severity
                     WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2
                     WHEN 'low' THEN 3 ELSE 4 END, created_at''',
                (run_id,),
            ).fetchall()
        ]
        payload = dict(row)
        payload['summary'] = json.loads(payload.pop('summary_json') or '{}')
        payload['findings'] = findings
        return payload


def list_findings(project_id: str, user: Principal, *, decision_status: str | None = None) -> list[dict]:
    with transaction() as conn:
        check_access(conn, project_id, user)
        clauses = ['project_id=?']
        params: list[object] = [project_id]
        if decision_status:
            clauses.append('decision_status=?')
            params.append(decision_status)
        rows = conn.execute(
            f'''SELECT * FROM compliance_findings WHERE {' AND '.join(clauses)}
                ORDER BY created_at DESC LIMIT 500''',
            params,
        ).fetchall()
        return [_public_finding(row) for row in rows]


def decide_finding(
    finding_id: str,
    user: Principal,
    *,
    decision_status: str,
    notes: str = '',
) -> dict:
    if decision_status not in {'open', 'accepted', 'waived', 'fixed'}:
        raise ValueError('decision_status 无效')
    timestamp = now()
    with transaction(immediate=True) as conn:
        row = conn.execute('SELECT * FROM compliance_findings WHERE id=?', (finding_id,)).fetchone()
        if not row:
            raise NotFoundError('审查发现不存在')
        check_access(conn, row['project_id'], user, write=True)
        conn.execute(
            '''UPDATE compliance_findings
               SET decision_status=?, decision_notes=?, decided_by=?, decided_at=?
               WHERE id=?''',
            (decision_status, notes or '', user.id, timestamp, finding_id),
        )
        updated = conn.execute('SELECT * FROM compliance_findings WHERE id=?', (finding_id,)).fetchone()
        return _public_finding(updated)


def _public_finding(row) -> dict:
    item = dict(row)
    item['evidence'] = json.loads(item.pop('evidence_json') or '[]')
    return item
