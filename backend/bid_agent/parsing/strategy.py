# -*- coding: utf-8 -*-
"""Parsing strategy and lightweight quality checks for bid documents."""

import re
import zipfile
import importlib.util
from pathlib import Path
from typing import Any, List, Optional

from bid_agent.parsing.document_parser import BidDocumentSection


PARSE_METHOD_LABELS = {
    "auto": "智能推荐解析",
    "mineru_vlm": "MinerU VLM 模型",
    "mineru_pipeline": "MinerU Pipeline 模型",
    "mineru_html": "MinerU-HTML 模型",
    "mineru_parallel_pages": "MinerU 并行页段",
    "pymupdf4llm": "PyMuPDF4LLM 快速 PDF",
    "docling": "Docling 结构化 PDF",
    "pdfplumber": "本地 pdfplumber PDF",
    "docx2python": "本地 docx2python Word",
    "docx2python_image_ocr": "本地 docx2python + OCR Word",
}


def inspect_document_profile(document: str, sample_pages: int = 5) -> dict:
    """Inspect cheap document signals before selecting an expensive parser."""
    path = Path(document)
    suffix = path.suffix.lower()
    profile: dict[str, Any] = {
        "document": document,
        "suffix": suffix,
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "page_count": None,
        "sample_pages": 0,
        "sample_text_chars": 0,
        "text_layer_pages": 0,
        "empty_text_pages": 0,
        "image_count": 0,
        "sample_table_count": 0,
        "pdf_type": "",
        "pdf_type_label": "",
        "parse_layers": [],
        "warnings": [],
    }

    if suffix == ".pdf":
        profile.update(_inspect_pdf_profile(path, sample_pages=sample_pages))
        profile.update(classify_pdf_profile(profile))
    elif suffix == ".docx":
        profile["image_count"] = count_docx_images(path)
        profile["sample_text_chars"] = _estimate_docx_text_chars(path)
    elif suffix == ".doc":
        profile["warnings"].append("旧版 .doc 文件需要本地 Word 转换或使用 MinerU 解析。")
    elif suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        profile["image_count"] = 1
        profile["warnings"].append("图片文件需要 OCR/视觉解析。")

    recommended = recommend_parse_method_from_profile(profile)
    profile["recommended_parse_method"] = recommended
    profile["recommended_parse_method_label"] = PARSE_METHOD_LABELS.get(recommended, recommended)
    return profile


def resolve_parse_method(document: str, parse_method: str) -> tuple[str, str]:
    if parse_method and parse_method != "auto":
        return parse_method, "用户手动选择"
    profile = inspect_document_profile(document)
    return profile["recommended_parse_method"], "系统根据文件类型和内容特征自动推荐"


def recommend_parse_method(document: str) -> str:
    return recommend_parse_method_from_profile(inspect_document_profile(document))


def recommend_parse_method_from_profile(profile: dict) -> str:
    suffix = str(profile.get("suffix") or "").lower()

    if suffix == ".docx":
        image_count = int(profile.get("image_count") or 0)
        text_chars = int(profile.get("sample_text_chars") or 0)
        if image_count >= 3 and text_chars < 1200:
            return "docx2python_image_ocr"
        return "docx2python_image_ocr" if image_count >= 8 else "docx2python"

    if suffix == ".doc":
        return "docx2python_image_ocr"

    if suffix == ".pdf":
        pdf_type = str(profile.get("pdf_type") or "")
        page_count = int(profile.get("page_count") or 0)

        if pdf_type == "scanned_pdf":
            return "mineru_parallel_pages" if page_count >= 30 else "mineru_vlm"
        if pdf_type == "mixed_pdf":
            return "mineru_parallel_pages"
        if pdf_type == "simple_text_pdf":
            return "pdfplumber"
        return "mineru_parallel_pages" if page_count >= 30 else "mineru_pipeline"

    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        return "mineru_vlm"

    return "mineru_vlm"


def count_docx_images(path: Path) -> int:
    if not path.exists() or path.suffix.lower() != ".docx":
        return 0
    try:
        with zipfile.ZipFile(path) as archive:
            return sum(
                1
                for name in archive.namelist()
                if name.startswith("word/media/") and not name.endswith("/")
            )
    except Exception:
        return 0


