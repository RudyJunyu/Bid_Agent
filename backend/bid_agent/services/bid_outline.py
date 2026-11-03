"""Build and persist scoring-aligned bid outlines from requirement items."""
from __future__ import annotations

from bid_agent.core.identity import Principal
from bid_agent.repositories import bids, requirements as requirement_repo, stages, workspace
from bid_agent.services.score_coverage import build_aligned_outline, scoring_matrix_from_requirements


def outline_from_requirements(
    project_id: str,
    user: Principal,
    *,
    document_version_id: str | None = None,
    save: bool = True,
    require_gate: bool = True,
) -> dict:
    with_workspace = workspace  # keep import used for access via list below
    projects = with_workspace.list_projects(user)
    project = next((item for item in projects if item['id'] == project_id), None)
    if not project:
        stages.ensure_project_exists(project_id, user)
        project_name = '未命名项目'
    else:
        project_name = project.get('project_name') or '未命名项目'

    if require_gate:
        stages.require_passed(project_id, 'requirements', user)

    version_id = document_version_id
    if not version_id:
        documents = workspace.list_documents(project_id, user)
        for document in documents:
            for version in document.get('versions') or []:
                version_id = version['id']
                break
            if version_id:
                break
    if not version_id:
        raise ValueError('项目尚无文档版本，无法从要求生成目录')

    extractor = requirement_repo.latest_extractor_version(version_id, user)
    items = requirement_repo.list_for_version(
        version_id, user, extractor_version=extractor,
    )
    confirmed_or_draft = [
        item for item in items
        if item.get('review_status') in {'confirmed', 'draft', 'conflict'}
    ]
    scoring_rows = scoring_matrix_from_requirements(confirmed_or_draft)
    built = build_aligned_outline(project_name=project_name, scoring_rows=scoring_rows)
    payload = {
        'project_id': project_id,
        'document_version_id': version_id,
        'title': f'{project_name} 目录',
        **built,
    }
    if save:
        saved = bids.create_bid_version(
            project_id,
            user,
            title=payload['title'],
            outline_markdown=built['outline_markdown'],
            outline_tree=built['outline_tree'],
            score_coverage=built['score_coverage'],
            document_version_id=version_id,
            sections=built['sections'],
        )
        payload['bid_version'] = saved
    return payload


def score_coverage_for_bid(bid_version_id: str, user: Principal) -> dict:
    bid = bids.get_bid_version(bid_version_id, user)
    return {
        'bid_version_id': bid_version_id,
        'score_coverage': bid.get('score_coverage') or {},
        'outline_markdown': bid.get('outline_markdown') or '',
    }
