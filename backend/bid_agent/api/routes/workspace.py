"""Versioned document workspace and durable parse task API."""
import asyncio
import json
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from bid_agent.core.identity import Principal
from bid_agent.core.security import current_user
from bid_agent.infrastructure.object_store import FileTooLarge, object_store
from bid_agent.repositories import jobs, workspace
from bid_agent.repositories.platform import ForbiddenError, NotFoundError, transaction
from bid_agent.schemas.documents import ParseOptions

router = APIRouter(prefix='/v1', tags=['document workspace'])


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class MemberCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    role: Literal['editor', 'viewer'] = 'viewer'


@router.get('/projects')
def projects(user: Principal = Depends(current_user)):
    return {'projects': workspace.list_projects(user)}


@router.post('/projects', status_code=201)
def create_project(body: ProjectCreate, user: Principal = Depends(current_user)):
    title = body.title.strip()
    if not title:
        raise HTTPException(422, '项目名称不能为空')
    return workspace.create_project(title, user)


@router.post('/projects/{project_id}/members')
def add_member(project_id: str, body: MemberCreate, user: Principal = Depends(current_user)):
    workspace.add_member(project_id, body.username, body.role, user)
    return {'added': True}


@router.get('/projects/{project_id}/documents')
def documents(project_id: str, user: Principal = Depends(current_user)):
    return {'documents': workspace.list_documents(project_id, user)}


@router.post('/projects/{project_id}/documents', status_code=201)
def upload(project_id: str, response: Response, file: UploadFile = File(...),
           document_id: str | None = Form(default=None), title: str = Form(default='', max_length=200),
           kind: Literal['tender', 'clarification', 'attachment'] = Form(default='tender'),
           parent_document_id: str | None = Form(default=None), user: Principal = Depends(current_user)):
    # Authenticate/authorize before writing any incoming bytes to durable storage.
    with transaction() as conn:
        workspace.check_access(conn, project_id, user, write=True)
    try:
        stored = object_store.put(file.file, file.filename or '')
    except FileTooLarge as exc:
        raise HTTPException(413, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    version, created = workspace.save_version(project_id, user, stored, document_id=document_id,
        title=title.strip(), kind=kind, parent_document_id=parent_document_id)
    version.pop('object_key', None)
    response.status_code = 201 if created else 200
    return {'version': version, 'created': created}


@router.get('/document-versions/{version_id}/download')
def download(version_id: str, user: Principal = Depends(current_user)):
    version = workspace.get_version(version_id, user)
    path = object_store.path(version['object_key'])
    if not path.is_file():
        raise NotFoundError('原件文件缺失，请从备份恢复')
    return FileResponse(path, filename=version['file_name'], media_type=version['media_type'],
                        headers={'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, no-store'})


@router.post('/document-versions/{version_id}/parse-jobs', status_code=202)
def parse_job(version_id: str, body: ParseOptions, response: Response, request: Request,
              idempotency_key: str = Header(min_length=1, max_length=128), user: Principal = Depends(current_user)):
    job, created = jobs.create_job(version_id, body.model_dump(), idempotency_key, user)
    response.headers['Location'] = f'{request.scope.get("root_path", "")}/v1/jobs/{job["id"]}'
    return {'job': job, 'created': created}


@router.get('/projects/{project_id}/jobs')
def project_jobs(project_id: str, limit: int = Query(default=100, ge=1, le=200), user: Principal = Depends(current_user)):
    return {'jobs': jobs.list_jobs(project_id, user, limit)}


@router.get('/jobs/{job_id}')
def job(job_id: str, user: Principal = Depends(current_user)):
    return jobs.get_job(job_id, user)


@router.get('/jobs/{job_id}/result')
def result(job_id: str, user: Principal = Depends(current_user)):
    return jobs.get_result(job_id, user)


@router.post('/jobs/{job_id}/cancel')
def cancel(job_id: str, user: Principal = Depends(current_user)):
    return jobs.cancel_job(job_id, user)


@router.post('/jobs/{job_id}/retry', status_code=202)
def retry(job_id: str, user: Principal = Depends(current_user)):
    return jobs.retry_job(job_id, user)


@router.get('/jobs/{job_id}/events')
def events(job_id: str, after: int = Query(default=0, ge=0), user: Principal = Depends(current_user)):
    return {'events': jobs.events(job_id, user, after)}


@router.get('/jobs/{job_id}/stream')
async def event_stream(job_id: str, request: Request, after: int = Query(default=0, ge=0),
                       last_event_id: str | None = Header(default=None), user: Principal = Depends(current_user)):
    jobs.get_job(job_id, user)
    try:
        cursor = max(after, int(last_event_id or 0))
    except ValueError as exc:
        raise HTTPException(422, 'Last-Event-ID 必须是事件序号') from exc

    async def generate():
        nonlocal cursor
        while not await request.is_disconnected():
            # Recheck session and membership during a long-lived connection.
            try:
                current_user(request)
                batch = jobs.events(job_id, user, cursor)
                state = jobs.get_job(job_id, user)['status']
            except (HTTPException, ForbiddenError, NotFoundError):
                yield 'event: access_expired\ndata: {}\n\n'
                break
            for event in batch:
                cursor = event['sequence']
                yield f'id: {cursor}\nevent: job\ndata: {json.dumps(event, ensure_ascii=False)}\n\n'
            if state in jobs.TERMINAL and len(batch) < 200:
                break
            yield ': heartbeat\n\n'
            await asyncio.sleep(1)
    return StreamingResponse(generate(), media_type='text/event-stream',
                              headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
