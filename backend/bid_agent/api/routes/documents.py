"""Extracted from the original API; public request contracts are retained."""
import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import AsyncIterator, Optional
from fastapi import File, Form, UploadFile
from fastapi.responses import StreamingResponse
from bid_agent.analysis.service import analyze_bid_document
from bid_agent.review.content_review import build_content_review
from bid_agent.parsing.document_parser import parse_bid_document, split_bid_markdown_sections
from bid_agent.parsing.image_analysis import analyze_document_images, format_image_analysis_markdown
from bid_agent.parsing.strategy import build_parse_quality_report, count_docx_images, inspect_document_profile, resolve_parse_method
from bid_agent.analysis.structured_extraction import structured_output_enabled
from bid_agent.infrastructure.database import save_analysis_result
from bid_agent.analysis.cleaner import clean_analysis_dict
from bid_agent.infrastructure.llm_client import LLM_Invoke
from bid_agent.core.model_config import resolve_llm_selection
from fastapi import APIRouter
from bid_agent.services.analysis_workflow import (
    _analyze_sections,
    _apply_local_module_fallbacks,
    _build_analysis_jobs,
    _build_content_review_llm_messages,
    _build_global_context_async,
    _build_llm,
    _build_structured_analysis_jobs,
    _classify_exception,
    _ensure_display_markdown_fields,
    _exception_traceback_tail,
    _raise_api_error,
    _run_qualification_prefilter_async,
    _run_structured_job_async,
    _sections_to_markdown_for_review,
    _stream_event,
)
from bid_agent.schemas.requests import (
    AnalyzeContentRequest,
    AnalyzeDocumentResponse,
    ContentReviewRequest,
    ContentReviewResponse,
    ParseDocumentRequest,
    ParseDocumentResponse,
)

from bid_agent.api.uploads import read_upload, read_upload_async, validate_output_dir

router = APIRouter(tags=["documents"])

@router.post("/bid-documents/parse", response_model=ParseDocumentResponse)
def parse_document(request: ParseDocumentRequest) -> ParseDocumentResponse:
    try:
        preflight_profile = inspect_document_profile(request.document)
        parse_method_used, _ = resolve_parse_method(request.document, request.parse_method)
        sections = parse_bid_document(
            document=request.document,
            output_dir=request.output_dir,
            parse_method=parse_method_used,
            model_version=request.model_version,
            language=request.language,
            is_ocr=request.is_ocr,
            enable_formula=request.enable_formula,
            enable_table=request.enable_table,
            page_ranges=request.page_ranges,
            poll_interval=request.poll_interval,
            timeout=request.timeout,
        )
        parse_method_recommended = preflight_profile.get(
            "recommended_parse_method",
            parse_method_used,
        )
        parse_quality = build_parse_quality_report(
            sections=sections,
            parse_method_used=parse_method_used,
            parse_method_recommended=parse_method_recommended,
            image_count=int(preflight_profile.get("image_count") or count_docx_images(Path(request.document))),
            preflight_profile=preflight_profile,
        )
    except Exception as exc:
        _raise_api_error(exc)
    return ParseDocumentResponse(
        sections=sections,
        parse_method_used=parse_method_used,
        parse_method_recommended=parse_method_recommended,
        parse_quality=parse_quality,
    )


