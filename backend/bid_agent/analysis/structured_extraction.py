# -*- coding: utf-8 -*-
"""JSON Schema based extraction for bid analysis modules."""
from __future__ import annotations

import json
import os
import re
from typing import Any, Iterable

from bid_agent.analysis.prompts import format_global_context_for_specialist


FIELD_TO_SCHEMA_KEY = {
    "business_content": "business_requirements",
    "technical_scoring_requirements": "technical_requirements",
    "qualification_compliance_requirements": "qualification_and_rejection",
    "price_scoring_requirements": "scoring_items",
}


def structured_output_enabled() -> bool:
    if os.getenv("BID_FAST_MARKDOWN_EXTRACTION", "true").lower() not in {
        "0",
        "false",
        "no",
        "off",
    }:
        return False
    return os.getenv("BID_STRUCTURED_OUTPUT_ENABLED", "false").lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def build_structured_messages(
    field: str,
    sections: Iterable[Any],
    global_context: str = "",
) -> list[dict[str, str]]:
    schema = STRUCTURED_SCHEMAS[FIELD_TO_SCHEMA_KEY[field]]
    file_content = sections_to_structured_source_context(sections)
    return [
        {
            "role": "system",
            "content": (
                "你是严谨的招投标结构化抽取引擎。"
                "必须按 JSON Schema 输出结构化对象，不要输出 Markdown、解释、代码块或多余字段。"
                "每一条要求、材料、废标情形或评分点都必须拆成独立数组元素。"
                "不得合并多个互不相同的条目；缺失字段用空字符串、false 或 null。"
                "每个原子条目必须回填 source_chunk_id 和 source_text；source_chunk_id 必须来自候选章节中的【source_chunk_id】标记，source_text 必须摘录原文证据。"
            ),
        },
        {
            "role": "user",
            "content": (
                "【全局项目信息和章节树】\n"
                f"{format_global_context_for_specialist(global_context)}\n\n"
                "【输出 JSON Schema】\n"
                f"{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
                "【候选章节内容】\n"
                f"{file_content.strip()}"
            ),
        },
    ]


def sections_to_structured_source_context(sections: Iterable[Any]) -> str:
    """Pack candidate sections with explicit source chunk ids for evidence tracing."""
    blocks: list[str] = []
    for fallback_index, section in enumerate(sections, start=1):
        if isinstance(section, dict):
            index = section.get("index") or fallback_index
            title = str(section.get("title") or "").strip()
            markdown = str(section.get("markdown") or section.get("content") or "").strip()
        else:
            index = getattr(section, "index", fallback_index) or fallback_index
            title = str(getattr(section, "title", "") or "").strip()
            markdown = str(getattr(section, "markdown", "") or getattr(section, "content", "") or "").strip()
        source_chunk_id = f"S{index}"
        blocks.append(
            "\n".join(
                [
                    f"【source_chunk_id】{source_chunk_id}",
                    f"【source_title】{title}",
                    markdown,
                ]
            ).strip()
        )
    return "\n\n".join(block for block in blocks if block).strip()


def schema_for_field(field: str) -> dict[str, Any]:
    return STRUCTURED_SCHEMAS[FIELD_TO_SCHEMA_KEY[field]]


def parse_structured_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}


def structured_to_markdown(field: str, data: dict[str, Any]) -> str:
    if field == "business_content":
        return _business_to_markdown(data)
    if field == "technical_scoring_requirements":
        return _technical_to_markdown(data)
    if field == "qualification_compliance_requirements":
        return _qualification_to_markdown(data)
    if field == "price_scoring_requirements":
        return _scoring_to_markdown(data)
    return ""


def _business_to_markdown(data: dict[str, Any]) -> str:
    rows = _list(data.get("business_requirements"))
    lines = ["# 商务内容", "", "| 项目 | 内容 |", "| --- | --- |"]
    for row in rows:
        item = _cell(row.get("item_name") or row.get("requirement_type"))
        text = _cell(row.get("requirement_text"))
        evidence = _cell(row.get("evidence_snippet"))
        source = _source_note(row)
        if evidence:
            text = f"{text}（原文依据：{evidence}）" if text else evidence
        if source:
            text = f"{text}（{source}）" if text else source
        lines.append(f"| {item or '未明确'} | {text or '未明确'} |")
    if len(lines) == 4:
        lines.append("| 未提及 | 未提及 |")
    return "\n".join(lines)


