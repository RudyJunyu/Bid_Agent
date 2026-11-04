"""Stage gate policies: high-risk review must close before check passes."""
from __future__ import annotations

from bid_agent.core.identity import Principal
from bid_agent.repositories import audit, reviews, stages


def mark_stage(
    project_id: str,
    stage: str,
    user: Principal,
    *,
    status: str = 'passed',
    notes: str = '',
    force_skip_high_risk: bool = False,
) -> dict:
    notes = (notes or '').strip()
    if stage == 'check' and status in {'passed', 'skipped'}:
        open_high = reviews.count_open_high_risk(project_id, user)
        if open_high:
            if not force_skip_high_risk:
                raise ValueError(
                    f'仍有 {open_high} 条高风险／严重审查发现未处理，不能通过合规审查闸门'
                )
            if not (user.is_admin or notes):
                raise ValueError('强制跳过高风险未闭环需管理员身份或填写备注')
    item = stages.mark_stage(
        project_id, stage, user, status=status, notes=notes,
    )
    audit.record(
        actor=user,
        action='stage.marked',
        object_type='project_stage',
        object_id=f'{project_id}:{stage}',
        summary=f'阶段 {stage} → {status}',
        project_id=project_id,
        detail={
            'stage': stage,
            'status': status,
            'notes': notes,
            'force_skip_high_risk': force_skip_high_risk,
        },
    )
    return item
