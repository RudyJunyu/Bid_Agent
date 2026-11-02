# 这个脚本负责提取招标文件里的图片，并给每张图片生成 OCR 文本和 AI 备注。
# -*- coding: utf-8 -*-
import asyncio
import base64
import mimetypes
import zipfile
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List, Optional

from pydantic import BaseModel, Field

from bid_agent.parsing.document_parser import parse_document_to_markdown
from bid_agent.parsing.strategy import resolve_parse_method
from bid_agent.infrastructure.llm_client import LLM_Invoke


class BidImageAnalysisItem(BaseModel):
    image_id: str = Field(default="", description="Stable image id for metadata and future multimodal embedding.")
    index: int = Field(description="Image order in the document.")
    source: str = Field(description="Image source path inside the document.")
    file_name: str = Field(description="Extracted image file name.")
    image_data_url: str = Field(default="", description="Base64 data URL for image preview.")
    thumbnail_data_url: str = Field(default="", description="Compressed thumbnail data URL for lightweight preview.")
    image_ref: str = Field(default="", description="Local image file reference.")
    has_multimodal_embedding: bool = Field(default=False, description="Whether image embedding has been generated.")
    ocr_text: str = Field(description="OCR text extracted from the image.")
    ai_note: str = Field(description="LLM generated note for the image.")


def extract_document_images(document: str, output_dir: str) -> List[Path]:
    path = Path(document).expanduser().resolve()
    target_dir = Path(output_dir).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    if path.suffix.lower() == ".docx":
        return _extract_docx_images(path, target_dir)
    if path.suffix.lower() == ".pdf":
        return _extract_pdf_images(path, target_dir)
    return []


async def analyze_document_images(
    document: str,
    llm: LLM_Invoke,
    parse_method: str = "docx2python",
    model_version: Optional[str] = None,
    language: str = "ch",
    is_ocr: Optional[bool] = None,
    enable_formula: bool = True,
    enable_table: bool = True,
    page_ranges: Optional[str] = None,
    max_concurrency: int = 4,
) -> List[BidImageAnalysisItem]:
    with TemporaryDirectory() as temp_dir:
        image_dir = Path(temp_dir) / "images"
        image_paths = extract_document_images(document, str(image_dir))
        if not image_paths:
            return []

        resolved_parse_method, _ = resolve_parse_method(document, parse_method)
        if Path(document).suffix.lower() == ".pdf":
            context_parse_method = "pdfplumber"
        else:
            context_parse_method = (
                "docx2python"
                if resolved_parse_method == "docx2python_image_ocr"
                else resolved_parse_method
            )
        try:
            context = parse_document_to_markdown(
                document=document,
                output_dir=None,
                parse_method=context_parse_method,
                model_version=model_version,
                language=language,
                is_ocr=is_ocr,
                enable_formula=enable_formula,
                enable_table=enable_table,
                page_ranges=page_ranges,
            )[:12000]
        except Exception:
            context = ""

        semaphore = asyncio.Semaphore(max_concurrency)

        async def run_one(index: int, image_path: Path) -> BidImageAnalysisItem:
            async with semaphore:
                ocr_text = _ocr_image(image_path)
                ai_note = await _annotate_image(
                    llm=llm,
                    image_path=image_path,
                    index=index,
                    context=context,
                    ocr_text=ocr_text,
                )
                return BidImageAnalysisItem(
                    image_id=f"img_{index:04d}",
                    index=index,
                    source=image_path.name,
                    file_name=image_path.name,
                    image_data_url=_image_to_data_url(image_path),
                    thumbnail_data_url=_image_to_thumbnail_data_url(image_path),
                    image_ref=str(image_path),
                    has_multimodal_embedding=False,
                    ocr_text=ocr_text,
                    ai_note=ai_note,
                )

        return await asyncio.gather(
            *(run_one(index, image_path) for index, image_path in enumerate(image_paths, start=1))
        )


