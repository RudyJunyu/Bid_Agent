"""B07 LLM refine pass: fill/correct low-confidence requirements with evidence quotes."""
from __future__ import annotations

import json
import os
import re
from typing import Any

from bid_agent.core.model_config import resolve_llm_selection
from bid_agent.infrastructure.llm_client import LLM_Invoke
from bid_agent.parsing.document_parser import BidDocumentSection
from bid_agent.repositories.platform import new_id, now
from bid_agent.schemas.documents import ParsedBlock
from bid_agent.schemas.requirements import RequirementItem
from bid_agent.services.requirement_extract import (
    OVERVIEW_FIELD_KEYS,
    _coerce_blocks,
    _coerce_sections,
    _dedupe,
    _locate_evidence,
    _overview_evidence_hints,
)

HYBRID_EXTRACTOR_VERSION = 'b07-hybrid-v1'

OVERVIEW_TARGETS = (
    ('project_name', '项目名称'),
    ('project_code', '项目编号'),
    ('buyer_name', '采购人'),
    ('agency_name', '招标代理机构'),
    ('budget_text', '项目规模和预算'),
    ('open_time', '开标时间'),
    ('bid_deadline', '投标文件提交截止时间'),
    ('procurement_method', '采购方式'),
    ('joint_venture', '是否允许联合体投标'),
)

REFINE_SCHEMA: dict[str, object] = {
    'title': 'B07RequirementRefine',
    'type': 'object',
    'additionalProperties': False,
    'properties': {
        'overview': {
            'type': 'array',
            'items': {
                'type': 'object',
                'additionalProperties': False,
                'properties': {
                    'field_key': {'type': 'string'},
                    'title': {'type': 'string'},
                    'value': {'type': 'string'},
                    'quote': {'type': 'string'},
                },
                'required': ['field_key', 'title', 'value', 'quote'],
            },
        },
        'clauses': {
            'type': 'array',
            'items': {
                'type': 'object',
                'additionalProperties': False,
                'properties': {
                    'category': {
                        'type': 'string',
                        'enum': ['qualification', 'rejection', 'commercial', 'technical', 'scoring'],
                    },
                    'title': {'type': 'string'},
                    'raw_text': {'type': 'string'},
                    'quote': {'type': 'string'},
                },
                'required': ['category', 'title', 'raw_text', 'quote'],
            },
        },
    },
    'required': ['overview', 'clauses'],
}


def llm_configured() -> bool:
    """SiliconFlow experiments only need the API key; model/base have defaults."""
    return bool(os.getenv('LLM_API_KEY', '').strip())


def build_requirement_llm(
    *,
    vendor: str | None = None,
    model_name: str | None = None,
) -> LLM_Invoke:
    vendor_name = vendor or 'siliconflow'
    display_or_id = model_name or os.getenv('LLM_MODEL_DISPLAY_NAME') or os.getenv('LLM_MODEL_ID') or 'Qwen3-8B (轻量)'
    try:
        resolved_model, base_url = resolve_llm_selection(vendor_name, display_or_id)
    except ValueError:
        # Allow raw provider model ids already stored in env.
        resolved_model = display_or_id
        base_url = os.getenv('LLM_BASE_URL') or resolve_llm_selection('siliconflow', 'Qwen3-8B (轻量)')[1]
    return LLM_Invoke(
        model=resolved_model,
        base_url=base_url,
        enable_deep_thinking=False,
    )


