"""B07 draft extractor: rule-first structured requirements with evidence refs."""
from __future__ import annotations

import re
from typing import Any

from bid_agent.analysis.rule_extractor import PROFILE_FIELDS, extract_rule_project_profile
from bid_agent.parsing.document_parser import BidDocumentSection
from bid_agent.repositories import requirements as requirement_repo
from bid_agent.repositories.platform import new_id, now
from bid_agent.schemas.documents import ParsedBlock
from bid_agent.schemas.requirements import RequirementItem, SourceRef

EXTRACTOR_VERSION = 'b07-rule-v1'

CATEGORY_HINTS: dict[str, tuple[str, ...]] = {
    'qualification': ('资格', '资质要求', '投标人资格', '供应商资格', '特定资格', '资格审查'),
    'rejection': ('废标', '否决', '无效投标', '拒绝接收', '作无效', '投标无效'),
    'commercial': ('付款', '保证金', '履约', '商务要求', '合同履行', '质保', '交付期限', '服务期限'),
    'technical': ('技术要求', '服务要求', '技术参数', '验收', '运维', '功能要求', '性能指标', '采购需求'),
    'scoring': ('评分', '分值', '评标办法', '综合评分', '评分标准', '得分'),
}

OVERVIEW_FIELD_KEYS = {
    '项目名称': 'project_name',
    '项目编号': 'project_code',
    '采购人': 'buyer_name',
    '招标代理机构': 'agency_name',
    '项目规模和预算': 'budget_text',
    '开标时间': 'open_time',
    '投标文件提交截止时间': 'bid_deadline',
    '采购方式': 'procurement_method',
    '是否允许联合体投标': 'joint_venture',
}


def extract_requirements_from_parsed(
    *,
    project_id: str,
    document_version_id: str,
    job_id: str | None,
    parsed: dict[str, Any],
) -> list[RequirementItem]:
    sections = _coerce_sections(parsed.get('sections') or [])
    blocks = _coerce_blocks(parsed.get('blocks') or [])
    timestamp = now()
    items: list[RequirementItem] = []

    profile = extract_rule_project_profile(sections)
    # Prefer English field keys for overview; fall back to Chinese labels from rule extractor.
    overview_pairs = []
    for english_key, chinese_label in PROFILE_FIELDS.items():
        value = ''
        # rule extractor returns Chinese label keys
        value = str(profile.get(chinese_label) or '').strip()
        if value and value not in {'未提及', '未提取'}:
            overview_pairs.append((english_key, chinese_label, value))
    for chinese_label, field_key in OVERVIEW_FIELD_KEYS.items():
        value = str(profile.get(chinese_label) or '').strip()
        if value and value not in {'未提及', '未提取'}:
            if not any(pair[0] == field_key for pair in overview_pairs):
                overview_pairs.append((field_key, chinese_label, value))

    seen_overview = set()
    for field_key, title, value in overview_pairs:
        if field_key in seen_overview:
            continue
        seen_overview.add(field_key)
        refs = _locate_evidence(value, blocks, sections)
        confidence = 0.85 if refs else 0.55
        items.append(_item(
            project_id=project_id,
            document_version_id=document_version_id,
            job_id=job_id,
            category='overview',
            field_key=field_key,
            title=title,
            raw_text=value,
            normalized_value=value,
            confidence=confidence,
            source_refs=refs,
            timestamp=timestamp,
        ))

    for section in sections:
        category = _category_for_section(section)
        if not category:
            continue
        text = (section.markdown or section.content or '').strip()
        if len(text) < 12:
            continue
        title = (section.title or category).strip()
        # Skip very large chapter dumps as a single item; prefer mid-level titles.
        if section.level <= 1 and len(text) > 2500:
            continue
        quote = text if len(text) <= 800 else text[:800]
        refs = _locate_evidence(quote[:120], blocks, sections, preferred_section=section)
        if not refs:
            refs = [_section_ref(section, quote[:240])]
        items.append(_item(
            project_id=project_id,
            document_version_id=document_version_id,
            job_id=job_id,
            category=category,
            field_key=None,
            title=title[:200],
            raw_text=quote,
            normalized_value=None,
            confidence=0.7 if refs and refs[0].block_id else 0.5,
            source_refs=refs,
            timestamp=timestamp,
        ))

    # Deduplicate near-identical titles within a category.
    return _dedupe(items)


