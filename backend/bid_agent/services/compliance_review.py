"""Orchestrate compliance checks and persist review runs."""
from __future__ import annotations

import os

from bid_agent.compliance import CHECKER_VERSION, run_checks
from bid_agent.compliance.types import CheckContext
from bid_agent.core.identity import Principal
from bid_agent.core.model_config import resolve_llm_selection
from bid_agent.infrastructure.llm_client import LLM_Invoke
from bid_agent.repositories import bids, requirements as requirement_repo, reviews, stages


def create_review_run(
    project_id: str,
    user: Principal,
    *,
    bid_version_id: str | None = None,
    document_version_id: str | None = None,
    use_llm: bool = False,
) -> dict:
    stages.ensure_project_exists(project_id, user)
    bid = None
    sections: list[dict] = []
    outline_markdown = ''
    version_id = document_version_id
    if bid_version_id:
        bid = bids.get_bid_version(bid_version_id, user)
        if bid['project_id'] != project_id:
            raise ValueError('标书版本不属于当前项目')
        sections = bid.get('sections') or []
        outline_markdown = bid.get('outline_markdown') or ''
        version_id = version_id or bid.get('document_version_id')

    items: list[dict] = []
    if version_id:
        items = requirement_repo.list_for_version(version_id, user)

    bid_text = '\n'.join(
        f"{section.get('title') or ''}\n{section.get('body_markdown') or ''}"
        for section in sections
    )
    llm = None
    if use_llm:
        if not os.getenv('LLM_API_KEY'):
            raise ValueError('未配置 LLM_API_KEY，无法启用 LLM 辅助审查')
        model_id, base_url = resolve_llm_selection('siliconflow', 'Qwen3-8B (轻量)')
        llm = LLM_Invoke(
            model=model_id,
            api_key=os.getenv('LLM_API_KEY'),
            base_url=base_url or os.getenv('LLM_BASE_URL'),
        )

    ctx = CheckContext(
        project_id=project_id,
        requirements=items,
        bid_sections=sections,
        outline_markdown=outline_markdown,
        bid_text=bid_text,
        use_llm=use_llm,
        llm=llm,
    )
    findings, summary = run_checks(ctx)
    return reviews.create_run(
        project_id,
        user,
        checker_version=CHECKER_VERSION,
        summary=summary,
        findings=[item.as_dict() for item in findings],
        bid_version_id=bid_version_id,
        document_version_id=version_id,
    )
