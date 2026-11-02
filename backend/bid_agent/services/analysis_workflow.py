"""Extracted from the original API; public request contracts are retained."""
import json
import os
import traceback
from typing import List, Optional
from fastapi import HTTPException
from bid_agent.analysis.prompts import build_business_content_messages_from_sections, build_business_scoring_messages_from_sections, build_global_context_messages_from_sections, build_project_overview_text_from_global_context, build_project_overview_messages_from_sections, build_qualification_compliance_messages_from_sections, build_technical_scoring_messages_from_sections
from bid_agent.analysis.service import BidAnalysisResult
from bid_agent.parsing.document_parser import BidDocumentSection
from bid_agent.analysis.qualification_prefilter import merge_qualification_prefilter_sections, prefilter_qualification_sections, prefilter_qualification_sections_sync, qualification_prefilter_enabled
from bid_agent.rag.section_retriever import retrieve_sections_for_analysis
from bid_agent.analysis.rule_extractor import build_rule_global_context, needs_llm_global_completion, rule_project_overview_markdown
from bid_agent.analysis.structured_extraction import build_structured_messages, parse_structured_json, schema_for_field, structured_output_enabled, structured_to_markdown
from bid_agent.infrastructure.database import save_analysis_result
from bid_agent.analysis.cleaner import clean_repeated_extraction_text
from bid_agent.infrastructure.llm_client import LLM_Invoke
from bid_agent.core.model_config import resolve_llm_selection, resolve_llm_base_url

def _raise_api_error(exc: Exception) -> None:
    if isinstance(exc, HTTPException):
        raise exc
    error_type, message, hint = _classify_exception(exc)
    raise HTTPException(
        status_code=500,
        detail={
            "type": error_type,
            "message": message,
            "hint": hint,
        },
    ) from exc


def _classify_exception(exc: Exception, stage: str = "") -> tuple[str, str, str]:
    message = str(exc) or exc.__class__.__name__
    lowered = message.lower()
    if "mineru" in lowered:
        error_type = "MinerU 解析失败"
    elif "llm" in lowered or "openai" in lowered or "model" in lowered:
        error_type = "大模型调用失败"
    elif "timeout" in lowered or "timed out" in lowered:
        error_type = "请求超时"
    elif "connection" in lowered or "network" in lowered or "fetch" in lowered:
        error_type = "网络连接失败"
    elif "errno 22" in lowered or "invalid argument" in lowered:
        error_type = "大模型运行环境异常"
    else:
        error_type = "后端处理失败"
    if stage:
        error_type = f"{stage}：{error_type}"
    hint = (
        "如果是 MinerU 或大模型调用失败，优先检查网络、代理、API Key、模型名称和超时时间。"
        "如果是本地解析方式失败，检查文件格式和依赖包是否安装。"
    )
    return error_type, message, hint


def _stream_event(event_type: str, **payload: object) -> str:
    return json.dumps({"type": event_type, **payload}, ensure_ascii=False) + "\n"


def _exception_traceback_tail(exc: Exception, limit: int = 8) -> str:
    lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
    return "".join(lines[-limit:]).strip()


def _build_analysis_jobs(
    sections: List[BidDocumentSection],
    global_context: str = "",
    include_project_overview: bool = False,
    qualification_prefilter_sections: Optional[List[BidDocumentSection]] = None,
) -> list[tuple[str, str, list]]:
    retrieved_sections = retrieve_sections_for_analysis(sections)
    if qualification_prefilter_sections:
        retrieved_sections["qualification_compliance"] = merge_qualification_prefilter_sections(
            retrieved_sections["qualification_compliance"],
            qualification_prefilter_sections,
        )
    jobs: list[tuple[str, str, list]] = []
    if include_project_overview:
        jobs.append(
            (
                "project_overview",
                "项目概述",
                build_project_overview_messages_from_sections(retrieved_sections["project_overview"]),
            )
        )
    jobs.extend(
        [
            (
                "business_content",
                "商务内容",
                build_business_content_messages_from_sections(
                    retrieved_sections["business_content"],
                    global_context=global_context,
                ),
            ),
            (
                "technical_scoring_requirements",
                "技术要求",
                build_technical_scoring_messages_from_sections(
                    retrieved_sections["technical_requirements"],
                    global_context=global_context,
                ),
            ),
            (
                "qualification_compliance_requirements",
                "资格和符合性审查",
                build_qualification_compliance_messages_from_sections(
                    retrieved_sections["qualification_compliance"],
                    global_context=global_context,
                ),
            ),
            (
                "price_scoring_requirements",
                "评分要求",
                build_business_scoring_messages_from_sections(
                    retrieved_sections["scoring"],
                    global_context=global_context,
                ),
            ),
        ]
    )
    return jobs


