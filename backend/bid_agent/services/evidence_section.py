"""Evidence-constrained section draft generation (B12 draft)."""
from __future__ import annotations

import re

from bid_agent.core.identity import Principal
from bid_agent.repositories import assets, bids, requirements as requirement_repo, responses
from bid_agent.services import bid_sections, enterprise_assets, evidence_search


FORBIDDEN_FABRICATION = re.compile(
    r'(证书编号|合同编号|金额|人员姓名|身份证|手机号)[：:]\s*(?!【待补充】)(\S+)'
)


def generate_from_evidence(
    section_id: str,
    user: Principal,
    *,
    overwrite: bool = False,
    mark_generate_gate: bool = True,
    use_llm: bool = False,
) -> dict:
    if use_llm:
        raise ValueError('证据约束成章草稿暂不启用 LLM；请使用规则拼装或关闭 use_llm')
    current = bids.get_section(section_id, user)
    existing = str(current.get('body_markdown') or '').strip()
    if existing and not overwrite:
        raise ValueError('章节已有正文；如需覆盖请传 overwrite=true')

    bid = bids.get_bid_version(current['bid_version_id'], user)
    project_id = bid['project_id']
    title = current.get('title') or '本章'
    evidence = _collect_evidence(project_id, user, bid=bid, section=current)
    body = _compose_markdown(title=title, evidence=evidence)
    if FORBIDDEN_FABRICATION.search(body):
        # Defensive: strip fabricated-looking assignments to placeholders.
        body = FORBIDDEN_FABRICATION.sub(r'\1：【待补充】', body)

    saved = bid_sections.save_section(
        section_id,
        user,
        body_markdown=body,
        mark_generate_gate=mark_generate_gate and bool(evidence['items'] or evidence['assets']),
    )
    return {
        **saved,
        'evidence_summary': {
            'requirement_count': len(evidence['items']),
            'asset_count': len(evidence['assets']),
            'quote_count': sum(len(item.get('quotes') or []) for item in evidence['items']),
            'pending_placeholders': body.count('【待补充】'),
        },
        'evidence': evidence,
    }


def _collect_evidence(project_id: str, user: Principal, *, bid: dict, section: dict) -> dict:
    section_id = section['id']
    section_key = section.get('section_key')
    title = section.get('title') or ''
    matrix_rows = []
    try:
        matrix_rows = responses.list_for_bid(bid['id'], user)
    except Exception:  # noqa: BLE001
        matrix_rows = []
    linked = [
        row for row in matrix_rows
        if row.get('section_id') == section_id
        or row.get('section_key') == section_key
        or (title and title in (row.get('section_title') or ''))
    ]
    # Fallback: search requirements related to section title.
    if not linked and title:
        hits = evidence_search.search(project_id, user, query=title, limit=8).get('hits') or []
        req_ids = [
            item['source_id'] for item in hits
            if item.get('source_type') == 'requirement'
        ]
        version_id = bid.get('document_version_id')
        if version_id and req_ids:
            extractor = requirement_repo.latest_extractor_version(version_id, user)
            items = requirement_repo.list_for_version(
                version_id, user, extractor_version=extractor,
            ) if extractor else []
            by_id = {item['id']: item for item in items}
            for req_id in req_ids:
                item = by_id.get(req_id)
                if item:
                    linked.append({
                        'requirement_item_id': item['id'],
                        'requirement_title': item.get('title'),
                        'requirement_value': item.get('normalized_value') or item.get('raw_text'),
                        'requirement_category': item.get('category'),
                        'requirement_source_refs': item.get('source_refs') or [],
                        'response_status': 'mapped',
                    })

    usable_assets = assets.list_for_project(project_id, user, usable_only=True)
    matched_assets = []
    for row in linked:
        req = {
            'category': row.get('requirement_category'),
            'title': row.get('requirement_title'),
            'normalized_value': row.get('requirement_value'),
            'raw_text': row.get('requirement_value'),
        }
        matched_assets.extend(enterprise_assets.match_assets_for_requirement(req, usable_assets))
    # Dedupe assets
    seen = set()
    assets_out = []
    for asset in matched_assets:
        if asset['id'] in seen:
            continue
        seen.add(asset['id'])
        assets_out.append(asset)

    items_out = []
    for row in linked:
        quotes = []
        for ref in row.get('requirement_source_refs') or []:
            quote = (ref.get('quote') or '').strip()
            if quote:
                quotes.append({
                    'quote': quote[:500],
                    'page': ref.get('page'),
                    'section_path': ref.get('section_path') or [],
                })
        items_out.append({
            'id': row.get('requirement_item_id'),
            'title': row.get('requirement_title'),
            'value': row.get('requirement_value'),
            'category': row.get('requirement_category'),
            'response_status': row.get('response_status'),
            'quotes': quotes,
        })
    return {'items': items_out, 'assets': assets_out}


def _compose_markdown(*, title: str, evidence: dict) -> str:
    lines = [
        f'## {title}',
        '',
        '### 响应说明',
        '本章依据已确认／已映射要求与可定位原文证据起草；未提供的企业事实一律标注【待补充】，不编造编号或金额。',
        '',
    ]
    items = evidence.get('items') or []
    if items:
        lines.extend(['### 对应要求与证据', ''])
        for index, item in enumerate(items, start=1):
            lines.append(f'{index}. **{item.get("title") or "要求"}**')
            if item.get('value'):
                lines.append(f'   - 要求摘录：{str(item["value"])[:300]}')
            quotes = item.get('quotes') or []
            if quotes:
                for quote in quotes[:3]:
                    page = f'（p.{quote["page"]}）' if quote.get('page') else ''
                    lines.append(f'   - 原文证据{page}：{quote["quote"]}')
            else:
                lines.append('   - 原文证据：【待补充】暂无来源摘录，请人工核对招标文件。')
            lines.append(f'   - 响应状态：{item.get("response_status") or "uncovered"}')
        lines.append('')
    else:
        lines.extend([
            '### 对应要求与证据',
            '',
            '- 【待补充】本章尚未映射到响应矩阵条目；请先重建矩阵或手工关联要求。',
            '',
        ])

    assets_list = evidence.get('assets') or []
    lines.extend(['### 可用企业材料', ''])
    if assets_list:
        for asset in assets_list[:8]:
            lines.append(
                f'- {asset.get("title")}（{asset.get("category")}）'
                + (f' · 编号 {asset.get("certificate_no")}' if asset.get('certificate_no') else ' · 编号【待补充】')
                + (f' · 到期 {asset.get("expires_on")}' if asset.get('expires_on') else '')
            )
    else:
        lines.append('- 【待补充】未匹配到可用（未过期）企业资产；请在企业资产面板补充并关联项目。')
    lines.extend([
        '',
        '### 待补充清单',
        '- 【待补充】本章盖章页／附件页码。',
        '- 【待补充】需人工确认的金额、人员与证书编号（禁止模型编造）。',
        '',
    ])
    return '\n'.join(lines)