def refine_requirements_with_llm(
    *,
    project_id: str,
    document_version_id: str,
    job_id: str | None,
    parsed: dict[str, Any],
    rule_items: list[RequirementItem],
    llm: LLM_Invoke,
    max_context_chars: int = 8000,
) -> list[RequirementItem]:
    sections = _coerce_sections(parsed.get('sections') or [])
    blocks = _coerce_blocks(parsed.get('blocks') or [])
    context = _build_refine_context(sections, max_chars=max_context_chars)
    if len(context) < 80:
        return rule_items

    messages = [
        {
            'role': 'system',
            'content': (
                '你是招投标结构化抽取助手。只根据给定原文抽取事实，禁止编造。'
                '只输出一个 JSON 对象，不要 Markdown 代码围栏，不要解释。'
                '格式：{"overview":[{"field_key":"","title":"","value":"","quote":""}],'
                '"clauses":[{"category":"qualification|rejection|commercial|technical|scoring",'
                '"title":"","raw_text":"","quote":""}]}。'
                'overview 覆盖项目关键字段；clauses 最多 12 条，优先资格与废标；'
                '每条 quote 必须能在原文中找到；找不到的字段不要输出。'
            ),
        },
        {
            'role': 'user',
            'content': (
                '请从下列招标文件片段抽取要求。字段 field_key 优先使用：'
                + ', '.join(key for key, _ in OVERVIEW_TARGETS)
                + '。\n\n'
                + context
            ),
        },
    ]

    # Prefer plain chat JSON: SiliconFlow json_schema is slow/unreliable on some models.
    try:
        raw = llm.think(messages, temperature=0, stream=False)
    except Exception:
        raw = llm.think_json(messages, schema=REFINE_SCHEMA, temperature=0)
    payload = _parse_json_object(raw)
    llm_items = _payload_to_items(
        payload,
        project_id=project_id,
        document_version_id=document_version_id,
        job_id=job_id,
        blocks=blocks,
        sections=sections,
    )
    return _merge_rule_and_llm(rule_items, llm_items)


def _build_refine_context(sections: list[BidDocumentSection], max_chars: int) -> str:
    preferred: list[str] = []
    fallback: list[str] = []
    keywords = (
        '项目基本情况', '招标公告', '资格', '废标', '否决', '无效', '开标', '截止',
        '预算', '采购人', '代理', '联合体', '评标', '评分',
    )
    for section in sections:
        title = section.title or ''
        body = (section.markdown or section.content or '').strip()
        if not body:
            continue
        chunk = f"## {title}\n{body[:1200]}"
        blob = title + body
        if any(word in blob for word in keywords) or section.level <= 2:
            preferred.append(chunk)
        else:
            fallback.append(chunk)

    parts: list[str] = []
    size = 0
    for chunk in preferred + fallback:
        if size >= max_chars:
            break
        take = chunk[: max(0, max_chars - size)]
        if not take:
            break
        parts.append(take)
        size += len(take) + 2
    return '\n\n'.join(parts)


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = (raw or '').strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', text, flags=re.S)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}