MODULE_FALLBACK_CONFIG = {
    "business_content": {
        "retrieval_key": "business_content",
        "title": "商务内容",
        "empty": "未从候选章节中召回到明确商务内容。",
    },
    "technical_scoring_requirements": {
        "retrieval_key": "technical_requirements",
        "title": "技术要求",
        "empty": "未从候选章节中召回到明确技术要求。",
    },
    "qualification_compliance_requirements": {
        "retrieval_key": "qualification_compliance",
        "title": "资格审查与废标项",
        "empty": "未从候选章节中召回到明确资格审查、符合性审查或废标项。",
    },
    "price_scoring_requirements": {
        "retrieval_key": "scoring",
        "title": "评分要求",
        "empty": "未从候选章节中召回到明确评分要求。",
    },
}


def _apply_local_module_fallbacks(
    results: dict,
    sections: List[BidDocumentSection],
    qualification_prefilter_sections: Optional[List[BidDocumentSection]] = None,
) -> dict:
    """Fill empty module outputs with local retrieved snippets so the UI is never blank."""
    retrieved_sections = retrieve_sections_for_analysis(sections)
    if qualification_prefilter_sections:
        retrieved_sections["qualification_compliance"] = merge_qualification_prefilter_sections(
            retrieved_sections["qualification_compliance"],
            qualification_prefilter_sections,
        )
    for field, config in MODULE_FALLBACK_CONFIG.items():
        value = str(results.get(field) or "").strip()
        if value and "提取失败" not in value[:80]:
            continue
        module_sections = retrieved_sections.get(config["retrieval_key"], [])
        results[field] = _format_local_module_fallback(
            field=field,
            title=config["title"],
            sections=module_sections,
            empty_message=config["empty"],
        )
    return results


def _format_local_module_fallback(
    field: str,
    title: str,
    sections: List[BidDocumentSection],
    empty_message: str,
    max_sections: int = 6,
    max_chars_per_section: int = 1200,
) -> str:
    snippets = []
    for section in sections[:max_sections]:
        section_title = str(getattr(section, "title", "") or "候选片段").strip()
        text = str(
            getattr(section, "markdown", "")
            or getattr(section, "content", "")
            or ""
        ).strip()
        if not text:
            continue
        text = text[:max_chars_per_section].rstrip()
        snippets.append((section_title, text))

    if not snippets:
        return f"## {title}\n\n{empty_message}"

    if field == "qualification_compliance_requirements":
        lines = [
            "## 资格性审查",
            "| 序号 | 资格要求 | 需提供资料 |",
            "| --- | --- | --- |",
            "| 1 | 见下方本地召回候选片段，请人工核对后再生成投标文件 | 未明确 |",
            "",
            "## 符合性审查",
            "| 序号 | 资格要求 | 需提供资料 |",
            "| --- | --- | --- |",
            "| 1 | 见下方本地召回候选片段，请人工核对后再生成投标文件 | 未明确 |",
            "",
            "## 废标项",
            "| 序号 | 废标项 | 具体表现 |",
            "| --- | --- | --- |",
            "| 1 | 见下方本地召回候选片段，请人工核对后再生成投标文件 | 未明确 |",
            "",
            "## 本地召回候选片段",
        ]
    elif field == "price_scoring_requirements":
        lines = [
            "## 商务评分",
            "| 评分项 | 评分标准 | 分数 |",
            "| --- | --- | --- |",
            "| 见下方本地召回候选片段 | 请人工核对评分表后再生成投标文件 | 未明确 |",
            "",
            "## 技术评分",
            "| 评分项 | 评分标准 | 分数 |",
            "| --- | --- | --- |",
            "| 见下方本地召回候选片段 | 请人工核对评分表后再生成投标文件 | 未明确 |",
            "",
            "## 本地召回候选片段",
        ]
    else:
        lines = [
            f"# {title}",
            "",
            "> 大模型未返回有效内容，以下为后端按宽关键词和章节标题召回的候选原文片段。",
            "",
        ]

    for index, (section_title, text) in enumerate(snippets, start=1):
        lines.extend(
            [
                f"### 候选片段 {index}：{section_title}",
                "",
                text,
                "",
            ]
        )
    return "\n".join(lines).strip()


