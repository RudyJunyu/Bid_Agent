# -*- coding: utf-8 -*-
"""Regex-based review agent for extracted bid document modules."""

import re
from typing import Any, Iterable


MODULES: dict[str, dict[str, Any]] = {
    "project_overview": {
        "label": "投标人须知",
        "checks": [
            ("项目名称", [r"项目名称"], [r"项目名称"], "high"),
            ("项目编号", [r"项目编号|招标编号|采购编号"], [r"项目编号|招标编号|采购编号"], "high"),
            ("项目类别/领域", [r"项目类别|服务类|货物类|工程类|所属领域"], [r"项目类别|采购类别|所属领域|服务类|货物类|工程类"], "medium"),
            ("包号/标包", [r"包号|标包|包件"], [r"包号|标包|包件"], "medium"),
            ("预算/最高限价", [r"预算|最高限价|控制价|限价"], [r"预算|最高限价|控制价|限价"], "high"),
            ("招标人/采购人", [r"招标人|采购人|采购单位"], [r"招标人|采购人|采购单位"], "high"),
            ("代理机构", [r"代理机构|招标代理|采购代理"], [r"代理机构|招标代理|采购代理"], "medium"),
            ("时间安排", [r"投标截止|开标|报名|获取.*文件|递交截止|澄清|答疑"], [r"投标截止|开标|报名|获取.*文件|递交截止|澄清|答疑"], "high"),
            ("中小企业", [r"中小企业|小微企业|专门面向"], [r"中小企业|小微企业|专门面向"], "medium"),
            ("暗标", [r"暗标|盲评|匿名评审"], [r"暗标|盲评|匿名评审"], "medium"),
        ],
    },
    "business_content": {
        "label": "商务内容",
        "checks": [
            ("报价要求", [r"报价|投标报价|分项报价|报价表"], [r"报价|投标报价|分项报价|报价表"], "high"),
            ("合同条款", [r"合同|合同签订|合同条款"], [r"合同|合同签订|合同条款"], "medium"),
            ("付款/支付", [r"付款|支付|结算"], [r"付款|支付|结算"], "high"),
            ("履行期限/地点", [r"履行期限|履行地点|服务期限|服务地点"], [r"履行期限|履行地点|服务期限|服务地点"], "medium"),
            ("交付/服务", [r"交付|交货|服务要求|售后|质保|维保"], [r"交付|交货|服务要求|售后|质保|维保"], "medium"),
            ("验收", [r"验收|验收标准|验收方式"], [r"验收|验收标准|验收方式"], "medium"),
            ("保证金", [r"保证金|投标保证金|履约保证金"], [r"保证金|投标保证金|履约保证金"], "medium"),
            ("联合体/分包", [r"联合体|分包|转包"], [r"联合体|分包|转包"], "medium"),
        ],
    },
    "technical_scoring_requirements": {
        "label": "技术要求",
        "checks": [
            ("技术要求/参数", [r"技术要求|技术参数|技术规格|技术标准"], [r"技术要求|技术参数|技术规格|技术标准"], "high"),
            ("采购/服务需求", [r"采购需求|服务需求|建设需求|功能需求"], [r"采购需求|服务需求|建设需求|功能需求"], "high"),
            ("实施/服务方案", [r"实施方案|服务方案|技术方案|项目方案"], [r"实施方案|服务方案|技术方案|项目方案"], "medium"),
            ("验收/质量", [r"验收|质量|质量保障|质量保证"], [r"验收|质量|质量保障|质量保证"], "medium"),
            ("进度/安全/保密", [r"进度|安全|保密|应急|运维"], [r"进度|安全|保密|应急|运维"], "medium"),
            ("图表/图片说明", [r"图表|流程图|架构图|图片|附图|表格"], [r"图表|流程图|架构图|图片|附图|表格"], "low"),
        ],
    },
    "qualification_compliance_requirements": {
        "label": "资格审查",
        "checks": [
            ("资格性审查", [r"资格性审查|资格审查|资格要求|资格条件"], [r"资格性审查|资格审查|资格要求|资格条件"], "high"),
            ("符合性审查", [r"符合性审查|响应性审查|符合性评审"], [r"符合性审查|响应性审查|符合性评审"], "high"),
            ("废标/否决项", [r"废标|无效投标|否决投标|投标无效|响应无效"], [r"废标|无效投标|否决投标|投标无效|响应无效"], "high"),
            ("证明材料", [r"证明材料|需提供|提供资料|承诺函|声明函"], [r"证明材料|需提供|提供资料|承诺函|声明函"], "medium"),
            ("资质/许可", [r"资质|许可证|营业执照|信用中国|政府采购"], [r"资质|许可证|营业执照|信用中国|政府采购"], "medium"),
        ],
    },
    "price_scoring_requirements": {
        "label": "评分要求",
        "checks": [
            ("评分办法", [r"评分办法|评分标准|评审办法|评审标准"], [r"评分办法|评分标准|评审办法|评审标准"], "high"),
            ("商务评分", [r"商务评分|商务分|商务评审|资信评分|企业实力|业绩"], [r"商务评分|商务分|商务评审|资信评分|企业实力|业绩"], "high"),
            ("技术评分", [r"技术评分|技术分|技术评审|技术部分|服务方案"], [r"技术评分|技术分|技术评审|技术部分|服务方案"], "high"),
            ("分值/权重", [r"分值|得分|满分|权重|分数"], [r"分值|得分|满分|权重|分数"], "high"),
            ("扣分/不得分", [r"扣分|不得分|不予计分|0分"], [r"扣分|不得分|不予计分|0分"], "medium"),
        ],
    },
}