@router.post("/bid-documents/upload", response_model=ParseDocumentResponse)
def upload_document(
    file: UploadFile = File(...),
    output_dir: Optional[str] = Form(default=None),
    parse_method: str = Form(default="mineru_vlm"),
    model_version: str = Form(default="vlm"),
    llm_vendor: str = Form(default="siliconflow"),
    llm_model: Optional[str] = Form(default=None),
    language: str = Form(default="ch"),
    is_ocr: Optional[bool] = Form(default=None),
    enable_formula: bool = Form(default=True),
    enable_table: bool = Form(default=True),
    page_ranges: Optional[str] = Form(default=None),
    poll_interval: int = Form(default=5),
    timeout: int = Form(default=600),
) -> ParseDocumentResponse:
    validate_output_dir(output_dir)
    suffix = Path(file.filename or "document").suffix
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir) / f"upload{suffix}"
        with temp_path.open("wb") as file_obj:
            file_obj.write(read_upload(file))

        try:
            preflight_profile = inspect_document_profile(str(temp_path))
            parse_method_used, _ = resolve_parse_method(str(temp_path), parse_method)
            sections = parse_bid_document(
                document=str(temp_path),
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
            parse_method_recommended = preflight_profile.get(
                "recommended_parse_method",
                parse_method_used,
            )
            parse_quality = build_parse_quality_report(
                sections=sections,
                parse_method_used=parse_method_used,
                parse_method_recommended=parse_method_recommended,
                image_count=int(preflight_profile.get("image_count") or count_docx_images(temp_path)),
                preflight_profile=preflight_profile,
            )
        except Exception as exc:
            _raise_api_error(exc)

    return ParseDocumentResponse(
        sections=sections,
        parse_method_used=parse_method_used,
        parse_method_recommended=parse_method_recommended,
        parse_quality=parse_quality,
    )


@router.post("/bid-documents/analyze", response_model=AnalyzeDocumentResponse)
def analyze_document(request: ParseDocumentRequest) -> AnalyzeDocumentResponse:
    try:
        result = analyze_bid_document(
            document=request.document,
            output_dir=request.output_dir,
            parse_method=request.parse_method,
            model_version=request.model_version,
            llm_vendor=request.llm_vendor,
            llm_model=request.llm_model,
            stream_output=request.stream_output,
            enable_deep_thinking=request.enable_deep_thinking,
            language=request.language,
            is_ocr=request.is_ocr,
            enable_formula=request.enable_formula,
            enable_table=request.enable_table,
            page_ranges=request.page_ranges,
            poll_interval=request.poll_interval,
            timeout=request.timeout,
        )
    except Exception as exc:
        _raise_api_error(exc)
    return AnalyzeDocumentResponse(**result.model_dump())


@router.post("/bid-documents/analyze-content", response_model=AnalyzeDocumentResponse)
def analyze_edited_content(request: AnalyzeContentRequest) -> AnalyzeDocumentResponse:
    try:
        sections = split_bid_markdown_sections(request.file_content)
        result = _analyze_sections(
            sections=sections,
            llm_vendor=request.llm_vendor,
            llm_model=request.llm_model,
            stream_output=request.stream_output,
            enable_deep_thinking=request.enable_deep_thinking,
        )
    except Exception as exc:
        _raise_api_error(exc)
    return AnalyzeDocumentResponse(**result.model_dump())


@router.post("/bid-documents/content-review", response_model=ContentReviewResponse)
def review_extracted_content(request: ContentReviewRequest) -> ContentReviewResponse:
    try:
        sections = request.sections or split_bid_markdown_sections(request.file_content)
        report = build_content_review(sections=sections, extracted=request.extracted)
        if request.llm_model:
            try:
                llm = _build_llm(
                    llm_vendor=request.llm_vendor,
                    llm_model=request.llm_model,
                    enable_deep_thinking=request.enable_deep_thinking,
                )
                llm_review = llm.think(
                    _build_content_review_llm_messages(
                        source_text=request.file_content or _sections_to_markdown_for_review(sections),
                        extracted=request.extracted,
                        regex_report=report.get("markdown", ""),
                    ),
                    stream=False,
                )
                if llm_review:
                    report["llm_review_markdown"] = llm_review
                    report["markdown"] = "\n\n".join(
                        [
                            report.get("markdown", ""),
                            "## 大模型深度审查",
                            "",
                            llm_review.strip(),
                        ]
                    ).strip()
            except Exception as llm_exc:
                error_type, message, hint = _classify_exception(llm_exc, stage="内容审查大模型复核")
                report["llm_review_error"] = {
                    "type": error_type,
                    "message": message,
                    "hint": hint,
                }
                report["markdown"] = "\n\n".join(
                    [
                        report.get("markdown", ""),
                        "## 大模型深度审查",
                        "",
                        "大模型深度审查失败，但正则审查报告已生成。",
                        "",
                        f"- 错误类型：{error_type}",
                        f"- 错误信息：{message}",
                        f"- 排查建议：{hint}",
                    ]
                ).strip()
    except Exception as exc:
        _raise_api_error(exc)
    return ContentReviewResponse(
        content_review_markdown=report.get("markdown", ""),
        content_review_report=report,
    )


@router.post("/bid-documents/upload-analyze", response_model=AnalyzeDocumentResponse)
def upload_and_analyze_document(
    file: UploadFile = File(...),
    output_dir: Optional[str] = Form(default=None),
    parse_method: str = Form(default="mineru_vlm"),
    model_version: str = Form(default="vlm"),
    llm_vendor: str = Form(default="siliconflow"),
    llm_model: Optional[str] = Form(default=None),
    stream_output: bool = Form(default=True),
    enable_deep_thinking: bool = Form(default=False),
    language: str = Form(default="ch"),
    is_ocr: Optional[bool] = Form(default=None),
    enable_formula: bool = Form(default=True),
    enable_table: bool = Form(default=True),
    page_ranges: Optional[str] = Form(default=None),
    poll_interval: int = Form(default=5),
    timeout: int = Form(default=600),
) -> AnalyzeDocumentResponse:
    validate_output_dir(output_dir)
    suffix = Path(file.filename or "document").suffix
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir) / f"upload{suffix}"
        with temp_path.open("wb") as file_obj:
            file_obj.write(read_upload(file))

        try:
            parse_method_used, _ = resolve_parse_method(str(temp_path), parse_method)
            result = analyze_bid_document(
                document=str(temp_path),
                output_dir=output_dir,
                parse_method=parse_method_used,
                model_version=model_version,
                llm_vendor=llm_vendor,
                llm_model=llm_model,
                stream_output=stream_output,
                enable_deep_thinking=enable_deep_thinking,
                language=language,
                is_ocr=is_ocr,
                enable_formula=enable_formula,
                enable_table=enable_table,
                page_ranges=page_ranges,
                poll_interval=poll_interval,
                timeout=timeout,
            )
        except Exception as exc:
            _raise_api_error(exc)

    return AnalyzeDocumentResponse(**result.model_dump())