def _build_structured_analysis_jobs(
    sections: List[BidDocumentSection],
    global_context: str = "",
    qualification_prefilter_sections: Optional[List[BidDocumentSection]] = None,
) -> list[tuple[str, str, list, dict]]:
    retrieved_sections = retrieve_sections_for_analysis(sections)
    if qualification_prefilter_sections:
        retrieved_sections["qualification_compliance"] = merge_qualification_prefilter_sections(
            retrieved_sections["qualification_compliance"],
            qualification_prefilter_sections,
        )
    return [
        (
            "business_content",
            "商务内容",
            build_structured_messages(
                "business_content",
                retrieved_sections["business_content"],
                global_context=global_context,
            ),
            schema_for_field("business_content"),
        ),
        (
            "technical_scoring_requirements",
            "技术要求",
            build_structured_messages(
                "technical_scoring_requirements",
                retrieved_sections["technical_requirements"],
                global_context=global_context,
            ),
            schema_for_field("technical_scoring_requirements"),
        ),
        (
            "qualification_compliance_requirements",
            "资格和符合性审查",
            build_structured_messages(
                "qualification_compliance_requirements",
                retrieved_sections["qualification_compliance"],
                global_context=global_context,
            ),
            schema_for_field("qualification_compliance_requirements"),
        ),
        (
            "price_scoring_requirements",
            "评分要求",
            build_structured_messages(
                "price_scoring_requirements",
                retrieved_sections["scoring"],
                global_context=global_context,
            ),
            schema_for_field("price_scoring_requirements"),
        ),
    ]


def _run_structured_job_sync(
    llm: LLM_Invoke,
    field: str,
    messages: list,
    schema: dict,
) -> tuple[str, dict]:
    try:
        raw = llm.think_json(messages, schema=schema)
    except Exception:
        strict_messages = _messages_with_json_only_instruction(messages)
        raw = llm.think(strict_messages, stream=False)
    data = parse_structured_json(raw)
    markdown = structured_to_markdown(field, data)
    if not markdown:
        raise ValueError(f"{field} structured JSON parse failed")
    return markdown, data


async def _run_structured_job_async(
    llm: LLM_Invoke,
    field: str,
    messages: list,
    schema: dict,
) -> tuple[str, dict]:
    try:
        raw = await llm.athink_json(messages, schema=schema)
    except Exception:
        strict_messages = _messages_with_json_only_instruction(messages)
        raw = await llm.athink(strict_messages, stream=False)
    data = parse_structured_json(raw)
    markdown = structured_to_markdown(field, data)
    if not markdown:
        raise ValueError(f"{field} structured JSON parse failed")
    return markdown, data


DISPLAY_MARKDOWN_FIELDS = (
    "business_content",
    "technical_scoring_requirements",
    "qualification_compliance_requirements",
    "price_scoring_requirements",
)


def _ensure_display_markdown_fields(results: dict) -> None:
    structured = results.get("structured_extraction") if isinstance(results.get("structured_extraction"), dict) else {}
    for field in DISPLAY_MARKDOWN_FIELDS:
        value = results.get(field)
        markdown = _coerce_field_to_markdown(field, value)
        if not markdown and structured.get(field):
            markdown = _coerce_field_to_markdown(field, structured.get(field))
        if markdown:
            results[field] = markdown


def _coerce_field_to_markdown(field: str, value) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return structured_to_markdown(field, value)
    if isinstance(value, list):
        return structured_to_markdown(field, _wrap_structured_rows(field, value))
    text = str(value or "").strip()
    if not text:
        return ""
    if text[:1] in {"{", "["} or text.startswith("```"):
        parsed = parse_structured_json(text)
        if parsed:
            markdown = structured_to_markdown(field, parsed)
            if markdown:
                return markdown
    return text


def _wrap_structured_rows(field: str, rows: list) -> dict:
    if field == "business_content":
        return {"business_requirements": rows}
    if field == "technical_scoring_requirements":
        return {"technical_requirements": rows}
    if field == "qualification_compliance_requirements":
        return {"qualification_requirements": rows, "rejection_items": []}
    if field == "price_scoring_requirements":
        return {"scoring_items": rows}
    return {}


def _messages_with_json_only_instruction(messages: list) -> list:
    output = [dict(message) for message in messages]
    output.append(
        {
            "role": "user",
            "content": "再次强调：只能输出符合上述 JSON Schema 的 JSON 对象，不要输出 Markdown 或解释。",
        }
    )
    return output


