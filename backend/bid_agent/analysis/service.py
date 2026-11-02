''' 招标文件分析服务，包含解析招标文件、构建提示词、调用LLM进行分析的函数。'''
# -*- coding: utf-8 -*-
import asyncio
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field

from bid_agent.analysis.prompts import (
    build_business_content_messages_from_sections,
    build_business_scoring_messages_from_sections,
    build_global_context_messages_from_sections,
    build_project_overview_text_from_global_context,
    build_project_overview_messages_from_sections,
    build_qualification_compliance_messages_from_sections,
    build_technical_scoring_messages_from_sections,
)
from bid_agent.parsing.document_parser import BidDocumentSection, parse_bid_document
from bid_agent.parsing.image_analysis import analyze_document_images, format_image_analysis_markdown
from bid_agent.parsing.strategy import (
    build_parse_quality_report,
    count_docx_images,
    inspect_document_profile,
    resolve_parse_method,
)
from bid_agent.analysis.qualification_prefilter import (
    merge_qualification_prefilter_sections,
    prefilter_qualification_sections_sync,
    qualification_prefilter_enabled,
)
from bid_agent.rag.section_retriever import retrieve_sections_for_analysis
from bid_agent.analysis.rule_extractor import (
    build_rule_global_context,
    needs_llm_global_completion,
    rule_project_overview_markdown,
)
from bid_agent.analysis.structured_extraction import (
    build_structured_messages,
    parse_structured_json,
    schema_for_field,
    structured_output_enabled,
    structured_to_markdown,
)
from bid_agent.infrastructure.database import save_analysis_result
from bid_agent.analysis.cleaner import clean_repeated_extraction_text
from bid_agent.infrastructure.llm_client import LLM_Invoke
from bid_agent.core.model_config import resolve_llm_selection, resolve_llm_base_url


class BidAnalysisResult(BaseModel):
    sections: List[BidDocumentSection] = Field(description="MinerU parsed sections.")
    project_overview: str = Field(description="LLM extracted project overview.")
    business_content: str = Field(default="", description="LLM extracted business content.")
    technical_scoring_requirements: str = Field(
        description="LLM extracted technical scoring requirements."
    )
    qualification_compliance_requirements: str = Field(
        description="LLM extracted qualification and compliance review requirements."
    )
    price_scoring_requirements: str = Field(
        description="LLM extracted price scoring requirements."
    )
    image_analysis_markdown: str = Field(
        default="",
        description="OCR and LLM notes for images extracted from the bid document.",
    )
    image_analysis_items: List[dict] = Field(
        default_factory=list,
        description="Image preview, OCR text, and LLM notes for extracted images.",
    )
    parse_method_used: str = Field(default="", description="Actual parser used.")
    parse_method_recommended: str = Field(default="", description="Recommended parser.")
    parse_quality: dict = Field(default_factory=dict, description="Parse quality metrics.")
    content_review_markdown: str = Field(
        default="",
        description="Regex-based completeness and accuracy review report.",
    )
    content_review_report: dict = Field(
        default_factory=dict,
        description="Structured regex-based content review report.",
    )
    global_context_markdown: str = Field(
        default="",
        description="First-pass project_profile and section_tree context.",
    )
    qualification_prefilter_count: int = Field(
        default=0,
        description="Number of lightweight prefilter hits used for qualification extraction.",
    )
    structured_extraction: dict = Field(
        default_factory=dict,
        description="JSON Schema structured extraction payloads by module.",
    )


def _build_lightweight_prefilter_llm(llm_vendor: str) -> LLM_Invoke:
    import os

    model = os.getenv("BID_QUAL_PREFILTER_MODEL_ID") or "Qwen/Qwen3-8B"
    base_url = os.getenv("BID_QUAL_PREFILTER_BASE_URL") or resolve_llm_base_url(llm_vendor)
    timeout = int(os.getenv("BID_QUAL_PREFILTER_TIMEOUT", os.getenv("LLM_TIMEOUT", "120")))
    return LLM_Invoke(model=model, base_url=base_url, timeout=timeout)


