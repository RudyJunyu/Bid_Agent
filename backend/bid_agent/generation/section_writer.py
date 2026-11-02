# -*- coding: utf-8 -*-
"""Generate bid document section drafts from an outline and project knowledge."""
from __future__ import annotations

import json
import re
from typing import Any

from bid_agent.infrastructure.database import get_project_detail
from bid_agent.infrastructure.llm_client import LLM_Invoke


def generate_bid_section_draft(
    *,
    project_id: str,
    section_title: str,
    outline_markdown: str,
    llm: LLM_Invoke | None = None,
) -> dict[str, Any]:
    detail = get_project_detail(project_id)
    if not detail:
        raise ValueError("Project not found")

    context = build_section_context(detail, section_title)
    fallback = build_local_section_draft(section_title, context)
    markdown = fallback
    used_llm = False
    error_message = ""

    if llm:
        try:
            markdown = llm.think(
                build_section_draft_messages(
                    section_title=section_title,
                    outline_markdown=outline_markdown,
                    context=context,
                ),
                stream=False,
            ) or fallback
            used_llm = True
        except Exception as exc:
            error_message = str(exc) or exc.__class__.__name__
            markdown = fallback

    return {
        "project_id": project_id,
        "section_title": section_title,
        "draft_markdown": markdown,
        "used_llm": used_llm,
        "error_message": error_message,
        "context_summary": {
            "profile_items": len(context.get("profile", {})),
            "business_items": len(context.get("business", [])),
            "technical_items": len(context.get("technical", [])),
            "qualification_items": len(context.get("qualification", [])),
            "rejection_items": len(context.get("rejection", [])),
            "scoring_items": len(context.get("scoring", [])),
            "chunk_items": len(context.get("chunks", [])),
        },
    }


def build_section_draft_messages(
    *,
    section_title: str,
    outline_markdown: str,
    context: dict[str, Any],
) -> list[dict[str, str]]:
    context_text = json.dumps(context, ensure_ascii=False, indent=2)[:42000]
    outline_text = (outline_markdown or "")[:16000]
    return [
        {
            "role": "system",
            "content": (
                "你是专业投标文件撰写助手。请根据招标文件结构化抽取结果，为指定目录章节生成可编辑的投标文件正文草稿。"
                "要求：只写当前章节，不要生成整份标书；不要编造证书编号、金额、人员姓名、公司专有承诺等未提供事实；"
                "缺少公司侧资料时使用【待补充】占位；如果是暗标章节，避免出现投标人名称、企业标识、人员身份等可识别信息；"
                "正文应采用正式投标文件语气，保留可核对的响应点、表格和清单。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"【当前要生成的章节】\n{section_title}\n\n"
                f"【用户编辑后的目录】\n{outline_text}\n\n"
                f"【项目结构化数据和原文证据】\n{context_text}\n\n"
                "请输出 Markdown 正文，建议结构：\n"
                "1. 章节标题\n"
                "2. 响应说明\n"
                "3. 与招标要求的对应关系或响应表\n"
                "4. 待补充材料清单（如需要）\n"
            ),
        },
    ]


def build_section_context(detail: dict[str, Any], section_title: str) -> dict[str, Any]:
    project = detail.get("project") or {}
    tables = detail.get("tables") or {}
    profile = _first_row(tables, "project_profile")
    rows = {
        "business": _rows(tables, "business_requirements"),
        "technical": _rows(tables, "technical_requirements"),
        "qualification": _rows(tables, "qualification_requirements"),
        "rejection": _rows(tables, "rejection_items"),
        "scoring": _rows(tables, "scoring_items"),
        "chunks": _rows(tables, "document_chunks"),
    }
    keywords = _section_keywords(section_title)
    filtered = {name: _rank_rows(items, keywords, limit=_limit_for(name)) for name, items in rows.items()}
    return {
        "project": {
            "project_name": project.get("project_name") or profile.get("project_name"),
            "project_code": project.get("project_code") or profile.get("project_code"),
            "project_category": project.get("project_category") or profile.get("project_category"),
            "buyer_name": project.get("buyer_name") or profile.get("buyer_name"),
            "agency_name": project.get("agency_name") or profile.get("agency_name"),
            "budget_amount": project.get("budget_amount"),
        },
        "profile": _compact_row(profile),
        **filtered,
    }


