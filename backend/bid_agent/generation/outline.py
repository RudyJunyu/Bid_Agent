# -*- coding: utf-8 -*-
"""Generate a bid document outline from structured project extraction results."""
from __future__ import annotations

import re
from typing import Any

from bid_agent.infrastructure.database import get_project_detail


def generate_bid_outline(project_id: str) -> dict[str, Any]:
    detail = get_project_detail(project_id)
    if not detail:
        raise ValueError("Project not found")

    project = detail.get("project") or {}
    tables = detail.get("tables") or {}
    profile = _first_row(tables, "project_profile")
    business = _rows(tables, "business_requirements")
    technical = _rows(tables, "technical_requirements")
    qualification = _rows(tables, "qualification_requirements")
    rejection = _rows(tables, "rejection_items")
    scoring = _rows(tables, "scoring_items")
    chunks = _rows(tables, "document_chunks")

    writing_requirements = _writing_requirement_chunks(chunks)
    outline = _build_outline_markdown(
        project=project,
        profile=profile,
        business=business,
        technical=technical,
        qualification=qualification,
        rejection=rejection,
        scoring=scoring,
        writing_requirements=writing_requirements,
    )
    return {
        "project_id": project_id,
        "project_name": project.get("project_name") or profile.get("project_name") or "未命名项目",
        "outline_markdown": outline,
        "writing_requirements": writing_requirements,
        "stats": {
            "business_requirements": len(business),
            "technical_requirements": len(technical),
            "qualification_requirements": len(qualification),
            "rejection_items": len(rejection),
            "scoring_items": len(scoring),
            "writing_requirement_hits": len(writing_requirements),
        },
    }


def _build_outline_markdown(
    *,
    project: dict[str, Any],
    profile: dict[str, Any],
    business: list[dict[str, Any]],
    technical: list[dict[str, Any]],
    qualification: list[dict[str, Any]],
    rejection: list[dict[str, Any]],
    scoring: list[dict[str, Any]],
    writing_requirements: list[dict[str, Any]],
) -> str:
    project_name = project.get("project_name") or profile.get("project_name") or "未命名项目"
    project_code = project.get("project_code") or profile.get("project_code") or "未提取"
    is_blind_bid = _yes_no(profile.get("is_blind_bid"))
    sme_reserved = _yes_no(profile.get("is_sme_reserved"))
    agent_allowed = _metadata_yes_no(profile, "agent_allowed")
    consortium_allowed = _metadata_yes_no(profile, "consortium_allowed")
    business_scoring = [row for row in scoring if "商务" in str(row.get("score_type") or row.get("source_heading") or "")]
    technical_scoring = [row for row in scoring if "技术" in str(row.get("score_type") or row.get("source_heading") or "")]

    lines = [
        f"# {project_name} 投标文件目录建议",
        "",
        "## 生成依据",
        f"- 项目编号：{project_code}",
        f"- 是否暗标：{is_blind_bid}",
        f"- 是否专门面向中小微企业：{sme_reserved}",
        f"- 是否允许代理商投标：{agent_allowed}",
        f"- 是否允许联合体投标：{consortium_allowed}",
        f"- 已识别资格要求：{len(qualification)} 条",
        f"- 已识别废标/否决项：{len(rejection)} 条",
        f"- 已识别商务要求：{len(business)} 条",
        f"- 已识别技术要求：{len(technical)} 条",
        f"- 已识别评分项：{len(scoring)} 条",
        "",
    ]

    if writing_requirements:
        lines.extend(
            [
                "## 招标文件中的编制 / 递交要求线索",
                *_bullet_lines([item["content"] for item in writing_requirements[:8]]),
                "",
            ]
        )

    lines.extend(
        [
            "## 一、投标文件总目录",
            "",
            "### 第一册 商务文件",
            "1. 投标函",
            "2. 开标一览表 / 报价表",
            "3. 法定代表人身份证明",
            "4. 法定代表人授权委托书",
            "5. 投标保证金或保证金承诺材料",
            "6. 资格证明文件",
            "7. 商务条款响应表",
            "8. 商务偏离表",
            "9. 合同条款响应及服务承诺",
            "",
            "### 第二册 技术文件",
            "1. 项目理解与需求分析",
            "2. 总体技术方案",
            "3. 技术要求响应表",
            "4. 项目实施方案",
            "5. 项目进度计划与交付安排",
            "6. 质量保障方案",
            "7. 验收方案",
            "8. 售后服务与运维保障方案",
            "9. 技术偏离表",
            "",
            "### 第三册 评分响应文件",
            "1. 商务评分响应索引表",
            "2. 技术评分响应索引表",
            "3. 评分证明材料索引",
            "",
            "### 第四册 附件材料",
            "1. 企业资质与证照附件",
            "2. 人员证书和履历附件",
            "3. 历史业绩证明附件",
            "4. 财务、纳税、社保及信用证明附件",
            "5. 其他招标文件要求的附件",
            "",
        ]
    )

    lines.extend(_qualification_outline(qualification))
    lines.extend(_business_outline(business))
    lines.extend(_technical_outline(technical, technical_scoring))
    lines.extend(_scoring_outline(business_scoring, technical_scoring))
    lines.extend(_risk_outline(rejection))
    lines.extend(_blind_bid_notes(is_blind_bid))
    return "\n".join(lines).strip() + "\n"


