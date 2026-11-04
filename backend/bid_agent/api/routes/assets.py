"""Enterprise assets API (B09 draft)."""
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from bid_agent.core.identity import Principal
from bid_agent.core.security import current_user
from bid_agent.infrastructure.object_store import FileTooLarge, object_store
from bid_agent.repositories import assets
from bid_agent.repositories.platform import NotFoundError
from bid_agent.services import enterprise_assets

router = APIRouter(prefix='/v1', tags=['enterprise-assets'])

Category = Literal[
    'qualification', 'personnel', 'financial', 'performance', 'case', 'template', 'other',
]
Status = Literal['draft', 'pending_review', 'active', 'expired', 'disabled']


class AssetCreateBody(BaseModel):
    category: Category
    title: str = Field(min_length=1, max_length=300)
    subject_name: str = Field(default='', max_length=200)
    certificate_no: str = Field(default='', max_length=200)
    issuer: str = Field(default='', max_length=200)
    issued_on: str | None = Field(default=None, max_length=32)
    expires_on: str | None = Field(default=None, max_length=32)
    status: Status = 'draft'
    review_notes: str = Field(default='', max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=40)
    metadata: dict = Field(default_factory=dict)


class AssetPatchBody(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    subject_name: str | None = Field(default=None, max_length=200)
    certificate_no: str | None = Field(default=None, max_length=200)
    issuer: str | None = Field(default=None, max_length=200)
    issued_on: str | None = Field(default=None, max_length=32)
    expires_on: str | None = Field(default=None, max_length=32)
    clear_expires_on: bool = False
    status: Status | None = None
    review_notes: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = Field(default=None, max_length=40)
    metadata: dict | None = None


@router.get('/enterprise-assets')
def list_assets(
    category: str | None = Query(default=None),
    status: str | None = Query(default=None),
    usable_only: bool = Query(default=False),
    q: str | None = Query(default=None),
    user: Principal = Depends(current_user),
):
    return {
        'assets': assets.list_assets(
            user,
            category=category,
            status=status,
            usable_only=usable_only,
            query=q,
        ),
    }


@router.post('/enterprise-assets', status_code=201)
def create_asset(body: AssetCreateBody, user: Principal = Depends(current_user)):
    try:
        return enterprise_assets.create_asset(user, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get('/enterprise-assets/{asset_id}')
def get_asset(asset_id: str, user: Principal = Depends(current_user)):
    return assets.get_asset(asset_id, user)


@router.patch('/enterprise-assets/{asset_id}')
def patch_asset(asset_id: str, body: AssetPatchBody, user: Principal = Depends(current_user)):
    try:
        return enterprise_assets.update_asset(asset_id, user, **body.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post('/enterprise-assets/{asset_id}/versions', status_code=201)
def upload_version(
    asset_id: str,
    file: UploadFile = File(...),
    notes: str = Form(default='', max_length=2000),
    user: Principal = Depends(current_user),
):
    try:
        return enterprise_assets.upload_version(
            asset_id, user, file_obj=file.file, filename=file.filename or '', notes=notes,
        )
    except FileTooLarge as exc:
        raise HTTPException(413, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get('/enterprise-asset-versions/{version_id}/download')
def download_version(version_id: str, user: Principal = Depends(current_user)):
    version = assets.get_version(version_id, user)
    path = object_store.path(version['object_key'])
    if not path.is_file():
        raise NotFoundError('资产附件文件缺失，请从备份恢复')
    return FileResponse(
        path,
        filename=version['file_name'],
        media_type=version['media_type'],
        headers={'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, no-store'},
    )


@router.get('/projects/{project_id}/assets')
def project_assets(
    project_id: str,
    usable_only: bool = Query(default=False),
    user: Principal = Depends(current_user),
):
    return {
        'project_id': project_id,
        'assets': assets.list_for_project(project_id, user, usable_only=usable_only),
        'expired': enterprise_assets.expired_linked_assets(project_id, user),
    }


@router.post('/projects/{project_id}/assets/{asset_id}/link')
def link_asset(project_id: str, asset_id: str, user: Principal = Depends(current_user)):
    try:
        return enterprise_assets.link_asset(project_id, asset_id, user)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete('/projects/{project_id}/assets/{asset_id}')
def unlink_asset(project_id: str, asset_id: str, user: Principal = Depends(current_user)):
    return enterprise_assets.unlink_asset(project_id, asset_id, user)
