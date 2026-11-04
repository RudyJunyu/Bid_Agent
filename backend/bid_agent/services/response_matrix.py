"""Build and maintain requirement → section response matrix (B13 draft)."""
from __future__ import annotations

import re

from bid_agent.core.identity import Principal
from bid_agent.repositories import assets, bids, requirements as requirement_repo, responses, stages
from bid_agent.services import enterprise_assets
from bid_agent.services.score_coverage import compute_score_coverage, scoring_matrix_from_requirements

MATRIX_CATEGORIES = {'qualification', 'rejection', 'commercial', 'technical', 'scoring'}
CATEGORY_DEFAULT_SECTION = {
    'qualification': 'qualification',
    'commercial': 'commercial',
    'technical': 'technical',
    'scoring': 'technical',
    'rejection': 'other',
}


def rebuild_matrix(bid_version_id: str, user: Principal) -> dict:
    bid = bids.get_bid_version(bid_version_id, user)
    project_id = bid['project_id']
    stages.ensure_project_exists(project_id, user)
    stages.require_passed(project_id, 'outline', user)

    version_id = bid.get('document_version_id')
    if not version_id:
        raise ValueError('标书版本未关联文档版本，无法构建响应矩阵')

    extractor = requirement_repo.latest_extractor_version(version_id, user)
    items = requirement_repo.list_for_version(
        version_id, user, extractor_version=extractor,
    )
    eligible = [
        item for item in items
        if item.get('category') in MATRIX_CATEGORIES
        and item.get('review_status') != 'rejected'
    ]
    sections = bid.get('sections') or []
    section_by_key = {str(item.get('section_key') or ''): item for item in sections}
    score_map = _score_section_keys(eligible, sections)
    linked_assets = assets.list_for_project(project_id, user, usable_only=False)
    usable_assets = [item for item in linked_assets if item.get('usable')]
    expired_assets = [item for item in linked_assets if item.get('status') == 'expired' or item.get('expired')]

    rows: list[dict] = []
    for item in eligible:
        section = _suggest_section(item, sections, section_by_key, score_map)
        has_body = bool(str((section or {}).get('body_markdown') or '').strip())
        if section and has_body:
            status = 'drafted'
        elif section:
            status = 'mapped'
        else:
            status = 'uncovered'
        mandatory = _is_mandatory(item)
        missing = _infer_missing(item, status=status, has_body=has_body)
        matches = enterprise_assets.match_assets_for_requirement(item, usable_assets)
        if not matches and item.get('category') in {'qualification', 'commercial'}:
            expired_hits = enterprise_assets.match_assets_for_requirement(
                item, [{**asset, 'usable': True} for asset in expired_assets],
            )
            for hit in expired_hits[:2]:
                missing.append(f'关联资产已过期不可用：{hit.get("title")}')
                status = 'missing_material' if status in {'uncovered', 'mapped'} else status
            if not expired_hits and not matches:
                missing.append('未匹配到可用企业资产')
        rows.append({
            'requirement_item_id': item['id'],
            'section_id': (section or {}).get('id'),
            'response_status': status,
            'is_mandatory': mandatory,
            'response_summary': (
                f'可用资产：{", ".join(asset.get("title") or "" for asset in matches[:3])}'
                if matches else ''
            ),
            'missing_materials': list(dict.fromkeys(missing)),
            'notes': '',
        })

    saved = responses.replace_matrix(
        project_id=project_id,
        bid_version_id=bid_version_id,
        user=user,
        rows=rows,
    )
    return matrix_payload(bid_version_id, user, rows=saved)


def get_matrix(bid_version_id: str, user: Principal) -> dict:
    bids.get_bid_version(bid_version_id, user)  # access check
    return matrix_payload(bid_version_id, user)


def update_row(
    response_id: str,
    user: Principal,
    *,
    response_status: str | None = None,
    section_id: str | None = None,
    clear_section: bool = False,
    response_summary: str | None = None,
    missing_materials: list[str] | None = None,
    notes: str | None = None,
    is_mandatory: bool | None = None,
) -> dict:
    row = responses.update_response(
        response_id,
        user,
        response_status=response_status,
        section_id=section_id,
        clear_section=clear_section,
        response_summary=response_summary,
        missing_materials=missing_materials,
        notes=notes,
        is_mandatory=is_mandatory,
    )
    summary = matrix_payload(row['bid_version_id'], user)['summary']
    return {'row': row, 'summary': summary}


