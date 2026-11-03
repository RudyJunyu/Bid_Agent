"""Bid outline versions and DOCX export."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from bid_agent.core.identity import Principal
from bid_agent.core.security import current_user
from bid_agent.infrastructure.object_store import object_store
from bid_agent.repositories import bids, exports
from bid_agent.services import bid_export, bid_outline

router = APIRouter(prefix='/v1', tags=['bids'])


class OutlineBody(BaseModel):
    document_version_id: str | None = None
    save: bool = True


class ExportBody(BaseModel):
    bid_version_id: str
    force_skip_gate: bool = False
    notes: str = Field(default='', max_length=2000)
    bidder_name: str = Field(default='', max_length=200)


@router.post('/projects/{project_id}/outline/from-requirements')
def outline_from_requirements(
    project_id: str,
    body: OutlineBody | None = None,
    user: Principal = Depends(current_user),
):
    payload = body or OutlineBody()
    try:
        return bid_outline.outline_from_requirements(
            project_id,
            user,
            document_version_id=payload.document_version_id,
            save=payload.save,
            require_gate=True,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get('/projects/{project_id}/bid-versions')
def list_versions(project_id: str, user: Principal = Depends(current_user)):
    return {'project_id': project_id, 'bid_versions': bids.list_bid_versions(project_id, user)}


@router.get('/bid-versions/{bid_version_id}')
def get_version(bid_version_id: str, user: Principal = Depends(current_user)):
    return bids.get_bid_version(bid_version_id, user)


@router.get('/bid-versions/{bid_version_id}/score-coverage')
def score_coverage(bid_version_id: str, user: Principal = Depends(current_user)):
    return bid_outline.score_coverage_for_bid(bid_version_id, user)


@router.post('/projects/{project_id}/export-jobs', status_code=201)
def create_export(project_id: str, body: ExportBody, user: Principal = Depends(current_user)):
    try:
        artifact = bid_export.export_docx(
            project_id,
            user,
            bid_version_id=body.bid_version_id,
            force_skip_gate=body.force_skip_gate,
            notes=body.notes,
            bidder_name=body.bidder_name,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {'artifact': artifact}


@router.get('/projects/{project_id}/exports')
def list_exports(project_id: str, user: Principal = Depends(current_user)):
    return {'project_id': project_id, 'exports': exports.list_artifacts(project_id, user)}


@router.get('/exports/{artifact_id}/download')
def download_export(artifact_id: str, user: Principal = Depends(current_user)):
    artifact = exports.get_artifact(artifact_id, user)
    path = object_store.path(artifact['object_key'])
    return FileResponse(
        path,
        filename=artifact['file_name'],
        media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    )