def build_parse_quality_report(
    sections: List[BidDocumentSection],
    parse_method_used: str,
    parse_method_recommended: Optional[str] = None,
    image_count: int = 0,
    image_ocr_chars: int = 0,
    preflight_profile: Optional[dict] = None,
) -> dict:
    markdown = "\n\n".join(section.markdown or section.content or "" for section in sections)
    text_chars = len(markdown.strip())
    section_count = len(sections)

    warnings = []
    score = 100
    if text_chars < 800:
        warnings.append("正文字符数偏少，可能存在扫描件、图片文字或解析遗漏。")
        score -= 35
    if section_count <= 1:
        warnings.append("章节数量偏少，章节切分可能不充分。")
        score -= 20
    if image_count and image_ocr_chars < 100:
        warnings.append("检测到图片，但 OCR 文字量较少，建议人工核对图片内容。")
        score -= 15
    if parse_method_used == "pdfplumber" and text_chars < 1500:
        warnings.append("PDF 文本解析结果偏少，如为扫描件建议改用 MinerU。")
        score -= 20
    if parse_method_used == "pymupdf4llm" and image_count:
        warnings.append("PyMuPDF4LLM 适合原生文本 PDF，含图内容建议核对图片解析模块。")
        score -= 10

    score = max(0, min(100, score))
    if score >= 80:
        level = "较好"
    elif score >= 55:
        level = "一般"
    else:
        level = "偏低"

    recommended = parse_method_recommended or parse_method_used
    return {
        "level": level,
        "score": score,
        "text_chars": text_chars,
        "section_count": section_count,
        "image_count": image_count,
        "image_ocr_chars": image_ocr_chars,
        "parse_method_used": parse_method_used,
        "parse_method_label": PARSE_METHOD_LABELS.get(parse_method_used, parse_method_used),
        "parse_method_recommended": recommended,
        "parse_method_recommended_label": PARSE_METHOD_LABELS.get(recommended, recommended),
        "preflight_profile": preflight_profile or {},
        "warnings": warnings,
    }


def _inspect_pdf_profile(path: Path, sample_pages: int = 5) -> dict:
    result = {
        "page_count": None,
        "sample_pages": 0,
        "sample_text_chars": 0,
        "text_layer_pages": 0,
        "empty_text_pages": 0,
        "image_count": 0,
        "sample_image_count": 0,
        "sample_table_count": 0,
    }
    if not path.exists():
        return result

    try:
        import pdfplumber
    except ImportError:
        result["warnings"] = ["未安装 pdfplumber，无法预检 PDF 文本层。"]
        return result

    try:
        with pdfplumber.open(path) as pdf:
            result["page_count"] = len(pdf.pages)
            selected_pages = pdf.pages[: max(1, sample_pages)]
            result["sample_pages"] = len(selected_pages)
            sample_page_count = len(selected_pages)
            for page_index, page in enumerate(pdf.pages, start=1):
                image_count = len(getattr(page, "images", []) or [])
                result["image_count"] += image_count
                if page_index <= sample_page_count:
                    text = page.extract_text() or ""
                    text_len = len(text.strip())
                    result["sample_text_chars"] += text_len
                    result["sample_image_count"] += image_count
                    try:
                        if page.extract_tables():
                            result["sample_table_count"] += 1
                    except Exception:
                        pass
                    if text_len:
                        result["text_layer_pages"] += 1
                    else:
                        result["empty_text_pages"] += 1
    except Exception as exc:
        result["warnings"] = [f"PDF 预检失败：{exc}"]
    return result


def classify_pdf_profile(profile: dict) -> dict:
    """Classify PDF before choosing the parser layer."""
    sample_pages = max(1, int(profile.get("sample_pages") or 1))
    sample_text_chars = int(profile.get("sample_text_chars") or 0)
    empty_text_pages = int(profile.get("empty_text_pages") or 0)
    image_count = int(profile.get("image_count") or 0)
    sample_image_count = int(profile.get("sample_image_count") or 0)
    text_chars_per_page = sample_text_chars / sample_pages

    if empty_text_pages >= sample_pages:
        pdf_type = "scanned_pdf"
        label = "扫描件 PDF"
        layers = ["解析层：OCR/多模态解析", "结构还原层：页码、标题、表格和图片说明"]
    elif image_count or sample_image_count:
        pdf_type = "mixed_pdf"
        label = "图文混排 PDF"
        layers = ["解析层：多模态解析", "结构还原层：页码、标题、章节、表格、图片说明"]
    else:
        if (
            text_chars_per_page >= 300
            and int(profile.get("sample_table_count") or 0) == 0
            and int(profile.get("page_count") or 0) <= 20
        ):
            pdf_type = "simple_text_pdf"
            label = "极简纯文本 PDF"
            layers = ["解析层：pdfplumber 轻量文本抽取", "结构还原层：标题、段落"]
        else:
            pdf_type = "native_text_pdf"
            label = "原生复杂 PDF"
            layers = ["解析层：MinerU 结构化解析", "结构还原层：页码、标题、章节、段落、表格"]
        if text_chars_per_page < 80:
            profile.setdefault("warnings", []).append("PDF 样本页文本较少，可能是封面/目录或文本层质量偏低。")

    return {
        "pdf_type": pdf_type,
        "pdf_type_label": label,
        "parse_layers": layers,
    }


def _estimate_docx_text_chars(path: Path) -> int:
    if not path.exists() or path.suffix.lower() != ".docx":
        return 0
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
    except Exception:
        return 0
    text = re.sub(r"<[^>]+>", "", xml)
    return len(text.strip())


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None