@router.post("/bid-documents/upload-analyze-stream")
async def upload_and_analyze_document_stream(
    file: UploadFile = File(...),
    output_dir: Optional[str] = Form(default=None),
    parse_method: str = Form(default="mineru_vlm"),
    model_version: str = Form(default="vlm"),
    llm_vendor: str = Form(default="siliconflow"),
    llm_model: Optional[str] = Form(default=None),
    enable_deep_thinking: bool = Form(default=False),
    language: str = Form(default="ch"),
    is_ocr: Optional[bool] = Form(default=None),
    enable_formula: bool = Form(default=True),
    enable_table: bool = Form(default=True),
    page_ranges: Optional[str] = Form(default=None),
    poll_interval: int = Form(default=5),
    timeout: int = Form(default=600),
) -> StreamingResponse:
    validate_output_dir(output_dir)
    filename = file.filename or "document"
    suffix = Path(filename).suffix
    file_bytes = await read_upload_async(file)

    async def event_generator() -> AsyncIterator[str]:
        current_stage = "解析阶段"
        results = {
            "project_overview": "",
            "business_content": "",
            "technical_scoring_requirements": "",
            "qualification_compliance_requirements": "",
            "price_scoring_requirements": "",
        }
        try:
            yield _stream_event("status", message="文件已上传，正在解析招标文件...")
            with TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir) / f"upload{suffix}"
                temp_path.write_bytes(file_bytes)
                preflight_profile = inspect_document_profile(str(temp_path))
                parse_method_used, _ = resolve_parse_method(str(temp_path), parse_method)
                parse_method_recommended = preflight_profile.get(
                    "recommended_parse_method",
                    parse_method_used,
                )
                sections = parse_bid_document(
                    document=str(temp_path),
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

            yield _stream_event(
                "parsed",
                message=f"文件解析完成，共识别 {len(sections)} 个章节，开始调用大模型...",
                sections=[section.model_dump() for section in sections],
                parse_method_used=parse_method_used,
                parse_method_recommended=parse_method_recommended,
                preflight_profile=preflight_profile,
            )

            current_stage = "大模型阶段"
            resolved_model = None
            resolved_base_url = None
            if llm_model:
                resolved_model, resolved_base_url = resolve_llm_selection(
                    vendor=llm_vendor,
                    model_name=llm_model,
                )
            llm = LLM_Invoke(
                model=resolved_model,
                base_url=resolved_base_url,
                enable_deep_thinking=enable_deep_thinking,
            )
            yield _stream_event(
                "status",
                field="project_overview",
                message="正在生成项目画像和全文章节树...",
            )
            global_context, project_overview = await _build_global_context_async(llm, sections)
            results["project_overview"] = project_overview
            results["global_context_markdown"] = global_context
            yield _stream_event(
                "field_done",
                field="project_overview",
                message="项目画像和章节树生成完成",
                content=project_overview,
            )
            yield _stream_event(
                "status",
                field="qualification_compliance_requirements",
                message="正在用轻量模型逐章预筛疑似资格审查和废标段落...",
            )
            qualification_prefilter_hits = await _run_qualification_prefilter_async(
                sections=sections,
                llm_vendor=llm_vendor,
            )
            results["qualification_prefilter_count"] = len(qualification_prefilter_hits)
            if qualification_prefilter_hits:
                yield _stream_event(
                    "status",
                    field="qualification_compliance_requirements",
                    message=f"资格/废标预筛完成，命中 {len(qualification_prefilter_hits)} 个疑似片段，已并入精提取上下文。",
                )

            async def run_image_analysis():
                with TemporaryDirectory() as image_temp_dir:
                    image_temp_path = Path(image_temp_dir) / f"upload{suffix}"
                    image_temp_path.write_bytes(file_bytes)
                    image_items = await analyze_document_images(
                        document=str(image_temp_path),
                        llm=llm,
                        parse_method=parse_method_used,
                        model_version=model_version,
                        language=language,
                        is_ocr=is_ocr,
                        enable_formula=enable_formula,
                        enable_table=enable_table,
                        page_ranges=page_ranges,
                    )
                    return image_items

            image_task = asyncio.create_task(run_image_analysis())

            if structured_output_enabled():
                structured_jobs = _build_structured_analysis_jobs(
                    sections,
                    global_context=global_context,
                    qualification_prefilter_sections=qualification_prefilter_hits,
                )
                results["structured_extraction"] = {}
                yield _stream_event("status", message="正在按 JSON Schema 结构化抽取四个专项模块...")
                for field, label, messages, schema in structured_jobs:
                    yield _stream_event("status", field=field, message=f"正在结构化抽取{label}...")
                    try:
                        markdown, data = await _run_structured_job_async(llm, field, messages, schema)
                        results[field] = markdown
                        results["structured_extraction"][field] = data
                    except Exception:
                        fallback_jobs = _build_analysis_jobs(
                            sections,
                            global_context=global_context,
                            qualification_prefilter_sections=qualification_prefilter_hits,
                        )
                        fallback = next(job for job in fallback_jobs if job[0] == field)
                        results[field] = await llm.athink(fallback[2], stream=False)
                    yield _stream_event(
                        "field_done",
                        field=field,
                        message=f"{label}结构化抽取完成",
                        content=results[field],
                    )
                jobs = [(field, label, []) for field, label, _, _ in structured_jobs]
            else:
                jobs = _build_analysis_jobs(
                    sections,
                    global_context=global_context,
                    qualification_prefilter_sections=qualification_prefilter_hits,
                )

                stream_concurrency = max(1, int(os.getenv("LLM_STREAM_MAX_CONCURRENCY", "4")))
                stream_semaphore = asyncio.Semaphore(stream_concurrency)
                yield _stream_event(
                    "status",
                    message=f"正在提取四个专项模块（流式并发 {stream_concurrency} 路）...",
                )
                parallel_failed = False
                queue: asyncio.Queue[dict] = asyncio.Queue()

                async def run_stream_job(field: str, label: str, messages: list) -> None:
                    try:
                        await queue.put({"type": "status", "field": field, "message": f"正在提取{label}..."})
                        async with stream_semaphore:
                            async for chunk in llm.astream(messages):
                                results[field] += chunk
                                await queue.put({"type": "chunk", "field": field, "content": chunk})
                        await queue.put(
                            {
                                "type": "field_done",
                                "field": field,
                                "message": f"{label}提取完成",
                                "content": results[field],
                            }
                        )
                    except Exception as exc:
                        await queue.put(
                            {
                                "type": "parallel_error",
                                "field": field,
                                "message": str(exc) or exc.__class__.__name__,
                            }
                        )

                tasks = [
                    asyncio.create_task(run_stream_job(field, label, messages))
                    for field, label, messages in jobs
                ]
                pending_count = len(tasks)
                while pending_count:
                    event = await queue.get()
                    if event["type"] == "parallel_error":
                        parallel_failed = True
                        for task in tasks:
                            task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                        yield _stream_event(
                            "status",
                            message="流式提取失败，正在自动切换为非流式稳定提取...",
                        )
                        break

                    if event["type"] == "field_done":
                        pending_count -= 1

                    yield _stream_event(str(event.pop("type")), **event)

                if parallel_failed:
                    for field, _, _ in jobs:
                        results[field] = ""
                    for field, label, messages in jobs:
                        yield _stream_event("status", field=field, message=f"正在稳定提取{label}...")
                        try:
                            results[field] = await llm.athink(messages, stream=False)
                        except Exception as exc:
                            error_type, message, hint = _classify_exception(exc, stage=f"{label}提取")
                            results[field] = "\n".join(
                                [
                                    f"{label}提取失败。",
                                    f"错误类型：{error_type}",
                                    f"错误信息：{message}",
                                    f"排查建议：{hint}",
                                    "",
                                    "后端 traceback 摘要：",
                                    _exception_traceback_tail(exc),
                                ]
                            )
                        yield _stream_event(
                            "field_done",
                            field=field,
                            message=f"{label}提取完成" if not results[field].startswith(f"{label}提取失败。") else f"{label}提取失败",
                            content=results[field],
                        )

            results = _apply_local_module_fallbacks(
                results,
                sections,
                qualification_prefilter_hits,
            )
            results = clean_analysis_dict(results)
            for field, label, _ in jobs:
                if results.get(field):
                    yield _stream_event(
                        "field_done",
                        field=field,
                        message=f"{label}清洗去重完成",
                        content=results[field],
                    )

            current_stage = "图片解析阶段"
            try:
                image_items = await image_task
                image_analysis_markdown = format_image_analysis_markdown(image_items)
                image_analysis_items = [item.model_dump() for item in image_items]
            except Exception as exc:
                image_analysis_markdown = f"图片解析失败：{exc}"
                image_analysis_items = []
            image_count = len(image_analysis_items) or int(preflight_profile.get("image_count") or 0)
            image_ocr_chars = sum(len(str(item.get("ocr_text", ""))) for item in image_analysis_items)
            parse_quality = build_parse_quality_report(
                sections=sections,
                parse_method_used=parse_method_used,
                parse_method_recommended=parse_method_recommended,
                image_count=image_count,
                image_ocr_chars=image_ocr_chars,
                preflight_profile=preflight_profile,
            )
            results["image_analysis_markdown"] = image_analysis_markdown
            results["image_analysis_items"] = image_analysis_items
            results["parse_method_used"] = parse_method_used
            results["parse_method_recommended"] = parse_method_recommended
            results["preflight_profile"] = preflight_profile
            results["parse_quality"] = parse_quality
            results["sections"] = [section.model_dump() for section in sections]
            results["content_review_report"] = {}
            results["content_review_markdown"] = "内容审查尚未执行，请在前端点击“执行审查”。"
            _ensure_display_markdown_fields(results)
            try:
                db_result = save_analysis_result(
                    sections=results["sections"],
                    analysis=results,
                    file_name=filename,
                    document_type="招标文件",
                    parse_method=parse_method_used,
                )
                results["database_save"] = db_result
            except Exception as db_exc:
                results["database_save_error"] = str(db_exc)
            yield _stream_event(
                "image_analysis",
                message="图片解析和备注生成完成",
                content=image_analysis_markdown,
                items=image_analysis_items,
                parse_quality=parse_quality,
            )

            yield _stream_event("done", message="全部分析完成", result=results)
        except Exception as exc:
            error_type, message, hint = _classify_exception(exc, stage=current_stage)
            yield _stream_event(
                "error",
                error_type=error_type,
                message=message,
                hint=hint,
                traceback=_exception_traceback_tail(exc),
            )

    return StreamingResponse(
        event_generator(),
        media_type="application/x-ndjson; charset=utf-8",
    )


@router.post("/bid-documents/analyze-content-stream")
async def analyze_edited_content_stream(request: AnalyzeContentRequest) -> StreamingResponse:
    sections = split_bid_markdown_sections(request.file_content)

    async def event_generator() -> AsyncIterator[str]:
        current_stage = "大模型阶段"
        results = {
            "project_overview": "",
            "business_content": "",
            "technical_scoring_requirements": "",
            "qualification_compliance_requirements": "",
            "price_scoring_requirements": "",
        }
        try:
            yield _stream_event(
                "parsed",
                message=f"已接收修改后的解析内容，共 {len(sections)} 个章节，开始调用大模型...",
                sections=[section.model_dump() for section in sections],
            )
            llm = _build_llm(
                llm_vendor=request.llm_vendor,
                llm_model=request.llm_model,
                enable_deep_thinking=request.enable_deep_thinking,
            )
            yield _stream_event(
                "status",
                field="project_overview",
                message="正在生成项目画像和全文章节树...",
            )
            global_context, project_overview = await _build_global_context_async(llm, sections)
            results["project_overview"] = project_overview
            results["global_context_markdown"] = global_context
            yield _stream_event(
                "field_done",
                field="project_overview",
                message="项目画像和章节树生成完成",
                content=project_overview,
            )
            yield _stream_event(
                "status",
                field="qualification_compliance_requirements",
                message="正在用轻量模型逐章预筛疑似资格审查和废标段落...",
            )
            qualification_prefilter_hits = await _run_qualification_prefilter_async(
                sections=sections,
                llm_vendor=request.llm_vendor,
            )
            results["qualification_prefilter_count"] = len(qualification_prefilter_hits)
            if qualification_prefilter_hits:
                yield _stream_event(
                    "status",
                    field="qualification_compliance_requirements",
                    message=f"资格/废标预筛完成，命中 {len(qualification_prefilter_hits)} 个疑似片段，已并入精提取上下文。",
                )
            jobs = _build_analysis_jobs(
                sections,
                global_context=global_context,
                qualification_prefilter_sections=qualification_prefilter_hits,
            )
            stream_concurrency = max(1, int(os.getenv("LLM_STREAM_MAX_CONCURRENCY", "4")))
            stream_semaphore = asyncio.Semaphore(stream_concurrency)
            yield _stream_event(
                "status",
                message=f"正在提取四个专项模块（流式并发 {stream_concurrency} 路）...",
            )
            parallel_failed = False
            queue: asyncio.Queue[dict] = asyncio.Queue()

            async def run_stream_job(field: str, label: str, messages: list) -> None:
                try:
                    await queue.put(
                        {
                            "type": "status",
                            "field": field,
                            "message": f"正在提取{label}...",
                        }
                    )
                    async with stream_semaphore:
                        async for chunk in llm.astream(messages):
                            results[field] += chunk
                            await queue.put(
                                {
                                    "type": "chunk",
                                    "field": field,
                                    "content": chunk,
                                }
                            )
                    await queue.put(
                        {
                            "type": "field_done",
                            "field": field,
                            "message": f"{label}提取完成",
                            "content": results[field],
                        }
                    )
                except Exception as exc:
                    await queue.put(
                        {
                            "type": "parallel_error",
                            "field": field,
                            "message": str(exc) or exc.__class__.__name__,
                        }
                    )

            tasks = [
                asyncio.create_task(run_stream_job(field, label, messages))
                for field, label, messages in jobs
            ]
            pending_count = len(tasks)
            while pending_count:
                event = await queue.get()
                if event["type"] == "parallel_error":
                    parallel_failed = True
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    yield _stream_event(
                        "status",
                        message="流式提取失败，正在自动切换为非流式稳定提取...",
                    )
                    break
                if event["type"] == "field_done":
                    pending_count -= 1
                yield _stream_event(str(event.pop("type")), **event)

            if parallel_failed:
                for field, _, _ in jobs:
                    results[field] = ""
                for field, label, messages in jobs:
                    yield _stream_event("status", field=field, message=f"正在稳定提取{label}...")
                    try:
                        results[field] = await llm.athink(messages, stream=False)
                    except Exception as exc:
                        error_type, message, hint = _classify_exception(exc, stage=f"{label}提取")
                        results[field] = "\n".join(
                            [
                                f"{label}提取失败。",
                                f"错误类型：{error_type}",
                                f"错误信息：{message}",
                                f"排查建议：{hint}",
                                "",
                                "后端 traceback 摘要：",
                                _exception_traceback_tail(exc),
                            ]
                        )
                    yield _stream_event(
                        "field_done",
                        field=field,
                        message=f"{label}提取完成" if not results[field].startswith(f"{label}提取失败。") else f"{label}提取失败",
                        content=results[field],
                    )

            results = _apply_local_module_fallbacks(
                results,
                sections,
                qualification_prefilter_hits,
            )
            results = clean_analysis_dict(results)
            for field, label, _ in jobs:
                if results.get(field):
                    yield _stream_event(
                        "field_done",
                        field=field,
                        message=f"{label}清洗去重完成",
                        content=results[field],
                    )

            results["sections"] = [section.model_dump() for section in sections]
            results["content_review_report"] = {}
            results["content_review_markdown"] = "内容审查尚未执行，请在前端点击“执行审查”。"
            _ensure_display_markdown_fields(results)
            try:
                db_result = save_analysis_result(
                    sections=results["sections"],
                    analysis=results,
                    file_name="edited_content.md",
                    document_type="招标文件",
                    parse_method="edited_content",
                )
                results["database_save"] = db_result
            except Exception as db_exc:
                results["database_save_error"] = str(db_exc)
            yield _stream_event("done", message="修改内容分析完成", result=results)
        except Exception as exc:
            error_type, message, hint = _classify_exception(exc, stage=current_stage)
            yield _stream_event(
                "error",
                error_type=error_type,
                message=message,
                hint=hint,
                traceback=_exception_traceback_tail(exc),
            )

    return StreamingResponse(
        event_generator(),
        media_type="application/x-ndjson; charset=utf-8",
    )