def _technical_to_markdown(data: dict[str, Any]) -> str:
    rows = _list(data.get("technical_requirements"))
    lines = [
        "# 技术要求",
        "",
        "| 要求分组 | 条目 | 具体要求 | 验收/指标 |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        requirement = _cell(row.get("requirement_text"))
        evidence = _cell(row.get("evidence_snippet"))
        source = _source_note(row)
        if evidence:
            requirement = f"{requirement}（原文依据：{evidence}）" if requirement else evidence
        if source:
            requirement = f"{requirement}（{source}）" if requirement else source
        lines.append(
            "| {group} | {item} | {requirement} | {acceptance} |".format(
                group=_cell(row.get("requirement_group")) or "未明确",
                item=_cell(row.get("item_name") or row.get("parameter_name")) or "未明确",
                requirement=requirement or "未明确",
                acceptance=_cell(row.get("acceptance_criteria") or row.get("parameter_value")) or "未明确",
            )
        )
    if len(lines) == 4:
        lines.append("| 未提及 | 未提及 | 未提及 | 未提及 |")
    return "\n".join(lines)


def _qualification_to_markdown(data: dict[str, Any]) -> str:
    qualification_rows = _list(data.get("qualification_requirements"))
    rejection_rows = _list(data.get("rejection_items"))
    lines = [
        "## 资格性审查",
        "| 序号 | 资格要求 | 需提供资料 |",
        "| --- | --- | --- |",
    ]
    qual_index = 1
    compliance_lines = [
        "",
        "## 符合性审查",
        "| 序号 | 资格要求 | 需提供资料 |",
        "| --- | --- | --- |",
    ]
    comp_index = 1
    for row in qualification_rows:
        review_type = _cell(row.get("review_type"))
        target = compliance_lines if "符合" in review_type or "响应" in review_type else lines
        index = comp_index if target is compliance_lines else qual_index
        target.append(
            f"| {_cell(row.get('sequence_no')) or index} | "
            f"{_with_source(row, 'requirement_text') or '未明确'} | "
            f"{_cell(row.get('required_materials')) or '未明确'} |"
        )
        if target is compliance_lines:
            comp_index += 1
        else:
            qual_index += 1
    if qual_index == 1:
        lines.append("| 1 | 未提及 | 未提及 |")
    if comp_index == 1:
        compliance_lines.append("| 1 | 未提及 | 未提及 |")
    lines.extend(compliance_lines)
    lines.extend(["", "## 废标项", "| 序号 | 废标项 | 具体表现 |", "| --- | --- | --- |"])
    for index, row in enumerate(rejection_rows, start=1):
        lines.append(
            f"| {_cell(row.get('sequence_no')) or index} | "
            f"{_cell(row.get('rejection_item')) or '未明确'} | "
            f"{_with_source(row, 'specific_behavior') or '未明确'} |"
        )
    if not rejection_rows:
        lines.append("| 1 | 未提及 | 未提及 |")
    return "\n".join(lines)


def _scoring_to_markdown(data: dict[str, Any]) -> str:
    rows = _list(data.get("scoring_items"))
    business = [row for row in rows if "商务" in _cell(row.get("type") or row.get("score_type"))]
    technical = [row for row in rows if "技术" in _cell(row.get("type") or row.get("score_type"))]
    other = [row for row in rows if row not in business and row not in technical]
    business.extend(other)
    lines = ["## 商务评分", "| 评分项 | 评分标准 | 分数 |", "| --- | --- | --- |"]
    _append_scoring_rows(lines, business)
    lines.extend(["", "## 技术评分", "| 评分项 | 评分标准 | 分数 |", "| --- | --- | --- |"])
    _append_scoring_rows(lines, technical)
    return "\n".join(lines)


def _append_scoring_rows(lines: list[str], rows: list[dict[str, Any]]) -> None:
    if not rows:
        lines.append("| 未提及 | 未提及 | 未提及 |")
        return
    for row in rows:
        standard = _cell(row.get("standard") or row.get("scoring_standard"))
        evidence = _cell(row.get("evidence_snippet"))
        source = _source_note(row)
        if evidence:
            standard = f"{standard}（原文依据：{evidence}）" if standard else evidence
        if source:
            standard = f"{standard}（{source}）" if standard else source
        lines.append(
            f"| {_cell(row.get('item') or row.get('item_name')) or '未明确'} | "
            f"{standard or '未明确'} | "
            f"{_cell(row.get('max_score') or row.get('score_text') or row.get('score_value')) or '未明确'} |"
        )


def _list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _cell(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "/").strip()


def _source_note(row: dict[str, Any]) -> str:
    source_chunk_id = _cell(row.get("source_chunk_id"))
    source_text = _cell(row.get("source_text"))
    parts = []
    if source_chunk_id:
        parts.append(f"来源：{source_chunk_id}")
    if source_text:
        parts.append(f"原文：{source_text}")
    return "；".join(parts)


def _with_source(row: dict[str, Any], field: str) -> str:
    value = _cell(row.get(field))
    source = _source_note(row)
    return f"{value}（{source}）" if value and source else value or source


TEXT_FIELD = {"type": "string"}
BOOL_FIELD = {"type": "boolean"}
NUMBER_FIELD = {"type": ["number", "null"]}
RISK_LEVEL_FIELD = {"type": "string", "enum": ["高", "中", "低", "未明确"]}
REVIEW_TYPE_FIELD = {"type": "string", "enum": ["资格性", "符合性", "响应性", "其他"]}
LEGAL_NATURE_FIELD = {"type": "string", "enum": ["资格性", "符合性", "响应性", "其他"]}
STATUS_FIELD = {"type": "string", "enum": ["open", "resolved", "ignored"]}
IMPORTANCE_LEVEL_FIELD = {"type": "string", "enum": ["高", "中", "低", "未明确"]}
SCORE_TYPE_FIELD = {"type": "string", "enum": ["商务评分", "技术评分", "价格评分", "其他"]}
BUSINESS_TYPE_FIELD = {
    "type": "string",
    "enum": ["报价", "合同", "付款", "交付", "验收", "保证金", "售后", "服务", "政策", "其他"],
}


def _source_properties() -> dict[str, Any]:
    return {
        "source_chunk_id": TEXT_FIELD,
        "source_text": TEXT_FIELD,
        "source_heading": TEXT_FIELD,
        "evidence_snippet": TEXT_FIELD,
    }


SOURCE_REQUIRED = ["source_chunk_id", "source_text", "source_heading", "evidence_snippet"]


STRUCTURED_SCHEMAS: dict[str, dict[str, Any]] = {
    "business_requirements": {
        "title": "business_requirements",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "business_requirements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "requirement_type": BUSINESS_TYPE_FIELD,
                        "item_name": TEXT_FIELD,
                        "requirement_text": TEXT_FIELD,
                        "amount": TEXT_FIELD,
                        "ratio": TEXT_FIELD,
                        "deadline_text": TEXT_FIELD,
                        "is_mandatory": BOOL_FIELD,
                        **_source_properties(),
                    },
                    "required": [
                        "requirement_type",
                        "item_name",
                        "requirement_text",
                        "amount",
                        "ratio",
                        "deadline_text",
                        "is_mandatory",
                        *SOURCE_REQUIRED,
                    ],
                },
            }
        },
        "required": ["business_requirements"],
    },
    "technical_requirements": {
        "title": "technical_requirements",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "technical_requirements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "requirement_group": TEXT_FIELD,
                        "item_name": TEXT_FIELD,
                        "parameter_name": TEXT_FIELD,
                        "parameter_value": TEXT_FIELD,
                        "requirement_text": TEXT_FIELD,
                        "acceptance_criteria": TEXT_FIELD,
                        "is_mandatory": BOOL_FIELD,
                        "importance_level": IMPORTANCE_LEVEL_FIELD,
                        **_source_properties(),
                    },
                    "required": [
                        "requirement_group",
                        "item_name",
                        "parameter_name",
                        "parameter_value",
                        "requirement_text",
                        "acceptance_criteria",
                        "is_mandatory",
                        "importance_level",
                        *SOURCE_REQUIRED,
                    ],
                },
            }
        },
        "required": ["technical_requirements"],
    },
    "qualification_and_rejection": {
        "title": "qualification_and_rejection",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "qualification_requirements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "review_type": REVIEW_TYPE_FIELD,
                        "sequence_no": TEXT_FIELD,
                        "requirement_text": TEXT_FIELD,
                        "required_materials": TEXT_FIELD,
                        "is_mandatory": BOOL_FIELD,
                        "risk_level": RISK_LEVEL_FIELD,
                        **_source_properties(),
                    },
                    "required": [
                        "review_type",
                        "sequence_no",
                        "requirement_text",
                        "required_materials",
                        "is_mandatory",
                        "risk_level",
                        *SOURCE_REQUIRED,
                    ],
                },
            },
            "rejection_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "sequence_no": TEXT_FIELD,
                        "rejection_item": TEXT_FIELD,
                        "specific_behavior": TEXT_FIELD,
                        "risk_level": RISK_LEVEL_FIELD,
                        "legal_nature": LEGAL_NATURE_FIELD,
                        "related_module": TEXT_FIELD,
                        **_source_properties(),
                    },
                    "required": [
                        "sequence_no",
                        "rejection_item",
                        "specific_behavior",
                        "risk_level",
                        "legal_nature",
                        "related_module",
                        *SOURCE_REQUIRED,
                    ],
                },
            },
        },
        "required": ["qualification_requirements", "rejection_items"],
    },
    "scoring_items": {
        "title": "scoring_items",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "scoring_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "type": SCORE_TYPE_FIELD,
                        "item": TEXT_FIELD,
                        "standard": TEXT_FIELD,
                        "max_score": NUMBER_FIELD,
                        "score_text": TEXT_FIELD,
                        **_source_properties(),
                    },
                    "required": [
                        "type",
                        "item",
                        "standard",
                        "max_score",
                        "score_text",
                        *SOURCE_REQUIRED,
                    ],
                },
            }
        },
        "required": ["scoring_items"],
    },
    "review_findings": {
        "title": "review_findings",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "review_findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "review_type": TEXT_FIELD,
                        "module": TEXT_FIELD,
                        "risk_level": RISK_LEVEL_FIELD,
                        "status": STATUS_FIELD,
                        "finding_title": TEXT_FIELD,
                        "finding_detail": TEXT_FIELD,
                        "suggestion": TEXT_FIELD,
                        **_source_properties(),
                    },
                    "required": [
                        "review_type",
                        "module",
                        "risk_level",
                        "status",
                        "finding_title",
                        "finding_detail",
                        "suggestion",
                        *SOURCE_REQUIRED,
                    ],
                },
            }
        },
        "required": ["review_findings"],
    },
}