def _payload_to_items(
    payload: dict[str, Any],
    *,
    project_id: str,
    document_version_id: str,
    job_id: str | None,
    blocks: list[ParsedBlock],
    sections: list[BidDocumentSection],
) -> list[RequirementItem]:
    timestamp = now()
    items: list[RequirementItem] = []
    allowed_overview = {key for key, _ in OVERVIEW_TARGETS}
    title_by_key = {key: title for key, title in OVERVIEW_TARGETS}
    # Also accept Chinese labels mapped through OVERVIEW_FIELD_KEYS.
    for chinese, key in OVERVIEW_FIELD_KEYS.items():
        title_by_key.setdefault(key, chinese)

    for row in payload.get('overview') or []:
        if not isinstance(row, dict):
            continue
        field_key = str(row.get('field_key') or '').strip()
        value = str(row.get('value') or '').strip()
        quote = str(row.get('quote') or value).strip()
        title = str(row.get('title') or title_by_key.get(field_key) or field_key).strip()
        if field_key not in allowed_overview or not value or value in {'未提及', '未提取'}:
            continue
        refs = _locate_evidence(
            quote or value,
            blocks,
            sections,
            evidence_hints=_overview_evidence_hints(field_key, title, value),
        )
        if not refs:
            # Require locatable evidence for LLM outputs.
            continue
        items.append(RequirementItem(
            id=new_id('req'),
            project_id=project_id,
            document_version_id=document_version_id,
            job_id=job_id,
            category='overview',
            field_key=field_key,
            title=title[:200],
            raw_text=value,
            normalized_value=value,
            confidence=0.9,
            source_refs=refs,
            extractor_version=HYBRID_EXTRACTOR_VERSION,
            created_at=timestamp,
            updated_at=timestamp,
        ))

    for row in payload.get('clauses') or []:
        if not isinstance(row, dict):
            continue
        category = str(row.get('category') or '').strip()
        title = str(row.get('title') or '').strip()
        raw_text = str(row.get('raw_text') or '').strip()
        quote = str(row.get('quote') or raw_text[:120]).strip()
        if category not in {'qualification', 'rejection', 'commercial', 'technical', 'scoring'}:
            continue
        if len(raw_text) < 12 or not title:
            continue
        refs = _locate_evidence(quote, blocks, sections)
        if not refs:
            continue
        items.append(RequirementItem(
            id=new_id('req'),
            project_id=project_id,
            document_version_id=document_version_id,
            job_id=job_id,
            category=category,  # type: ignore[arg-type]
            field_key=None,
            title=title[:200],
            raw_text=raw_text[:800],
            normalized_value=None,
            confidence=0.82,
            source_refs=refs,
            extractor_version=HYBRID_EXTRACTOR_VERSION,
            created_at=timestamp,
            updated_at=timestamp,
        ))
    return _dedupe(items)


def _merge_rule_and_llm(
    rule_items: list[RequirementItem],
    llm_items: list[RequirementItem],
) -> list[RequirementItem]:
    timestamp = now()
    merged: list[RequirementItem] = []
    llm_overview = {
        item.field_key: item
        for item in llm_items
        if item.category == 'overview' and item.field_key
    }
    seen_overview: set[str] = set()

    for item in rule_items:
        if item.category == 'overview' and item.field_key:
            replacement = llm_overview.get(item.field_key)
            weak = (
                item.confidence < 0.8
                or not item.source_refs
                or not _looks_like_datetime_if_needed(item)
            )
            if replacement and (weak or _llm_value_richer(item, replacement)):
                merged.append(replacement)
                seen_overview.add(item.field_key)
                continue
            seen_overview.add(item.field_key)
            merged.append(item.model_copy(update={
                'extractor_version': HYBRID_EXTRACTOR_VERSION,
                'updated_at': timestamp,
            }))
            continue
        merged.append(item.model_copy(update={
            'extractor_version': HYBRID_EXTRACTOR_VERSION,
            'updated_at': timestamp,
        }))

    for field_key, item in llm_overview.items():
        if field_key not in seen_overview:
            merged.append(item)

    existing_clause_keys = {
        (item.category, re.sub(r'\s+', '', item.title)[:80])
        for item in merged
        if item.category != 'overview'
    }
    for item in llm_items:
        if item.category == 'overview':
            continue
        key = (item.category, re.sub(r'\s+', '', item.title)[:80])
        if key in existing_clause_keys:
            continue
        existing_clause_keys.add(key)
        merged.append(item)
    return _dedupe(merged)


def _looks_like_datetime_if_needed(item: RequirementItem) -> bool:
    if item.field_key not in {'open_time', 'bid_deadline'}:
        return True
    return bool(re.search(r'20\d{2}\s*年', item.normalized_value or item.raw_text or ''))


def _llm_value_richer(rule_item: RequirementItem, llm_item: RequirementItem) -> bool:
    rule_value = (rule_item.normalized_value or rule_item.raw_text or '').strip()
    llm_value = (llm_item.normalized_value or llm_item.raw_text or '').strip()
    if not llm_value:
        return False
    if rule_item.field_key in {'open_time', 'bid_deadline'}:
        return ('年' in llm_value) and ('年' not in rule_value or len(llm_value) > len(rule_value))
    return len(llm_value) >= len(rule_value) and llm_value != rule_value