def _build_global_context_sync(
    llm: LLM_Invoke,
    sections: List[BidDocumentSection],
    stream_output: bool,
) -> tuple[str, str]:
    """Run the first-pass project profile + section tree extraction."""
    rule_context = build_rule_global_context(sections)
    try:
        payload = json.loads(rule_context)
        if not needs_llm_global_completion(
            payload.get("project_profile") or {},
            payload.get("section_tree") or [],
        ):
            return rule_context, rule_project_overview_markdown(rule_context)
    except Exception:
        pass
    try:
        global_context = llm.think(
            build_global_context_messages_from_sections(
                retrieve_sections_for_analysis(sections)["project_overview"]
            ),
            stream=False,
        ) or ""
        project_overview = build_project_overview_text_from_global_context(global_context)
        return global_context, project_overview
    except Exception:
        messages = build_project_overview_messages_from_sections(
            retrieve_sections_for_analysis(sections)["project_overview"]
        )
        project_overview = llm.think(messages, stream=stream_output) or ""
        return "", project_overview


async def _build_global_context_async(
    llm: LLM_Invoke,
    sections: List[BidDocumentSection],
) -> tuple[str, str]:
    """Async first-pass project profile + section tree extraction."""
    rule_context = build_rule_global_context(sections)
    try:
        payload = json.loads(rule_context)
        if not needs_llm_global_completion(
            payload.get("project_profile") or {},
            payload.get("section_tree") or [],
        ):
            return rule_context, rule_project_overview_markdown(rule_context)
    except Exception:
        pass
    try:
        global_context = await llm.athink(
            build_global_context_messages_from_sections(
                retrieve_sections_for_analysis(sections)["project_overview"]
            ),
            stream=False,
        ) or ""
        project_overview = build_project_overview_text_from_global_context(global_context)
        return global_context, project_overview
    except Exception:
        messages = build_project_overview_messages_from_sections(
            retrieve_sections_for_analysis(sections)["project_overview"]
        )
        project_overview = await llm.athink(messages, stream=False) or ""
        return "", project_overview


def _build_lightweight_prefilter_llm(llm_vendor: str) -> LLM_Invoke:
    model = os.getenv("BID_QUAL_PREFILTER_MODEL_ID") or "Qwen/Qwen3-8B"
    base_url = os.getenv("BID_QUAL_PREFILTER_BASE_URL") or resolve_llm_base_url(llm_vendor)
    timeout = int(os.getenv("BID_QUAL_PREFILTER_TIMEOUT", os.getenv("LLM_TIMEOUT", "120")))
    return LLM_Invoke(model=model, base_url=base_url, timeout=timeout)


def _run_qualification_prefilter_sync(
    sections: List[BidDocumentSection],
    llm_vendor: str,
) -> list[BidDocumentSection]:
    if not qualification_prefilter_enabled():
        return []
    try:
        return prefilter_qualification_sections_sync(
            sections,
            _build_lightweight_prefilter_llm(llm_vendor),
        )
    except Exception:
        return []


async def _run_qualification_prefilter_async(
    sections: List[BidDocumentSection],
    llm_vendor: str,
) -> list[BidDocumentSection]:
    if not qualification_prefilter_enabled():
        return []
    try:
        return await prefilter_qualification_sections(
            sections,
            _build_lightweight_prefilter_llm(llm_vendor),
        )
    except Exception:
        return []


def _build_llm(
    llm_vendor: str,
    llm_model: Optional[str],
    enable_deep_thinking: bool = False,
) -> LLM_Invoke:
    resolved_model = None
    resolved_base_url = None
    if llm_model:
        resolved_model, resolved_base_url = resolve_llm_selection(
            vendor=llm_vendor,
            model_name=llm_model,
        )
    return LLM_Invoke(
        model=resolved_model,
        base_url=resolved_base_url,
        enable_deep_thinking=enable_deep_thinking,
    )


def _build_content_review_llm_messages(
    source_text: str,
    extracted: dict,
    regex_report: str,
) -> list[dict[str, str]]:
    source_text = (source_text or "")[:60000]
    extracted_text = json.dumps(extracted or {}, ensure_ascii=False, indent=2)[:30000]
    regex_report = (regex_report or "")[:20000]
    return [
        {
            "role": "system",
            "content": (
                "你是严谨的招投标内容审查专家。请基于原文、已提取结果和正则审查报告，"
                "复核信息是否完整、准确、一致，并指出响应偏离、废标风险和需要人工核对的事项。"
                "不要重新生成五大模块内容，只输出审查意见。"
            ),
        },
        {
            "role": "user",
            "content": (
                "请按以下 Markdown 结构输出：\n\n"
                "### 复核结论\n"
                "- 结论：\n"
                "- 主要风险：\n\n"
                "### 高风险问题\n"
                "| 模块 | 问题 | 原因 | 建议 |\n"
                "| --- | --- | --- | --- |\n\n"
                "### 需要人工核对\n"
                "| 模块 | 核对点 | 核对依据 |\n"
                "| --- | --- | --- |\n\n"
                "### 补充建议\n"
                "- \n\n"
                f"【正则审查报告】\n{regex_report}\n\n"
                f"【已提取结果】\n{extracted_text}\n\n"
                f"【原始解析文本】\n{source_text}"
            ),
        },
    ]