def build_local_section_draft(section_title: str, context: dict[str, Any]) -> str:
    title = re.sub(r"^\s*(?:#+|\d+[.、]|[一二三四五六七八九十]+[、.])\s*", "", section_title).strip() or "章节正文"
    project = context.get("project") or {}
    lines = [
        f"# {title}",
        "",
        "## 一、响应说明",
        f"本章节根据{project.get('project_name') or '本项目'}招标文件要求编制，围绕“{title}”对应的资格、商务、技术和评分要求进行响应。",
        "涉及投标人专属信息、证明材料编号、人员姓名、证书编号、合同编号等内容，请在定稿前补充并复核。",
        "",
    ]
    if context.get("qualification"):
        lines.extend(["## 二、资格或材料响应要点", "", "| 序号 | 响应要点 | 需补充材料 |", "| --- | --- | --- |"])
        for index, row in enumerate(context["qualification"][:8], start=1):
            lines.append(f"| {index} | {_cell(row.get('requirement_text'))} | {_cell(row.get('required_materials') or '【待补充】')} |")
        lines.append("")
    if context.get("business"):
        lines.extend(["## 三、商务条款响应", "", "| 条款 | 响应内容 |", "| --- | --- |"])
        for row in context["business"][:8]:
            lines.append(f"| {_cell(row.get('item_name') or row.get('requirement_type'))} | {_cell(row.get('requirement_text'))} |")
        lines.append("")
    if context.get("technical"):
        lines.extend(["## 四、技术或实施响应", "", "| 要求 | 响应方案 |", "| --- | --- |"])
        for row in context["technical"][:8]:
            lines.append(f"| {_cell(row.get('item_name') or row.get('parameter_name'))} | {_cell(row.get('requirement_text'))} |")
        lines.append("")
    if context.get("scoring"):
        lines.extend(["## 五、评分点对应说明", "", "| 评分项 | 响应策略 | 分值 |", "| --- | --- | --- |"])
        for row in context["scoring"][:8]:
            lines.append(f"| {_cell(row.get('item_name'))} | {_cell(row.get('scoring_standard'))} | {_cell(row.get('score_text') or row.get('score_value'))} |")
        lines.append("")
    lines.extend(
        [
            "## 六、待补充与复核",
            "- 【待补充】投标人实际证明材料、附件页码和盖章签字状态。",
            "- 【待复核】本章节是否涉及暗标限制、废标项或格式性要求。",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def _rows(tables: dict[str, Any], table_name: str) -> list[dict[str, Any]]:
    table = tables.get(table_name) or {}
    rows = table.get("rows") or []
    return rows if isinstance(rows, list) else []


def _first_row(tables: dict[str, Any], table_name: str) -> dict[str, Any]:
    rows = _rows(tables, table_name)
    return rows[0] if rows else {}


def _section_keywords(title: str) -> list[str]:
    text = str(title or "")
    base = [item for item in re.split(r"[\s/／、，,（）()：:]+", text) if len(item) >= 2]
    groups = {
        "资格": ["资格", "资质", "证明", "承诺", "信用", "纳税", "社保"],
        "商务": ["商务", "报价", "合同", "付款", "保证金", "验收", "售后", "偏离"],
        "技术": ["技术", "方案", "实施", "服务", "质量", "进度", "验收", "运维"],
        "评分": ["评分", "评审", "得分", "业绩", "人员", "方案"],
        "风险": ["废标", "否决", "无效", "实质性", "偏离"],
    }
    for key, values in groups.items():
        if key in text:
            base.extend(values)
    return list(dict.fromkeys(base))


def _rank_rows(rows: list[dict[str, Any]], keywords: list[str], limit: int) -> list[dict[str, Any]]:
    scored = []
    for row in rows:
        text = " ".join(str(value or "") for value in row.values())
        score = sum(2 if keyword in text else 0 for keyword in keywords)
        if score <= 0 and rows.index(row) < limit:
            score = 1
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [_compact_row(row) for _, row in scored[:limit]]


def _limit_for(name: str) -> int:
    return 12 if name == "chunks" else 10


def _compact_row(row: dict[str, Any]) -> dict[str, Any]:
    skip = {"metadata_json", "tags_json", "created_at", "updated_at", "confirmed_status"}
    output = {}
    for key, value in row.items():
        if key in skip or value in (None, ""):
            continue
        text = str(value)
        output[key] = text if len(text) <= 500 else text[:500] + "..."
    return output


def _cell(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "【待补充】")).replace("|", "｜").strip()
