"""B07 draft API: extract and review structured requirements with evidence."""
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from bid_agent.core.identity import Principal
from bid_agent.core.security import current_user
from bid_agent.repositories import jobs, requirements as requirement_repo
from bid_agent.repositories.platform import NotFoundError
from bid_agent.repositories.workspace import get_version
from bid_agent.schemas.requirements import RequirementReviewBody
from bid_agent.services.requirement_extract import EXTRACTOR_VERSION, extract_and_store

router = APIRouter(prefix='/v1', tags=['requirements'])


class ExtractBody(BaseModel):
    job_id: str | None = Field(default=None, description='成功的解析任务 ID；缺省时使用该版本最近一次成功解析')


@router.post('/document-versions/{version_id}/requirements/extract')
def extract_requirements(version_id: str, body: ExtractBody | None = None, user: Principal = Depends(current_user)):
    version = get_version(version_id, user, write=True)
    project_id = version['project_id']
    job_id = (body.job_id if body else None) or _latest_succeeded_job(project_id, version_id, user)
    parsed = jobs.get_result(job_id, user)
    items = extract_and_store(project_id, version_id, job_id, parsed, user)
    counts = dict(Counter(item['category'] for item in items))
    return {
        'document_version_id': version_id,
        'job_id': job_id,
        'extractor_version': EXTRACTOR_VERSION,
        'counts': counts,
        'items': items,
    }


@router.get('/document-versions/{version_id}/requirements')
def list_requirements(
    version_id: str,
    category: str | None = Query(default=None),
    user: Principal = Depends(current_user),
):
    get_version(version_id, user)
    items = requirement_repo.list_for_version(version_id, user, category=category)
    return {
        'document_version_id': version_id,
        'extractor_version': EXTRACTOR_VERSION,
        'counts': dict(Counter(item['category'] for item in items)),
        'items': items,
    }


@router.post('/requirements/{item_id}/review')
def review_requirement(item_id: str, body: RequirementReviewBody, user: Principal = Depends(current_user)):
    return requirement_repo.update_review(item_id, body.review_status, body.normalized_value, user)


def _latest_succeeded_job(project_id: str, version_id: str, user) -> str:
    for job in jobs.list_jobs(project_id, user, limit=200):
        if job['document_version_id'] == version_id and job['status'] == 'succeeded':
            return job['id']
    raise NotFoundError('该版本尚没有成功的解析任务，请先完成解析')
