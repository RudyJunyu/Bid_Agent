"""Project stage gate API."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from bid_agent.core.identity import Principal
from bid_agent.core.security import current_user
from bid_agent.repositories import stages

router = APIRouter(prefix='/v1', tags=['stages'])


class StageBody(BaseModel):
    status: Literal['passed', 'skipped', 'pending'] = 'passed'
    notes: str = Field(default='', max_length=2000)


@router.get('/projects/{project_id}/stages')
def get_stages(project_id: str, user: Principal = Depends(current_user)):
    return {'project_id': project_id, 'stages': stages.list_stages(project_id, user)}


@router.post('/projects/{project_id}/stages/{stage}')
def pass_stage(project_id: str, stage: str, body: StageBody | None = None, user: Principal = Depends(current_user)):
    payload = body or StageBody()
    try:
        item = stages.mark_stage(
            project_id, stage, user, status=payload.status, notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return item


@router.delete('/projects/{project_id}/stages/{stage}')
def reset_stage(project_id: str, stage: str, user: Principal = Depends(current_user)):
    try:
        item = stages.mark_stage(project_id, stage, user, status='pending', notes='')
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return item