def _qualification_outline(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return []
    lines = ["## 二、资格证明文件建议目录", ""]
    for index, row in enumerate(rows[:30], start=1):
        title = row.get("required_materials") or row.get("requirement_text") or "资格材料"
        lines.append(f"{index}. {_short(title, 80)}")
    lines.append("")
    return lines


def _business_outline(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return []
    grouped = _group_by(rows, "requirement_type")
    lines = ["## 三、商务响应建议目录", ""]
    for group, items in grouped.items():
        lines.append(f"### {group or '其他商务要求'}")
        for index, row in enumerate(items[:10], start=1):
            title = row.get("item_name") or row.get("requirement_text") or "商务响应项"
            lines.append(f"{index}. {_short(title, 70)}")
        lines.append("")
    return lines


def _technical_outline(rows: list[dict[str, Any]], scoring_rows: list[dict[str, Any]]) -> list[str]:
    if not rows and not scoring_rows:
        return []
    grouped = _group_by(rows, "requirement_group")
    lines = ["## 四、技术文件建议目录", ""]
    for group, items in grouped.items():
        lines.append(f"### {group or '技术要求'}")
        for index, row in enumerate(items[:12], start=1):
            title = row.get("item_name") or row.get("parameter_name") or row.get("requirement_text") or "技术响应项"
            lines.append(f"{index}. {_short(title, 70)}")
        lines.append("")
    if scoring_rows:
        lines.append("### 技术评分重点响应章节")
        for index, row in enumerate(scoring_rows[:12], start=1):
            lines.append(f"{index}. {_short(row.get('item_name') or '技术评分项', 70)}")
        lines.append("")
    return lines


def _scoring_outline(business_rows: list[dict[str, Any]], technical_rows: list[dict[str, Any]]) -> list[str]:
    if not business_rows and not technical_rows:
        return []
    lines = ["## 五、评分响应索引建议", ""]
    if business_rows:
        lines.append("### 商务评分响应索引")
        for index, row in enumerate(business_rows[:20], start=1):
            lines.append(f"{index}. {_short(row.get('item_name') or '商务评分项', 70)}：{_short(row.get('score_text') or '', 20)}")
        lines.append("")
    if technical_rows:
        lines.append("### 技术评分响应索引")
        for index, row in enumerate(technical_rows[:20], start=1):
            lines.append(f"{index}. {_short(row.get('item_name') or '技术评分项', 70)}：{_short(row.get('score_text') or '', 20)}")
        lines.append("")
    return lines


def _risk_outline(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return []
    lines = ["## 六、废标 / 否决风险对应目录提醒", ""]
    for index, row in enumerate(rows[:20], start=1):
        item = row.get("rejection_item") or row.get("specific_behavior") or "废标风险项"
        lines.append(f"{index}. {_short(item, 90)}")
    lines.append("")
    return lines


def _blind_bid_notes(is_blind_bid: str) -> list[str]:
    if is_blind_bid != "是":
        return []
    return [
        "## 七、暗标编制特别提醒",
        "",
        "- 技术文件目录和正文应避免出现投标人名称、人员身份、企业标识、过往项目中可识别单位的信息。",
        "- 商务文件与技术文件建议分册管理，暗标部分单独复核。",
        "",
    ]


def _writing_requirement_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pattern = re.compile(
        r"投标文件.*(组成|编制|格式|目录|装订|签署|盖章|密封|递交)|"
        r"(商务文件|技术文件|资格证明文件|响应文件).*(组成|编制|格式|目录|要求)|"
        r"暗标|盲评|技术标.*不得|不得出现.*投标人|目录|偏离表|响应表"
    )
    hits = []
    seen: set[str] = set()
    for chunk in chunks:
        text = " ".join(
            str(chunk.get(key) or "")
            for key in ("title_path", "content", "source_text")
        )
        if not pattern.search(text):
            continue
        content = _short(str(chunk.get("content") or chunk.get("source_text") or ""), 260)
        key = re.sub(r"\s+", "", content)[:120]
        if not key or key in seen:
            continue
        seen.add(key)
        hits.append(
            {
                "chunk_id": chunk.get("id"),
                "title_path": chunk.get("title_path"),
                "content": content,
            }
        )
        if len(hits) >= 12:
            break
    return hits


def _rows(tables: dict[str, Any], table_name: str) -> list[dict[str, Any]]:
    table = tables.get(table_name) or {}
    rows = table.get("rows") or []
    return rows if isinstance(rows, list) else []


def _first_row(tables: dict[str, Any], table_name: str) -> dict[str, Any]:
    rows = _rows(tables, table_name)
    return rows[0] if rows else {}


def _group_by(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        group = str(row.get(key) or "其他").strip() or "其他"
        output.setdefault(group, []).append(row)
    return output


def _bullet_lines(values: list[str]) -> list[str]:
    return [f"- {_short(value, 220)}" for value in values if str(value).strip()]


def _short(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else f"{text[:limit]}..."


def _yes_no(value: Any) -> str:
    if value in {1, "1", True, "true", "True", "是"}:
        return "是"
    if value in {0, "0", False, "false", "False", "否"}:
        return "否"
    return "未提取"


def _metadata_yes_no(profile: dict[str, Any], key: str) -> str:
    # Reserved for future normalized metadata fields; unknown values default to 未提取.
    return _yes_no(profile.get(key))