def matrix_payload(
    bid_version_id: str,
    user: Principal,
    *,
    rows: list[dict] | None = None,
) -> dict:
    items = rows if rows is not None else responses.list_for_bid(bid_version_id, user)
    summary = summarize(items)
    return {
        'bid_version_id': bid_version_id,
        'rows': items,
        'summary': summary,
        'missing_materials': missing_materials_list(items),
    }


def summarize(rows: list[dict]) -> dict:
    by_status: dict[str, int] = {}
    mandatory_total = 0
    mandatory_open = 0
    for row in rows:
        status = row.get('response_status') or 'uncovered'
        by_status[status] = by_status.get(status, 0) + 1
        if row.get('is_mandatory'):
            mandatory_total += 1
            if status in {'uncovered', 'mapped', 'missing_material'}:
                mandatory_open += 1
    return {
        'total': len(rows),
        'by_status': by_status,
        'mandatory_total': mandatory_total,
        'mandatory_open': mandatory_open,
        'coverage_rate': round(
            ((mandatory_total - mandatory_open) / mandatory_total) if mandatory_total else 1.0,
            4,
        ),
    }


def missing_materials_list(rows: list[dict]) -> list[dict]:
    result = []
    for row in rows:
        materials = row.get('missing_materials') or []
        status = row.get('response_status')
        if status == 'missing_material' or materials or (
            row.get('is_mandatory') and status in {'uncovered', 'mapped'}
        ):
            result.append({
                'response_id': row.get('id'),
                'requirement_item_id': row.get('requirement_item_id'),
                'requirement_title': row.get('requirement_title'),
                'category': row.get('requirement_category'),
                'is_mandatory': bool(row.get('is_mandatory')),
                'response_status': status,
                'section_title': row.get('section_title'),
                'materials': materials or (
                    ['待映射响应章节'] if status == 'uncovered'
                    else ['章节正文待补充'] if status == 'mapped'
                    else []
                ),
            })
    return result


def _score_section_keys(items: list[dict], sections: list[dict]) -> dict[str, str]:
    rows = scoring_matrix_from_requirements(items)
    coverage = compute_score_coverage(rows, sections)
    mapping = coverage.get('mapping') or {}
    # mapping: scoring item title → section_key
    by_req: dict[str, str] = {}
    for row in rows:
        key = mapping.get(row.get('item') or '')
        if key and row.get('requirement_item_id'):
            by_req[str(row['requirement_item_id'])] = str(key)
    return by_req


def _suggest_section(
    item: dict,
    sections: list[dict],
    section_by_key: dict[str, dict],
    score_map: dict[str, str],
) -> dict | None:
    req_id = str(item.get('id') or '')
    if req_id in score_map and score_map[req_id] in section_by_key:
        return section_by_key[score_map[req_id]]

    default_key = CATEGORY_DEFAULT_SECTION.get(item.get('category') or '')
    text = ' '.join(
        str(part or '')
        for part in (item.get('title'), item.get('normalized_value'), item.get('raw_text'))
    )
    tokens = _tokens(text)
    best = None
    best_score = 0.0
    for section in sections:
        title = str(section.get('title') or '')
        score = _overlap(tokens, _tokens(title))
        if default_key and section.get('section_key') == default_key:
            score = max(score, 0.35)
        if item.get('title') and str(item['title']) in title:
            score = max(score, 0.85)
        if score > best_score:
            best_score = score
            best = section
    if best_score >= 0.3:
        return best
    if default_key and default_key in section_by_key:
        return section_by_key[default_key]
    return None


def _is_mandatory(item: dict) -> bool:
    category = item.get('category')
    if category in {'qualification', 'rejection', 'scoring'}:
        return True
    text = f'{item.get("title") or ""} {item.get("normalized_value") or ""} {item.get("raw_text") or ""}'
    markers = ('★', '▲', '必须', '应当', '不得', '严禁', '实质性', '废标', '否决')
    return any(token in text for token in markers)


def _infer_missing(item: dict, *, status: str, has_body: bool) -> list[str]:
    missing: list[str] = []
    if status == 'uncovered':
        missing.append('待映射响应章节')
    elif status == 'mapped' and not has_body:
        missing.append('章节正文待补充')
    category = item.get('category')
    title = item.get('title') or item.get('field_key') or '要求'
    if category == 'qualification':
        missing.append(f'企业资质／证明材料：{title}')
    elif category == 'commercial':
        text = f'{item.get("title") or ""} {item.get("raw_text") or ""}'
        if any(token in text for token in ('业绩', '合同', '案例')):
            missing.append(f'业绩／合同证明：{title}')
    return list(dict.fromkeys(missing))


def _tokens(text: str) -> set[str]:
    parts = re.findall(r'[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}', text or '')
    return {part.lower() for part in parts}


def _overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / max(len(left), 1)