EMPTY_MARKERS = {"", "未提及", "未明确", "暂无结果", "无", "none", "null"}
GENERIC_CELLS = {"项目", "内容", "序号", "评分项", "评分标准", "分数", "资格要求", "需提供资料", "未提及", "未明确"}


def build_content_review(
    sections: Iterable[Any],
    extracted: dict[str, Any],
) -> dict[str, Any]:
    """Compare extracted modules with parsed source text using regex rules."""
    source_text = _sections_to_text(sections)
    module_reports = []
    weighted_score_sum = 0.0
    weight_sum = 0.0

    for field, config in MODULES.items():
        extracted_text = str(extracted.get(field) or "").strip()
        report = _review_module(
            field=field,
            label=str(config["label"]),
            extracted_text=extracted_text,
            source_text=source_text,
            checks=list(config["checks"]),
        )
        module_reports.append(report)
        weighted_score_sum += report["score"] * report["weight"]
        weight_sum += report["weight"]

    score = round(weighted_score_sum / weight_sum) if weight_sum else 0
    level = _score_level(score)
    markdown = format_content_review_markdown(
        score=score,
        level=level,
        module_reports=module_reports,
    )
    total_checks = sum(report["total_checks"] for report in module_reports)
    passed_checks = sum(report["passed_checks"] for report in module_reports)
    return {
        "score": score,
        "level": level,
        "total_checks": total_checks,
        "passed_checks": passed_checks,
        "modules": module_reports,
        "markdown": markdown,
    }


