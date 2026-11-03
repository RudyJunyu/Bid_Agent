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
from bid_agent.services.requirement_llm_refine import llm_configured

router = APIRouter(prefix='/v1', tags=['requirements'])


class ExtractBody(BaseModel):
    job_id: str | None = Field(default=None, description='成功的解析任务 ID；缺省时使用该版本最近一次成功解析')
    use_llm: bool = Field(default=False, description='规则抽取后是否用 LLM 精抽补全／纠正')
    llm_vendor: str | None = Field(default='siliconflow', description='模型供应商；默认硅基流动')
    llm_model: str | None = Field(
        default='Qwen3-8B (轻量)',
        description='前端展示名或供应商模型 ID；默认 Qwen3-8B 轻量试验',
    )


@router.post('/document-versions/{version_id}/requirements/extract')
def extract_requirements(version_id: str, body: ExtractBody | None = None, user: Principal = Depends(current_user)):
    version = get_version(version_id, user, write=True)
    project_id = version['project_id']
    payload = body or ExtractBody()
    job_id = payload.job_id or _latest_succeeded_job(project_id, version_id, user)
    parsed = jobs.get_result(job_id, user)
    try:
        items, extractor_version = extract_and_store(
            project_id,
            version_id,
            job_id,
            parsed,
            user,
            use_llm=payload.use_llm,
            llm_vendor=payload.llm_vendor,
            llm_model=payload.llm_model,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        message = str(exc)
        if payload.use_llm and ('api' in message.lower() or 'key' in message.lower() or 'auth' in message.lower()):
            raise HTTPException(502, f'LLM 精抽失败：{message}') from exc
        raise
    counts = dict(Counter(item['category'] for item in items))
    return {
        'document_version_id': version_id,
        'job_id': job_id,
        'extractor_version': extractor_version,
        'use_llm': payload.use_llm,
        'llm_configured': llm_configured(),
        'counts': counts,
        'items': items,
    }


@router.get('/document-versions/{version_id}/requirements')
def list_requirements(
    version_id: str,
    category: str | None = Query(default=None),
    extractor_version: str | None = Query(
        default=None,
        description='缺省取该版本最近一次抽取器；传 all 返回全部；也可指定 b07-rule-v2／b07-hybrid-v1',
    ),
    user: Principal = Depends(current_user),
):
    get_version(version_id, user)
    if extractor_version == 'all':
        selected = None
    elif extractor_version in (None, '', 'current'):
        selected = requirement_repo.latest_extractor_version(version_id, user) or EXTRACTOR_VERSION
    else:
        selected = extractor_version
    items = requirement_repo.list_for_version(
        version_id, user, category=category, extractor_version=selected,
    )
    return {
        'document_version_id': version_id,
        'extractor_version': selected or 'all',
        'llm_configured': llm_configured(),
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