def _run_qualification_prefilter(
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


def _run_structured_job(
    llm: LLM_Invoke,
    field: str,
    messages: list,
    schema: dict,
) -> tuple[str, dict]:
    try:
        raw = llm.think_json(messages, schema=schema)
    except Exception:
        raw = llm.think(
            [
                *messages,
                {
                    "role": "user",
                    "content": "只能输出符合上述 JSON Schema 的 JSON 对象，不要输出 Markdown 或解释。",
                },
            ],
            stream=False,
        )
    data = parse_structured_json(raw)
    markdown = structured_to_markdown(field, data)
    if not markdown:
        raise ValueError(f"{field} structured JSON parse failed")
    return markdown, data


MODULE_FALLBACK_CONFIG = {
    "business_content": ("business_content", "商务内容", "未从候选章节中召回到明确商务内容。"),
    "technical_scoring_requirements": ("technical_requirements", "技术要求", "未从候选章节中召回到明确技术要求。"),
    "qualification_compliance_requirements": (
        "qualification_compliance",
        "资格审查与废标项",
        "未从候选章节中召回到明确资格审查、符合性审查或废标项。",
    ),
    "price_scoring_requirements": ("scoring", "评分要求", "未从候选章节中召回到明确评分要求。"),
}


def _apply_local_module_fallbacks(
    results: dict,
    retrieved_sections: dict,
) -> dict:
    for field, (retrieval_key, title, empty_message) in MODULE_FALLBACK_CONFIG.items():
        value = str(results.get(field) or "").strip()
        if value and "提取失败" not in value[:80]:
            continue
        results[field] = _format_local_module_fallback(
            field,
            title,
            retrieved_sections.get(retrieval_key, []),
            empty_message,
        )
    return results


def _format_local_module_fallback(
    field: str,
    title: str,
    sections: list[BidDocumentSection],
    empty_message: str,
    max_sections: int = 6,
    max_chars_per_section: int = 1200,
) -> str:
    snippets = []
    for section in sections[:max_sections]:
        section_title = str(getattr(section, "title", "") or "候选片段").strip()
        text = str(getattr(section, "markdown", "") or getattr(section, "content", "") or "").strip()
        if text:
            snippets.append((section_title, text[:max_chars_per_section].rstrip()))
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
        lines.extend([f"### 候选片段 {index}：{section_title}", "", text, ""])
    return "\n".join(lines).strip()


def analyze_bid_document(
    document: str,
    output_dir: Optional[str] = None,
    model_version: str = "vlm",
    language: str = "ch",
    is_ocr: bool = False,
    enable_formula: bool = True,
    enable_table: bool = True,
    page_ranges: Optional[str] = None,
    poll_interval: int = 5,
    timeout: int = 600,
    parse_method: str = "mineru_vlm",
    llm_vendor: str = "siliconflow",
    llm_model: Optional[str] = None,
    stream_output: bool = True,
    enable_deep_thinking: bool = False,
    llm_client: Optional[LLM_Invoke] = None,
) -> BidAnalysisResult:
    """Parse a bid document, pack parsed content with prompts, then ask the LLM."""
    preflight_profile = inspect_document_profile(document)
    parse_method_used, _ = resolve_parse_method(document, parse_method)
    parse_method_recommended = preflight_profile.get("recommended_parse_method", parse_method_used)
    sections = parse_bid_document(
        document=document,
        output_dir=output_dir,
        parse_method=parse_method_used,
        model_version=model_version,
        language=language,
        is_ocr=is_ocr,
        enable_formula=enable_formula,
        enable_table=enable_table,
        page_ranges=page_ranges,
        poll_interval=poll_interval,
        timeout=timeout,
    )
    resolved_model = None
    resolved_base_url = None
    if llm_model:
        resolved_model, resolved_base_url = resolve_llm_selection(
            vendor=llm_vendor,
            model_name=llm_model,
        )
    llm = llm_client or LLM_Invoke(
        model=resolved_model,
        base_url=resolved_base_url,
        enable_deep_thinking=enable_deep_thinking,
    )

    retrieved_sections = retrieve_sections_for_analysis(sections)
    qualification_prefilter_hits = _run_qualification_prefilter(
        sections=sections,
        llm_vendor=llm_vendor,
    )
    if qualification_prefilter_hits:
        retrieved_sections["qualification_compliance"] = merge_qualification_prefilter_sections(
            retrieved_sections["qualification_compliance"],
            qualification_prefilter_hits,
        )
    rule_context = build_rule_global_context(sections)
    try:
        import json

        rule_payload = json.loads(rule_context)
        if not needs_llm_global_completion(
            rule_payload.get("project_profile") or {},
            rule_payload.get("section_tree") or [],
        ):
            global_context = rule_context
            project_overview = rule_project_overview_markdown(rule_context)
        else:
            global_context = llm.think(
                build_global_context_messages_from_sections(retrieved_sections["project_overview"]),
                stream=False,
            ) or ""
            project_overview = build_project_overview_text_from_global_context(global_context)
    except Exception:
        global_context = rule_context
        project_overview = llm.think(
            build_project_overview_messages_from_sections(retrieved_sections["project_overview"]),
            stream=stream_output,
        ) or rule_project_overview_markdown(rule_context)
    structured_outputs: dict[str, dict] = {}
    if structured_output_enabled():
        try:
            structured_jobs = [
                (
                    "business_content",
                    build_structured_messages(
                        "business_content",
                        retrieved_sections["business_content"],
                        global_context=global_context,
                    ),
                    schema_for_field("business_content"),
                ),
                (
                    "technical_scoring_requirements",
                    build_structured_messages(
                        "technical_scoring_requirements",
                        retrieved_sections["technical_requirements"],
                        global_context=global_context,
                    ),
                    schema_for_field("technical_scoring_requirements"),
                ),
                (
                    "qualification_compliance_requirements",
                    build_structured_messages(
                        "qualification_compliance_requirements",
                        retrieved_sections["qualification_compliance"],
                        global_context=global_context,
                    ),
                    schema_for_field("qualification_compliance_requirements"),
                ),
                (
                    "price_scoring_requirements",
                    build_structured_messages(
                        "price_scoring_requirements",
                        retrieved_sections["scoring"],
                        global_context=global_context,
                    ),
                    schema_for_field("price_scoring_requirements"),
                ),
            ]
            structured_results = {}
            for field, messages, schema in structured_jobs:
                markdown, data = _run_structured_job(llm, field, messages, schema)
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
            messages_batch = [
                build_business_content_messages_from_sections(
                    retrieved_sections["business_content"],
                    global_context=global_context,
                ),
                build_technical_scoring_messages_from_sections(
                    retrieved_sections["technical_requirements"],
                    global_context=global_context,
                ),
                build_qualification_compliance_messages_from_sections(
                    retrieved_sections["qualification_compliance"],
                    global_context=global_context,
                ),
                build_business_scoring_messages_from_sections(
                    retrieved_sections["scoring"],
                    global_context=global_context,
                ),
            ]
            (
                business_content,
                technical_scoring_requirements,
                qualification_compliance_requirements,
                price_scoring_requirements,
            ) = llm.think_many_sync(messages_batch, stream=stream_output)
    else:
        messages_batch = [
            build_business_content_messages_from_sections(
                retrieved_sections["business_content"],
                global_context=global_context,
            ),
            build_technical_scoring_messages_from_sections(
                retrieved_sections["technical_requirements"],
                global_context=global_context,
            ),
            build_qualification_compliance_messages_from_sections(
                retrieved_sections["qualification_compliance"],
                global_context=global_context,
            ),
            build_business_scoring_messages_from_sections(
                retrieved_sections["scoring"],
                global_context=global_context,
            ),
        ]
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

    module_results = _apply_local_module_fallbacks(
        {
            "business_content": business_content,
            "technical_scoring_requirements": technical_scoring_requirements,
            "qualification_compliance_requirements": qualification_compliance_requirements,
            "price_scoring_requirements": price_scoring_requirements,
        },
        retrieved_sections,
    )
    business_content = module_results["business_content"]
    technical_scoring_requirements = module_results["technical_scoring_requirements"]
    qualification_compliance_requirements = module_results["qualification_compliance_requirements"]
    price_scoring_requirements = module_results["price_scoring_requirements"]

    image_analysis_markdown = ""
    image_analysis_items = []
    try:
        image_items = asyncio.run(
            analyze_document_images(
                document=document,
                llm=llm,
                parse_method=parse_method_used,
                model_version=model_version,
                language=language,
                is_ocr=is_ocr,
                enable_formula=enable_formula,
                enable_table=enable_table,
                page_ranges=page_ranges,
            )
        )
        image_analysis_markdown = format_image_analysis_markdown(image_items)
        image_analysis_items = [item.model_dump() for item in image_items]
    except Exception as exc:
        image_analysis_markdown = f"图片解析失败：{exc}"

    image_count = len(image_analysis_items) or count_docx_images(Path(document))
    image_ocr_chars = sum(len(str(item.get("ocr_text", ""))) for item in image_analysis_items)
    parse_quality = build_parse_quality_report(
        sections=sections,
        parse_method_used=parse_method_used,
        parse_method_recommended=parse_method_recommended,
        image_count=image_count,
        image_ocr_chars=image_ocr_chars,
        preflight_profile=preflight_profile,
    )
    result = BidAnalysisResult(
        sections=sections,
        project_overview=clean_repeated_extraction_text(project_overview),
        business_content=clean_repeated_extraction_text(business_content),
        technical_scoring_requirements=clean_repeated_extraction_text(technical_scoring_requirements),
        qualification_compliance_requirements=clean_repeated_extraction_text(qualification_compliance_requirements),
        price_scoring_requirements=clean_repeated_extraction_text(price_scoring_requirements),
        image_analysis_markdown=image_analysis_markdown,
        image_analysis_items=image_analysis_items,
        parse_method_used=parse_method_used,
        parse_method_recommended=parse_method_recommended,
        parse_quality=parse_quality,
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
            file_name=Path(document).name,
            document_type="招标文件",
            parse_method=parse_method_used,
        )
    except Exception:
        pass
    return result
# 这个脚本负责把文件解析结果交给大模型，并汇总招标分析结果。