def format_content_review_markdown(
    score: int,
    level: str,
    module_reports: list[dict[str, Any]],
) -> str:
    lines = [
        "# 内容审查报告",
        "",
        f"- 审查结论：{level}",
        f"- 规则得分：{score}/100",
        "- 审查方式：正则匹配 + 宽关键词召回 + 原文证据片段 + 提取结果溯源",
        "",
        "## 总览",
        "",
        "| 模块 | 得分 | 覆盖情况 | 提取溯源 | 风险等级 | 主要风险 |",
        "| --- | ---: | --- | --- | --- | --- |",
    ]
    for report in module_reports:
        lines.append(
            "| {label} | {score} | {coverage} | {grounding} | {risk_level} | {risk} |".format(
                label=_md(report["label"]),
                score=report["score"],
                coverage=_md(report["coverage_text"]),
                grounding=_md(report["grounding_text"]),
                risk_level=_md(report["risk_level"]),
                risk=_md(report["risk_text"]),
            )
        )

    lines.extend(["", "## 模块明细"])
    for report in module_reports:
        lines.extend(
            [
                "",
                f"### {report['label']}",
                "",
                f"- 模块得分：{report['score']}/100",
                f"- 覆盖情况：{report['coverage_text']}",
                f"- 提取溯源：{report['grounding_text']}",
                f"- 风险等级：{report['risk_level']}",
                f"- 风险提示：{report['risk_text']}",
                "",
                "| 检查项 | 原文是否存在 | 提取是否覆盖 | 状态 | 证据片段 |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for item in report["checks"]:
            lines.append(
                "| {name} | {source} | {output} | {status} | {evidence} |".format(
                    name=_md(item["name"]),
                    source="是" if item["source_hit"] else "否",
                    output="是" if item["output_hit"] else "否",
                    status=_md(item["status"]),
                    evidence=_md("；".join(item["evidence"]) or "未命中"),
                )
            )
        if report["missing_keywords"]:
            lines.append("")
            lines.append(f"- 重点缺失：{'、'.join(report['missing_keywords'])}")
        if report["unverified_keywords"]:
            lines.append(f"- 需人工核对：{'、'.join(report['unverified_keywords'])}")
    return "\n".join(lines).strip()


def _review_module(
    field: str,
    label: str,
    extracted_text: str,
    source_text: str,
    checks: list[tuple[str, list[str], list[str], str]],
) -> dict[str, Any]:
    normalized_output = _normalize_text(extracted_text)
    is_empty = normalized_output.lower() in EMPTY_MARKERS or len(normalized_output) < 12

    check_reports = []
    source_available = 0
    passed_checks = 0
    high_risks = 0
    medium_risks = 0
    missing_keywords = []
    unverified_keywords = []

    for name, output_patterns, source_patterns, severity in checks:
        source_hit = _any_pattern(source_patterns, source_text)
        output_hit = _any_pattern(output_patterns, extracted_text)
        evidence = _evidence_snippets(source_text, source_patterns)

        if source_hit:
            source_available += 1

        if source_hit and output_hit:
            status = "通过"
            passed_checks += 1
        elif source_hit and not output_hit:
            status = "原文存在但提取缺失"
            missing_keywords.append(name)
            if severity == "high":
                high_risks += 1
            elif severity == "medium":
                medium_risks += 1
        elif output_hit and not source_hit:
            status = "提取有内容但原文未直接命中"
            unverified_keywords.append(name)
            if severity == "high":
                medium_risks += 1
        else:
            status = "原文未直接命中"

        check_reports.append(
            {
                "name": name,
                "severity": severity,
                "source_hit": source_hit,
                "output_hit": output_hit,
                "status": status,
                "evidence": evidence,
            }
        )

    coverage_ratio = passed_checks / max(1, source_available or len(checks))
    grounding_ratio, grounded_terms, ungrounded_terms = _grounding_ratio(extracted_text, source_text)
    if ungrounded_terms:
        unverified_keywords.extend(ungrounded_terms[:5])

    score = round(
        55 * coverage_ratio
        + 30 * grounding_ratio
        + 15 * (0 if is_empty else 1)
    )
    if high_risks:
        score = max(0, score - 12 * high_risks)
    if medium_risks:
        score = max(0, score - 6 * medium_risks)
    score = max(0, min(100, score))

    risks = []
    if is_empty:
        risks.append("模块输出为空或过短")
    if high_risks:
        risks.append(f"{high_risks} 个高风险关键项缺失")
    if medium_risks:
        risks.append(f"{medium_risks} 个中风险关键项缺失")
    if grounding_ratio < 0.45 and grounded_terms + len(ungrounded_terms) >= 3:
        risks.append("提取内容原文溯源不足")
    if not source_available:
        risks.append("原文未召回相关章节，需确认解析质量")

    return {
        "field": field,
        "label": label,
        "score": score,
        "weight": 1.2 if field in {"qualification_compliance_requirements", "price_scoring_requirements"} else 1.0,
        "coverage_ratio": coverage_ratio,
        "grounding_ratio": grounding_ratio,
        "coverage_text": f"{passed_checks}/{source_available or len(checks)}",
        "grounding_text": f"{grounded_terms}/{grounded_terms + len(ungrounded_terms)}" if grounded_terms or ungrounded_terms else "无可比对短语",
        "risk_level": _score_level(score),
        "risk_text": "；".join(risks) if risks else "未发现明显风险",
        "missing_keywords": missing_keywords,
        "unverified_keywords": _dedupe(unverified_keywords),
        "checks": check_reports,
        "passed_checks": passed_checks,
        "total_checks": len(checks),
    }


def _sections_to_text(sections: Iterable[Any]) -> str:
    chunks = []
    for section in sections or []:
        if isinstance(section, dict):
            title = str(section.get("title") or "")
            chunks.append(f"{title}\n{section.get('markdown') or section.get('content') or ''}")
        else:
            title = str(getattr(section, "title", "") or "")
            chunks.append(
                f"{title}\n{getattr(section, 'markdown', '') or getattr(section, 'content', '') or ''}"
            )
    return "\n\n".join(chunk for chunk in chunks if chunk.strip()).strip()


def _any_pattern(patterns: list[str], text: str) -> bool:
    return any(re.search(pattern, text or "", flags=re.IGNORECASE) for pattern in patterns)


def _evidence_snippets(source_text: str, patterns: list[str], window: int = 46) -> list[str]:
    snippets = []
    for pattern in patterns:
        match = re.search(pattern, source_text or "", flags=re.IGNORECASE)
        if not match:
            continue
        start = max(0, match.start() - window)
        end = min(len(source_text), match.end() + window)
        snippet = re.sub(r"\s+", " ", source_text[start:end]).strip()
        snippets.append(("..." if start else "") + snippet + ("..." if end < len(source_text) else ""))
        if len(snippets) >= 2:
            break
    return snippets


def _grounding_ratio(extracted_text: str, source_text: str) -> tuple[float, int, list[str]]:
    terms = _extract_grounding_terms(extracted_text)
    if not terms:
        return 1.0, 0, []
    normalized_source = _normalize_text(source_text)
    grounded = 0
    ungrounded = []
    for term in terms:
        if _term_in_source(term, normalized_source):
            grounded += 1
        else:
            ungrounded.append(term)
    return grounded / max(1, len(terms)), grounded, ungrounded


def _extract_grounding_terms(text: str, max_terms: int = 24) -> list[str]:
    terms = []
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            if re.match(r"^\|?\s*:?-{3,}:?", stripped):
                continue
            cells = [cell.strip() for cell in stripped.split("|")[1:-1]]
            for cell in cells:
                _append_term(terms, cell)
        else:
            match = re.match(r"^[#*\-\d.、\s]*([^：:]{2,40})[：:]\s*(.+)$", stripped)
            if match:
                _append_term(terms, match.group(2))
    return terms[:max_terms]


def _append_term(terms: list[str], value: str) -> None:
    cleaned = re.sub(r"\s+", "", value or "")
    cleaned = re.sub(r"^[：:，,。；;\-\s]+|[：:，,。；;\-\s]+$", "", cleaned)
    if len(cleaned) < 4 or len(cleaned) > 90:
        return
    if cleaned in GENERIC_CELLS or cleaned.lower() in EMPTY_MARKERS:
        return
    if cleaned not in terms:
        terms.append(cleaned)


def _term_in_source(term: str, normalized_source: str) -> bool:
    normalized_term = _normalize_text(term)
    if not normalized_term:
        return True
    if normalized_term in normalized_source:
        return True
    if len(normalized_term) < 12:
        return False
    chunks = [normalized_term[index : index + 10] for index in range(0, len(normalized_term), 10)]
    meaningful = [chunk for chunk in chunks if len(chunk) >= 6]
    if not meaningful:
        return False
    hits = sum(1 for chunk in meaningful if chunk in normalized_source)
    return hits >= max(1, round(len(meaningful) * 0.45))


def _normalize_text(text: str) -> str:
    return re.sub(r"[\s|`*_#>\-—，,。；;：:（）()\[\]【】]+", "", text or "")


def _score_level(score: int) -> str:
    if score >= 85:
        return "较好"
    if score >= 70:
        return "基本可用"
    if score >= 55:
        return "需核对"
    return "风险较高"


def _md(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", "<br>")


def _dedupe(items: list[str]) -> list[str]:
    output = []
    for item in items:
        if item and item not in output:
            output.append(item)
    return output
