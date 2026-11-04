"""Requirement response matrix API (B13 draft)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from bid_agent.core.identity import Principal
from bid_agent.core.security import current_user
from bid_agent.services import response_matrix

router = APIRouter(prefix='/v1', tags=['responses'])


class ResponsePatchBody(BaseModel):
    response_status: str | None = None
    section_id: str | None = None
    clear_section: bool = False
    response_summary: str | None = Field(default=None, max_length=4000)
    missing_materials: list[str] | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=2000)
    is_mandatory: bool | None = None


@router.post('/bid-versions/{bid_version_id}/response-matrix/rebuild')
def rebuild_matrix(bid_version_id: str, user: Principal = Depends(current_user)):
    try:
        return response_matrix.rebuild_matrix(bid_version_id, user)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get('/bid-versions/{bid_version_id}/response-matrix')
def get_matrix(bid_version_id: str, user: Principal = Depends(current_user)):
    try:
        return response_matrix.get_matrix(bid_version_id, user)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get('/bid-versions/{bid_version_id}/missing-materials')
def missing_materials(bid_version_id: str, user: Principal = Depends(current_user)):
    payload = response_matrix.get_matrix(bid_version_id, user)
    return {
        'bid_version_id': bid_version_id,
        'summary': payload['summary'],
        'missing_materials': payload['missing_materials'],
    }


@router.patch('/requirement-responses/{response_id}')
def patch_response(
    response_id: str,
    body: ResponsePatchBody,
    user: Principal = Depends(current_user),
):
    try:
        return response_matrix.update_row(
            response_id,
            user,
            response_status=body.response_status,
            section_id=body.section_id,
            clear_section=body.clear_section,
            response_summary=body.response_summary,
            missing_materials=body.missing_materials,
            notes=body.notes,
            is_mandatory=body.is_mandatory,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
