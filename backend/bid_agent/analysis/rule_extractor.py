# -*- coding: utf-8 -*-
"""Lightweight rule-based project profile and section tree extraction."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Iterable

from bid_agent.parsing.document_parser import BidDocumentSection


PROFILE_FIELDS = {
    "project_name": "项目名称",
    "project_code": "项目编号",
    "project_category": "项目类别（服务类，货物类，工程类）和服务年限",
    "buyer_name": "采购人",
    "agency_name": "招标代理机构",
    "budget_text": "项目规模和预算",
    "open_time": "开标时间",
    "bid_deadline": "投标文件提交截止时间",
    "registration_time": "网上报名时间安排",
    "procurement_method": "采购方式",
    "package_no": "包号",
    "project_domain": "项目所属领域",
    "implementation_scope": "项目要实施的具体内容",
    "technical_features": "主要技术特点",
    "other_key_requirements": "其他关键要求",
}


FIELD_PATTERNS = {
    "project_name": [
        r"(?:项目名称|采购项目名称|招标项目名称)\s*[：:]\s*([^\n\r|]{3,120})",
        r"(?:项目概况|项目基本情况)[^\n\r]{0,80}(?:项目名称|采购项目名称)\s*[：:]\s*([^\n\r|]{3,120})",
    ],
    "project_code": [
        r"(?:项目编号|采购编号|招标编号|招标项目编号|项目代码)\s*[：:]\s*([^\n\r|]{2,80})",
        r"(?:项目编号|采购编号|招标编号|招标项目编号|项目代码)\s*[：:]\s*([A-Za-z0-9_\-./（）()]+)",
    ],
    "project_category": [
        r"(?:采购品目|项目类别|采购类型|标的类型)\s*[：:]\s*([^\n\r|]{2,80})",
        r"((?:服务类|货物类|工程类)[^\n\r。；;]{0,80}(?:年|月|日|服务期|履约期限)?)",
    ],
    "buyer_name": [
        r"(?:采购人|招标人|建设单位)\s*[：:]\s*([^\n\r|]{2,80})",
    ],
    "agency_name": [
        r"(?:采购代理机构|招标代理机构|代理机构)\s*[：:]\s*([^\n\r|]{2,100})",
    ],
    "budget_text": [
        r"((?:预算金额|采购预算|项目预算|最高限价|最高投标限价|控制价|拦标价)[^\n\r。；;]{0,120}(?:元|万元|亿元))",
    ],
    "open_time": [
        r"((?:开标时间|开标日期)[^\n\r。；;]{0,80})",
    ],
    "bid_deadline": [
        r"((?:投标截止时间|提交投标文件截止时间|投标文件提交截止时间|响应文件提交截止时间)[^\n\r。；;]{0,100})",
    ],
    "registration_time": [
        r"((?:报名时间|获取招标文件时间|获取采购文件时间|发售时间)[^\n\r。；;]{0,120})",
    ],
    "procurement_method": [
        r"(?:采购方式|招标方式)\s*[：:]\s*([^\n\r|]{2,40})",
    ],
    "package_no": [
        r"(?:包号|标包|采购包)\s*[：:]\s*([^\n\r|]{1,40})",
        r"(?:第|包)\s*([A-Za-z0-9一二三四五六七八九十]+)\s*包",
    ],
    "project_domain": [
        r"(?:所属行业|所属领域|行业领域|采购领域)\s*[：:]\s*([^\n\r|]{2,80})",
    ],
}

TIME_PATTERNS = (
    r"((?:网上报名|报名时间|报名截止|获取招标文件|获取采购文件|发售时间|文件获取)[^\n\r。；;]{0,160})",
    r"((?:澄清|答疑|提问|质疑)[^\n\r。；;]{0,160}(?:时间|截止|前))",
    r"((?:投标保证金|保证金)[^\n\r。；;]{0,160}(?:时间|截止|到账|缴纳))",
    r"((?:投标截止时间|提交投标文件截止时间|投标文件提交截止时间|响应文件提交截止时间)[^\n\r。；;]{0,160})",
    r"((?:开标时间|开标日期|开启时间|响应文件开启时间)[^\n\r。；;]{0,160})",
    r"((?:服务期限|服务期|履约期限|合同履行期限|交付时间|完成时间|工期)[^\n\r。；;]{0,160})",
)

IMPLEMENTATION_KEYWORDS = (
    "采购需求",
    "服务内容",
    "建设内容",
    "项目内容",
    "工作内容",
    "实施内容",
    "采购内容",
    "招标范围",
)

TECHNICAL_KEYWORDS = (
    "技术要求",
    "技术参数",
    "技术标准",
    "功能要求",
    "性能指标",
    "服务要求",
    "验收标准",
)

OTHER_KEYWORDS = (
    "投标人须知",
    "实质性要求",
    "响应要求",
    "关键要求",
    "特别要求",
    "重要提示",
)


TITLE_RE = re.compile(
    r"^\s*((?:第[一二三四五六七八九十百千万\d]+章|第\d+章|[一二三四五六七八九十]+[、.．]|"
    r"\d+(?:[.．]\d+){0,4}|[（(][一二三四五六七八九十\d]+[）)])\s*[^\n\r]{2,80})\s*$"
)


def build_rule_global_context(sections: Iterable[BidDocumentSection]) -> str:
    payload = extract_rule_global_context(sections)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def extract_rule_global_context(sections: Iterable[BidDocumentSection]) -> dict[str, Any]:
    section_list = list(sections or [])
    profile = extract_rule_project_profile(section_list)
    tree = extract_rule_section_tree(section_list)
    return {
        "project_profile": profile,
        "section_tree": tree,
        "extraction_meta": {
            "method": "rule_regex_first_pass",
            "profile_completeness": profile_completeness(profile),
            "section_count": len(tree),
            "needs_llm_completion": needs_llm_global_completion(profile, tree),
        },
    }


def extract_rule_project_profile(sections: list[BidDocumentSection]) -> dict[str, Any]:
    preface = "\n".join(
        str(getattr(section, "markdown", "") or getattr(section, "content", ""))
        for section in sections[:10]
    )
    full_text = "\n".join(
        str(getattr(section, "markdown", "") or getattr(section, "content", ""))
        for section in sections
    )
    profile: dict[str, Any] = {}
    for key, patterns in FIELD_PATTERNS.items():
        value = _first_match(preface, patterns)
        profile[PROFILE_FIELDS[key]] = value

    profile["项目类别（服务类，货物类，工程类）和服务年限"] = (
        profile.get("项目类别（服务类，货物类，工程类）和服务年限")
        or _infer_project_category_and_period(full_text)
        or "未提及"
    )
    profile["项目所属领域"] = (
        profile.get("项目所属领域")
        or _infer_project_domain(full_text)
        or "未提及"
    )
    profile["各种时间安排"] = _collect_time_arrangements(full_text) or "未提及"
    profile["项目要实施的具体内容"] = _extract_keyword_snippet(full_text, IMPLEMENTATION_KEYWORDS) or "未提及"
    profile["主要技术特点"] = _extract_keyword_snippet(full_text, TECHNICAL_KEYWORDS) or "未提及"
    profile["其他关键要求"] = _extract_keyword_snippet(full_text, OTHER_KEYWORDS) or "未提及"

    profile["是否专门面向中小微企业采购"] = _yes_no_from_text(full_text, ("专门面向中小企业", "专门面向中小微企业"))
    profile["是否为暗标"] = _yes_no_from_text(full_text, ("暗标", "匿名评审"))
    profile["是否允许代理商投标"] = _yes_no_from_text(full_text, ("代理商", "经销商"))
    profile["是否允许联合体投标"] = _yes_no_from_text(full_text, ("联合体投标", "接受联合体"))

    for label in (
        "项目名称",
        "项目编号",
        "包号",
        "项目规模和预算",
        "采购人",
        "招标代理机构",
        "采购方式",
    ):
        if not str(profile.get(label) or "").strip():
            profile[label] = "未提及"
    return profile


def extract_rule_section_tree(sections: list[BidDocumentSection]) -> list[dict[str, Any]]:
    tree = []
    for index, section in enumerate(sections, start=1):
        title = str(getattr(section, "title", "") or "").strip()
        metadata = getattr(section, "metadata", {}) or {}
        level = int(getattr(section, "level", 1) or _guess_title_level(title))
        if not title:
            continue
        tree.append(
            {
                "section_id": f"S{index}",
                "title": title,
                "level": level,
                "title_path": _title_path(metadata, title),
                "page_start": metadata.get("page_start") or metadata.get("page") or None,
                "page_end": metadata.get("page_end") or None,
                "module_hint": _module_hint(title),
                "rule_confidence": 0.9 if TITLE_RE.match(title) else 0.65,
            }
        )
    return tree


def profile_completeness(profile: dict[str, Any]) -> float:
    important = ["项目名称", "项目编号", "采购人", "招标代理机构", "项目规模和预算", "开标时间"]
    hit = sum(1 for key in important if _is_meaningful(profile.get(key)))
    return hit / len(important)


def needs_llm_global_completion(profile: dict[str, Any], section_tree: list[dict[str, Any]]) -> bool:
    if os.getenv("BID_PROJECT_OVERVIEW_RULE_FIRST", "true").lower() in {"1", "true", "yes", "on"}:
        return profile_completeness(profile) < 0.34 and len(section_tree) < 2
    return profile_completeness(profile) < 0.67 or len(section_tree) < 3


def rule_project_overview_markdown(global_context: str) -> str:
    try:
        payload = json.loads(global_context or "{}")
    except Exception:
        payload = {}
    profile = payload.get("project_profile") if isinstance(payload, dict) else {}
    if not isinstance(profile, dict):
        profile = {}
    rows = [
        ("项目名称", profile.get("项目名称")),
        ("项目编号", profile.get("项目编号")),
        ("项目类别（服务类，货物类，工程类）和服务年限", profile.get("项目类别（服务类，货物类，工程类）和服务年限")),
        ("包号", profile.get("包号")),
        ("项目规模和预算", profile.get("项目规模和预算")),
        ("招标人", profile.get("采购人")),
        ("招标代理机构", profile.get("招标代理机构")),
        ("项目所属领域", profile.get("项目所属领域")),
        ("各种时间安排", profile.get("各种时间安排")),
        ("项目要实施的具体内容", profile.get("项目要实施的具体内容")),
        ("主要技术特点", profile.get("主要技术特点")),
        ("其他关键要求", profile.get("其他关键要求")),
        ("是否专门面向中小微企业采购", profile.get("是否专门面向中小微企业采购") or "否"),
        ("是否为暗标", profile.get("是否为暗标") or "否"),
        ("是否允许代理商投标", profile.get("是否允许代理商投标") or "否"),
        ("是否允许联合体投标", profile.get("是否允许联合体投标") or "否"),
    ]
    return "\n".join(f"{key}：{value or '未提及'}" for key, value in rows)


def _first_match(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text or "", flags=re.IGNORECASE)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip(" ：:|")
    return ""


def _is_meaningful(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text and text not in {"未提及", "未提取", "无", "否"})


def _collect_time_arrangements(text: str, max_items: int = 12) -> str:
    hits: list[str] = []
    seen = set()
    for pattern in TIME_PATTERNS:
        for match in re.finditer(pattern, text or "", flags=re.IGNORECASE):
            value = re.sub(r"\s+", " ", match.group(1)).strip(" ：:|")
            if len(value) < 6:
                continue
            key = value[:80]
            if key in seen:
                continue
            seen.add(key)
            hits.append(value)
            if len(hits) >= max_items:
                return "\n".join(f"- {item}" for item in hits)
    return "\n".join(f"- {item}" for item in hits)


def _extract_keyword_snippet(text: str, keywords: tuple[str, ...], max_chars: int = 360) -> str:
    value = str(text or "")
    best_index = -1
    for keyword in keywords:
        index = value.find(keyword)
        if index >= 0 and (best_index < 0 or index < best_index):
            best_index = index
    if best_index < 0:
        return ""
    snippet = value[best_index : best_index + max_chars]
    lines = [re.sub(r"\s+", " ", line).strip(" ：:|") for line in snippet.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ""
    return "\n".join(lines[:4])


def _infer_project_category_and_period(text: str) -> str:
    value = str(text or "")
    category = ""
    if re.search(r"服务类|服务采购|服务项目|服务内容|服务要求", value):
        category = "服务类"
    elif re.search(r"货物类|货物采购|设备采购|产品采购", value):
        category = "货物类"
    elif re.search(r"工程类|工程采购|施工|建设工程", value):
        category = "工程类"
    period = _first_match(
        value,
        [
            r"((?:服务期限|服务期|履约期限|合同履行期限|交付期限|工期)[^\n\r。；;]{0,100})",
        ],
    )
    if category and period:
        return f"{category}；{period}"
    return category or period


def _infer_project_domain(text: str) -> str:
    value = str(text or "")
    domain_keywords = (
        "信息化",
        "软件",
        "系统",
        "数据",
        "人工智能",
        "网络安全",
        "运维",
        "物业",
        "咨询",
        "工程",
        "设备",
        "医疗",
        "教育",
        "政务",
        "海关",
    )
    hits = [keyword for keyword in domain_keywords if keyword in value]
    return "、".join(hits[:4])


def _yes_no_from_text(text: str, positive_keywords: tuple[str, ...]) -> str:
    value = str(text or "")
    if any(keyword in value for keyword in positive_keywords):
        window = value[max(0, min(value.find(k) for k in positive_keywords if k in value) - 12) :]
        if re.search(r"不接受|不允许|不得|否", window[:60]):
            return "否"
        return "是"
    return "否"


def _guess_title_level(title: str) -> int:
    value = str(title or "")
    if re.match(r"^\s*第[一二三四五六七八九十百千万\d]+章", value):
        return 1
    if re.match(r"^\s*\d+[.．]\d+", value):
        return 2
    if re.match(r"^\s*[一二三四五六七八九十]+[、.．]", value):
        return 2
    return 3


def _title_path(metadata: dict[str, Any], fallback: str) -> str:
    path = metadata.get("title_path")
    if isinstance(path, list):
        return " > ".join(str(item).strip() for item in path if str(item).strip()) or fallback
    if isinstance(path, str) and path.strip():
        return path.strip()
    return fallback


def _module_hint(title: str) -> str:
    value = str(title or "")
    if re.search(r"投标人须知|招标公告|项目概况|采购需求", value):
        return "project_overview"
    if re.search(r"商务|合同|付款|交付|验收|保证金|售后", value):
        return "business_content"
    if re.search(r"技术|服务要求|实施方案|参数", value):
        return "technical_requirements"
    if re.search(r"资格|符合性|废标|否决", value):
        return "qualification_compliance"
    if re.search(r"评分|评审|评标办法|综合评分", value):
        return "scoring"
    return "other"