def _sections_to_markdown_for_review(sections: List[BidDocumentSection]) -> str:
    return "\n\n".join(
        section.markdown or section.content or ""
        for section in sections
        if section.markdown or section.content
    )


def _analyze_sections(
    sections: List[BidDocumentSection],
    llm_vendor: str,
    llm_model: Optional[str],
    stream_output: bool,
    enable_deep_thinking: bool = False,
) -> BidAnalysisResult:
    llm = _build_llm(
        llm_vendor=llm_vendor,
        llm_model=llm_model,
        enable_deep_thinking=enable_deep_thinking,
    )
    global_context, project_overview = _build_global_context_sync(
        llm=llm,
        sections=sections,
        stream_output=stream_output,
    )
    qualification_prefilter_hits = _run_qualification_prefilter_sync(
        sections=sections,
        llm_vendor=llm_vendor,
    )
    structured_outputs: dict[str, dict] = {}
    if structured_output_enabled():
        try:
            structured_jobs = _build_structured_analysis_jobs(
                sections,
                global_context=global_context,
                qualification_prefilter_sections=qualification_prefilter_hits,
            )
            structured_results = {}
            for field, _, messages, schema in structured_jobs:
                markdown, data = _run_structured_job_sync(llm, field, messages, schema)
                structured_results[field] = markdown
                structured_outputs[field] = data
            business_content = structured_results["business_content"]
            technical_scoring_requirements = structured_results["technical_scoring_requirements"]
            qualification_compliance_requirements = structured_results[
                "qualification_compliance_requirements"
            ]
            price_scoring_requirements = structured_results["price_scoring_requirements"]
        except Exception:
            structured_outputs = {}
            jobs = _build_analysis_jobs(
                sections,
                global_context=global_context,
                qualification_prefilter_sections=qualification_prefilter_hits,
            )
            messages_batch = [messages for _, _, messages in jobs]
            (
                business_content,
                technical_scoring_requirements,
                qualification_compliance_requirements,
                price_scoring_requirements,
            ) = llm.think_many_sync(messages_batch, stream=stream_output)
    else:
        jobs = _build_analysis_jobs(
            sections,
            global_context=global_context,
            qualification_prefilter_sections=qualification_prefilter_hits,
        )
        messages_batch = [messages for _, _, messages in jobs]
        try:
            (
                business_content,
                technical_scoring_requirements,
                qualification_compliance_requirements,
                price_scoring_requirements,
            ) = llm.think_many_sync(messages_batch, stream=stream_output)
        except Exception:
            business_content = llm.think(messages_batch[0], stream=stream_output)
            technical_scoring_requirements = llm.think(messages_batch[1], stream=stream_output)
            qualification_compliance_requirements = llm.think(
                messages_batch[2],
                stream=stream_output,
            )
            price_scoring_requirements = llm.think(messages_batch[3], stream=stream_output)

    result = BidAnalysisResult(
        sections=sections,
        project_overview=clean_repeated_extraction_text(project_overview),
        business_content=clean_repeated_extraction_text(business_content),
        technical_scoring_requirements=clean_repeated_extraction_text(technical_scoring_requirements),
        qualification_compliance_requirements=clean_repeated_extraction_text(qualification_compliance_requirements),
        price_scoring_requirements=clean_repeated_extraction_text(price_scoring_requirements),
        global_context_markdown=global_context,
        qualification_prefilter_count=len(qualification_prefilter_hits),
        structured_extraction=structured_outputs,
        content_review_markdown="内容审查尚未执行，请在前端点击“执行审查”。",
        content_review_report={},
    )
    try:
        save_analysis_result(
            sections=[section.model_dump() for section in sections],
            analysis=result.model_dump(),
            file_name="analyzed_content.md",
            document_type="招标文件",
            parse_method="structured_analysis",
        )
    except Exception:
        pass
    return result

