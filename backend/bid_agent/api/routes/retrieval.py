"""Evidence search and retrieval evaluation API (B10 draft)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from bid_agent.core.identity import Principal
from bid_agent.core.security import current_user
from bid_agent.repositories import indexes
from bid_agent.services import evidence_search

router = APIRouter(prefix='/v1', tags=['retrieval'])


class RebuildBody(BaseModel):
    notes: str = Field(default='', max_length=2000)


class SearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=50)


class EvalCase(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    relevant_ids: list[str] = Field(default_factory=list, max_length=50)


class EvalBody(BaseModel):
    cases: list[EvalCase] = Field(min_length=1, max_length=200)
    k: int = Field(default=10, ge=1, le=50)


@router.post('/projects/{project_id}/indexes/rebuild')
def rebuild_index(
    project_id: str,
    body: RebuildBody | None = None,
    user: Principal = Depends(current_user),
):
    payload = body or RebuildBody()
    try:
        return evidence_search.rebuild_index(project_id, user, notes=payload.notes)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get('/projects/{project_id}/indexes')
def list_indexes(project_id: str, user: Principal = Depends(current_user)):
    return {'project_id': project_id, 'indexes': indexes.list_versions(project_id, user)}


@router.post('/projects/{project_id}/search')
def search_project(project_id: str, body: SearchBody, user: Principal = Depends(current_user)):
    try:
        return evidence_search.search(
            project_id, user, query=body.query, limit=body.limit,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post('/projects/{project_id}/retrieval-eval')
def retrieval_eval(project_id: str, body: EvalBody, user: Principal = Depends(current_user)):
    try:
        return evidence_search.evaluate_recall(
            project_id,
            user,
            cases=[item.model_dump() for item in body.cases],
            k=body.k,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
