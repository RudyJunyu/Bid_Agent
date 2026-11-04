"""Persisted compliance review runs, findings, decisions and approvals."""
from __future__ import annotations

import json

from bid_agent.core.identity import Principal
from bid_agent.repositories import audit
from bid_agent.repositories.platform import NotFoundError, new_id, now, transaction
from bid_agent.repositories.workspace import check_access

HIGH_RISK = {'high', 'critical'}
APPROVAL_STATUSES = {'pending', 'approved', 'rejected'}


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
                status,summary_json,created_by,created_at,approval_status,approval_notes)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
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
                'pending',
                '',
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
        audit.record(
            actor=user,
            action='review.run_created',
            object_type='compliance_run',
            object_id=run_id,
            summary=f'创建审查任务，发现 {len(findings)} 条',
            project_id=project_id,
            detail={'finding_count': len(findings), 'checker_version': checker_version},
            conn=conn,
        )
    return get_run(run_id, user)


def list_runs(project_id: str, user: Principal, *, limit: int = 20) -> list[dict]:
    with transaction() as conn:
        check_access(conn, project_id, user)
        rows = conn.execute(
            '''SELECT id,project_id,bid_version_id,document_version_id,checker_version,
                      status,summary_json,created_by,created_at,
                      approval_status,approved_by,approved_at,approval_notes
               FROM compliance_runs WHERE project_id=? ORDER BY created_at DESC LIMIT ?''',
            (project_id, limit),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item['summary'] = json.loads(item.pop('summary_json') or '{}')
            item['approval_status'] = item.get('approval_status') or 'pending'
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
        payload['approval_status'] = payload.get('approval_status') or 'pending'
        payload['findings'] = findings
        payload['open_high_risk'] = sum(
            1 for item in findings
            if item.get('decision_status') == 'open' and item.get('severity') in HIGH_RISK
        )
        return payload


def list_findings(
    project_id: str,
    user: Principal,
    *,
    decision_status: str | None = None,
    severity: str | None = None,
) -> list[dict]:
    with transaction() as conn:
        check_access(conn, project_id, user)
        clauses = ['project_id=?']
        params: list[object] = [project_id]
        if decision_status:
            clauses.append('decision_status=?')
            params.append(decision_status)
        if severity:
            clauses.append('severity=?')
            params.append(severity)
        rows = conn.execute(
            f'''SELECT * FROM compliance_findings WHERE {' AND '.join(clauses)}
                ORDER BY CASE severity
                  WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2
                  WHEN 'low' THEN 3 ELSE 4 END, created_at DESC LIMIT 500''',
            params,
        ).fetchall()
        return [_public_finding(row) for row in rows]


def count_open_high_risk(project_id: str, user: Principal) -> int:
    with transaction() as conn:
        check_access(conn, project_id, user)
        row = conn.execute(
            '''SELECT COUNT(*) AS cnt FROM compliance_findings
               WHERE project_id=? AND decision_status='open'
                 AND severity IN ('high','critical')''',
            (project_id,),
        ).fetchone()
        return int(row['cnt'] or 0)


def decide_finding(
    finding_id: str,
    user: Principal,
    *,
    decision_status: str,
    notes: str = '',
) -> dict:
    if decision_status not in {'open', 'accepted', 'waived', 'fixed'}:
        raise ValueError('decision_status 无效')
    notes = (notes or '').strip()
    timestamp = now()
    with transaction(immediate=True) as conn:
        row = conn.execute('SELECT * FROM compliance_findings WHERE id=?', (finding_id,)).fetchone()
        if not row:
            raise NotFoundError('审查发现不存在')
        check_access(conn, row['project_id'], user, write=True)
        severity = row['severity']
        if decision_status == 'waived' and not notes:
            raise ValueError('豁免必须填写理由')
        if severity in HIGH_RISK and decision_status in {'accepted', 'waived', 'fixed'} and not notes:
            raise ValueError('高风险／严重项处理必须填写备注，便于审计追溯')
        from_status = row['decision_status']
        conn.execute(
            '''UPDATE compliance_findings
               SET decision_status=?, decision_notes=?, decided_by=?, decided_at=?
               WHERE id=?''',
            (decision_status, notes, user.id, timestamp, finding_id),
        )
        conn.execute(
            '''INSERT INTO compliance_decision_events(
                id,finding_id,project_id,run_id,from_status,to_status,notes,actor_id,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)''',
            (
                new_id('rde'),
                finding_id,
                row['project_id'],
                row['run_id'],
                from_status,
                decision_status,
                notes,
                user.id,
                timestamp,
            ),
        )
        row_run = conn.execute(
            'SELECT approval_status FROM compliance_runs WHERE id=?', (row['run_id'],)
        ).fetchone()
        if row_run and (row_run['approval_status'] or 'pending') == 'approved':
            conn.execute(
                '''UPDATE compliance_runs
                   SET approval_status='pending', approved_by=NULL, approved_at=NULL,
                       approval_notes=?
                   WHERE id=?''',
                ('发现状态变更后需重新审批', row['run_id']),
            )
        audit.record(
            actor=user,
            action='review.finding_decided',
            object_type='compliance_finding',
            object_id=finding_id,
            summary=f'{from_status} → {decision_status}：{row["title"]}',
            project_id=row['project_id'],
            detail={
                'from_status': from_status,
                'to_status': decision_status,
                'severity': severity,
                'notes': notes,
                'run_id': row['run_id'],
            },
            conn=conn,
        )
        updated = conn.execute('SELECT * FROM compliance_findings WHERE id=?', (finding_id,)).fetchone()
        return _public_finding(updated)


def list_decision_events(finding_id: str, user: Principal) -> list[dict]:
    with transaction() as conn:
        row = conn.execute(
            'SELECT project_id FROM compliance_findings WHERE id=?', (finding_id,)
        ).fetchone()
        if not row:
            raise NotFoundError('审查发现不存在')
        check_access(conn, row['project_id'], user)
        events = conn.execute(
            '''SELECT * FROM compliance_decision_events
               WHERE finding_id=? ORDER BY created_at ASC''',
            (finding_id,),
        ).fetchall()
        return [dict(item) for item in events]


def approve_run(
    run_id: str,
    user: Principal,
    *,
    approval_status: str = 'approved',
    notes: str = '',
    force: bool = False,
) -> dict:
    if approval_status not in APPROVAL_STATUSES:
        raise ValueError('approval_status 无效')
    notes = (notes or '').strip()
    timestamp = now()
    with transaction(immediate=True) as conn:
        row = conn.execute('SELECT * FROM compliance_runs WHERE id=?', (run_id,)).fetchone()
        if not row:
            raise NotFoundError('审查任务不存在')
        check_access(conn, row['project_id'], user, write=True)
        open_high = conn.execute(
            '''SELECT COUNT(*) AS cnt FROM compliance_findings
               WHERE run_id=? AND decision_status='open' AND severity IN ('high','critical')''',
            (run_id,),
        ).fetchone()
        open_count = int(open_high['cnt'] or 0)
        if approval_status == 'approved' and open_count and not force:
            raise ValueError(f'仍有 {open_count} 条高风险／严重发现未处理，不能批准')
        if approval_status == 'approved' and open_count and force and not (user.is_admin or notes):
            raise ValueError('强制批准需管理员身份或填写备注')
        if approval_status == 'rejected' and not notes:
            raise ValueError('驳回审查任务必须填写备注')
        conn.execute(
            '''UPDATE compliance_runs
               SET approval_status=?, approved_by=?, approved_at=?, approval_notes=?
               WHERE id=?''',
            (approval_status, user.id, timestamp, notes, run_id),
        )
        audit.record(
            actor=user,
            action='review.run_approved' if approval_status == 'approved' else f'review.run_{approval_status}',
            object_type='compliance_run',
            object_id=run_id,
            summary=f'审查任务{approval_status}',
            project_id=row['project_id'],
            detail={'approval_status': approval_status, 'notes': notes, 'force': force, 'open_high_risk': open_count},
            conn=conn,
        )
    return get_run(run_id, user)


def review_readiness(project_id: str, user: Principal) -> dict:
    open_high = count_open_high_risk(project_id, user)
    with transaction() as conn:
        check_access(conn, project_id, user)
        latest = conn.execute(
            '''SELECT id,approval_status,created_at FROM compliance_runs
               WHERE project_id=? ORDER BY created_at DESC LIMIT 1''',
            (project_id,),
        ).fetchone()
    return {
        'project_id': project_id,
        'open_high_risk': open_high,
        'latest_run_id': latest['id'] if latest else None,
        'latest_approval_status': (latest['approval_status'] if latest else None) or 'pending',
        'check_gate_ready': open_high == 0,
    }


def _public_finding(row) -> dict:
    item = dict(row)
    item['evidence'] = json.loads(item.pop('evidence_json') or '[]')
    return item