def _item(**kwargs) -> RequirementItem:
    timestamp = kwargs.pop('timestamp')
    return RequirementItem(
        id=new_id('req'),
        created_at=timestamp,
        updated_at=timestamp,
        extractor_version=EXTRACTOR_VERSION,
        **kwargs,
    )


def _coerce_sections(raw: list[Any]) -> list[BidDocumentSection]:
    sections: list[BidDocumentSection] = []
    for index, item in enumerate(raw, start=1):
        if isinstance(item, BidDocumentSection):
            sections.append(item)
            continue
        if not isinstance(item, dict):
            continue
        payload = dict(item)
        payload.setdefault('index', index)
        payload.setdefault('level', 2)
        payload.setdefault('content', '')
        payload.setdefault('markdown', payload.get('content') or '')
        payload.setdefault('title', f'段落{index}')
        payload.setdefault('metadata', {})
        sections.append(BidDocumentSection.model_validate(payload))
    return sections


def _coerce_blocks(raw: list[Any]) -> list[ParsedBlock]:
    blocks: list[ParsedBlock] = []
    for item in raw:
        if isinstance(item, ParsedBlock):
            blocks.append(item)
        elif isinstance(item, dict):
            try:
                blocks.append(ParsedBlock.model_validate(item))
            except Exception:
                continue
    return blocks


def _category_for_section(section: BidDocumentSection) -> str | None:
    blob = f"{section.title}\n{section.content}"
    scores: dict[str, int] = {}
    for category, hints in CATEGORY_HINTS.items():
        score = sum(1 for hint in hints if hint in blob)
        if score:
            scores[category] = score
    if not scores:
        return None
    return max(scores, key=scores.get)


def _locate_evidence(
    needle: str,
    blocks: list[ParsedBlock],
    sections: list[BidDocumentSection],
    preferred_section: BidDocumentSection | None = None,
) -> list[SourceRef]:
    cleaned = re.sub(r'\s+', '', needle or '')
    if len(cleaned) < 4:
        if preferred_section:
            return [_section_ref(preferred_section, needle)]
        return []

    for block in blocks:
        hay = re.sub(r'\s+', '', block.text or '')
        if cleaned[:40] in hay or (len(cleaned) >= 12 and cleaned[:12] in hay):
            return [SourceRef(
                block_id=block.id,
                section_index=block.section_index,
                section_path=list(block.section_path or []),
                page=block.page,
                quote=(block.text or '')[:240],
            )]

    if preferred_section:
        return [_section_ref(preferred_section, needle)]

    for section in sections:
        hay = re.sub(r'\s+', '', (section.markdown or section.content or ''))
        if cleaned[:40] in hay or (len(cleaned) >= 12 and cleaned[:12] in hay):
            return [_section_ref(section, needle)]
    return []


def _section_ref(section: BidDocumentSection, quote: str) -> SourceRef:
    metadata = section.metadata or {}
    path = metadata.get('title_path') or [section.title]
    if not isinstance(path, list):
        path = [str(path)]
    page = metadata.get('page_start') or metadata.get('page')
    try:
        page = int(page) if page is not None else None
    except (TypeError, ValueError):
        page = None
    return SourceRef(
        block_id=None,
        section_index=section.index,
        section_path=[str(part) for part in path],
        page=page if page and page > 0 else None,
        quote=(quote or section.title or '')[:240],
    )


def _dedupe(items: list[RequirementItem]) -> list[RequirementItem]:
    seen: set[tuple[str, str]] = set()
    result: list[RequirementItem] = []
    for item in items:
        key = (item.category, re.sub(r'\s+', '', item.title)[:80])
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def extract_and_store(project_id: str, document_version_id: str, job_id: str | None, parsed: dict, user) -> list[dict]:
    items = extract_requirements_from_parsed(
        project_id=project_id,
        document_version_id=document_version_id,
        job_id=job_id,
        parsed=parsed,
    )
    return requirement_repo.replace_drafts(
        project_id=project_id,
        document_version_id=document_version_id,
        job_id=job_id,
        items=[item.model_dump() for item in items],
        user=user,
        extractor_version=EXTRACTOR_VERSION,
    )