def format_image_analysis_markdown(items: List[BidImageAnalysisItem]) -> str:
    if not items:
        return "未提取到图片。"

    blocks = []
    for item in items:
        blocks.append(
            "\n".join(
                [
                    f"## 图片 {item.index}",
                    f"- ID：{item.image_id}",
                    f"- 文件：{item.file_name}",
                    f"- 位置：{item.source}",
                    f"- 多模态向量：{'已生成' if item.has_multimodal_embedding else '未生成'}",
                    "",
                    f"![图片 {item.index}]({item.thumbnail_data_url or item.image_data_url})",
                    "",
                    "### OCR文本",
                    item.ocr_text or "未识别到文字。",
                    "",
                    "### AI备注",
                    item.ai_note or "未生成备注。",
                ]
            )
        )
    return "\n\n".join(blocks)


def _extract_docx_images(path: Path, output_dir: Path) -> List[Path]:
    image_paths = []
    with zipfile.ZipFile(path) as archive:
        image_names = [
            name
            for name in archive.namelist()
            if name.startswith("word/media/") and not name.endswith("/")
        ]
        for index, name in enumerate(image_names, start=1):
            suffix = Path(name).suffix or ".png"
            target_path = output_dir / f"image_{index:03d}{suffix}"
            target_path.write_bytes(archive.read(name))
            image_paths.append(target_path)
    return image_paths


def _extract_pdf_images(path: Path, output_dir: Path) -> List[Path]:
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader
        except ImportError:
            return []

    image_paths: List[Path] = []
    try:
        reader = PdfReader(str(path))
        for page_index, page in enumerate(reader.pages, start=1):
            for image_index, image in enumerate(getattr(page, "images", []) or [], start=1):
                name = getattr(image, "name", "") or f"image_{image_index}.png"
                suffix = Path(name).suffix or ".png"
                target_path = output_dir / f"pdf_page_{page_index:04d}_image_{image_index:03d}{suffix}"
                data = getattr(image, "data", None)
                if not data:
                    continue
                target_path.write_bytes(data)
                image_paths.append(target_path)
    except Exception:
        return image_paths
    return image_paths


def _ocr_image(image_path: Path) -> str:
    rapidocr_text = _ocr_image_with_rapidocr(image_path)
    if rapidocr_text:
        return rapidocr_text

    try:
        from PIL import Image
        import pytesseract
    except ImportError:
        return "本地 OCR Python 依赖未安装，未执行图片文字识别。"

    try:
        with Image.open(image_path) as image:
            return pytesseract.image_to_string(image, lang="chi_sim+eng").strip()
    except Exception as exc:
        return f"OCR识别失败：{exc}。建议安装 RapidOCR 或 Tesseract OCR 引擎。"


def _ocr_image_with_rapidocr(image_path: Path) -> str:
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return ""

    try:
        engine = RapidOCR()
        result, _ = engine(str(image_path))
        if not result:
            return ""
        return "\n".join(item[1] for item in result if len(item) > 1 and item[1]).strip()
    except Exception:
        return ""


async def _annotate_image(
    llm: LLM_Invoke,
    image_path: Path,
    index: int,
    context: str,
    ocr_text: str,
) -> str:
    messages = [
        {
            "role": "system",
            "content": (
                "你是专业的招标文件分析师。请结合招标文件上下文和图片 OCR 文本，"
                "给图片生成简洁备注。备注要说明图片可能对应的章节、用途、关键信息。"
                "不要编造无法从上下文或 OCR 文本判断的内容。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"招标文件上下文节选：\n{context}\n\n"
                f"图片编号：{index}\n"
                f"图片文件名：{image_path.name}\n"
                f"OCR文本：\n{ocr_text or '未识别到文字'}\n\n"
                "请为这张图片生成备注。"
            ),
        },
    ]
    try:
        return await llm.athink(messages, stream=False)
    except Exception as exc:
        return f"AI备注生成失败：{exc}"


def _image_to_data_url(image_path: Path) -> str:
    mime_type = mimetypes.guess_type(str(image_path))[0] or "image/png"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _image_to_thumbnail_data_url(image_path: Path, max_size: int = 512, quality: int = 75) -> str:
    try:
        from PIL import Image
    except ImportError:
        return _image_to_data_url(image_path)

    try:
        with Image.open(image_path) as image:
            image.thumbnail((max_size, max_size))
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            buffer = BytesIO()
            image.save(buffer, format="JPEG", quality=quality, optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"
    except Exception:
        return _image_to_data_url(image_path)
