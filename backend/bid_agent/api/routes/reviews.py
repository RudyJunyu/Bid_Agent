"""Compliance review runs and finding decisions."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from bid_agent.core.identity import Principal
from bid_agent.core.security import current_user
from bid_agent.repositories import reviews
from bid_agent.services.compliance_review import create_review_run

router = APIRouter(prefix='/v1', tags=['reviews'])


class ReviewBody(BaseModel):
    bid_version_id: str | None = None
    document_version_id: str | None = None
    use_llm: bool = False


class DecideBody(BaseModel):
    decision_status: Literal['open', 'accepted', 'waived', 'fixed']
    notes: str = Field(default='', max_length=2000)


@router.post('/projects/{project_id}/review-runs', status_code=201)
def start_review(project_id: str, body: ReviewBody | None = None, user: Principal = Depends(current_user)):
    payload = body or ReviewBody()
    try:
        return create_review_run(
            project_id,
            user,
            bid_version_id=payload.bid_version_id,
            document_version_id=payload.document_version_id,
            use_llm=payload.use_llm,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get('/projects/{project_id}/review-runs')
def list_runs(project_id: str, user: Principal = Depends(current_user)):
    return {'project_id': project_id, 'runs': reviews.list_runs(project_id, user)}


@router.get('/review-runs/{run_id}')
def get_run(run_id: str, user: Principal = Depends(current_user)):
    return reviews.get_run(run_id, user)


@router.get('/projects/{project_id}/review-findings')
def list_findings(
    project_id: str,
    decision_status: str | None = Query(default=None),
    user: Principal = Depends(current_user),
):
    return {
        'project_id': project_id,
        'findings': reviews.list_findings(project_id, user, decision_status=decision_status),
    }


@router.post('/review-findings/{finding_id}/decide')
def decide(finding_id: str, body: DecideBody, user: Principal = Depends(current_user)):
    try:
        return reviews.decide_finding(
            finding_id, user, decision_status=body.decision_status, notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
