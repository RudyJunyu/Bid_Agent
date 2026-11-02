# 这个脚本负责调用 MinerU 把 PDF 等文件解析成可分析的文本。
''' MinerU PDF Parse Tool '''

import os
import time
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, Optional

import requests
from bid_agent.core import settings  # Load the project environment once.




BASE_URL = "https://mineru.net/api/v4"
DEFAULT_MODEL_VERSION = "vlm"
DONE_STATE = "done"
FAILED_STATE = "failed"
SUPPORTED_DOCUMENT_SUFFIXES = {
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".png",
    ".jpg",
    ".jpeg",
    ".jp2",
    ".webp",
    ".gif",
    ".bmp",
    ".html",
}


def mineru_parse_document(
    document: str,
    output_dir: Optional[str] = None,
    model_version: str = DEFAULT_MODEL_VERSION,
    language: str = "ch",
    is_ocr: bool = False,
    enable_formula: bool = True,
    enable_table: bool = True,
    page_ranges: Optional[str] = None,
    poll_interval: int = 5,
    timeout: int = 600,
) -> str:
    """Parse a local document path or remote document URL with MinerU."""
    document = document.strip()
    if document.startswith(("http://", "https://")):
        return mineru_parse_document_url(
            document_url=document,
            output_dir=output_dir,
            model_version=model_version,
            language=language,
            is_ocr=is_ocr,
            enable_formula=enable_formula,
            enable_table=enable_table,
            page_ranges=page_ranges,
            poll_interval=poll_interval,
            timeout=timeout,
        )

    return mineru_parse_document_file(
        file_path=document,
        output_dir=output_dir,
        model_version=model_version,
        language=language,
        is_ocr=is_ocr,
        enable_formula=enable_formula,
        enable_table=enable_table,
        page_ranges=page_ranges,
        poll_interval=poll_interval,
        timeout=timeout,
    )


def mineru_parse_pdf(
    pdf: str,
    output_dir: Optional[str] = None,
    model_version: str = DEFAULT_MODEL_VERSION,
    language: str = "ch",
    is_ocr: bool = False,
    enable_formula: bool = True,
    enable_table: bool = True,
    page_ranges: Optional[str] = None,
    poll_interval: int = 5,
    timeout: int = 600,
) -> str:
    """Parse a local PDF path or remote PDF URL with MinerU and return Markdown."""
    return mineru_parse_document(
        document=pdf,
        output_dir=output_dir,
        model_version=model_version,
        language=language,
        is_ocr=is_ocr,
        enable_formula=enable_formula,
        enable_table=enable_table,
        page_ranges=page_ranges,
        poll_interval=poll_interval,
        timeout=timeout,
    )


def mineru_parse_document_url(
    document_url: str,
    output_dir: Optional[str] = None,
    model_version: str = DEFAULT_MODEL_VERSION,
    language: str = "ch",
    is_ocr: bool = False,
    enable_formula: bool = True,
    enable_table: bool = True,
    page_ranges: Optional[str] = None,
    poll_interval: int = 5,
    timeout: int = 600,
) -> str:
    """Submit a remote document URL to MinerU and return parsed Markdown."""
    payload: Dict[str, Any] = {
        "url": document_url,
        "model_version": model_version,
        "language": language,
        "is_ocr": is_ocr,
        "enable_formula": enable_formula,
        "enable_table": enable_table,
    }
    if page_ranges:
        payload["page_ranges"] = page_ranges

    response = requests.post(
        f"{BASE_URL}/extract/task",
        headers=_auth_headers(),
        json=payload,
        timeout=_request_timeout(),
    )
    result = _json_response(response)
    task_id = result["data"]["task_id"]
    task_result = _poll_task(task_id, poll_interval=poll_interval, timeout=timeout)
    return _download_markdown_from_zip(task_result["full_zip_url"], output_dir=output_dir)


def mineru_parse_pdf_url(pdf_url: str, **kwargs: Any) -> str:
    """Backward-compatible alias for URL parsing."""
    return mineru_parse_document_url(document_url=pdf_url, **kwargs)


def mineru_parse_document_file(
    file_path: str,
    output_dir: Optional[str] = None,
    model_version: str = DEFAULT_MODEL_VERSION,
    language: str = "ch",
    is_ocr: bool = False,
    enable_formula: bool = True,
    enable_table: bool = True,
    page_ranges: Optional[str] = None,
    poll_interval: int = 5,
    timeout: int = 600,
) -> str:
    """Upload a local document to MinerU by signed URL and return parsed Markdown."""
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Document file not found: {path}")
    if path.suffix.lower() not in SUPPORTED_DOCUMENT_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_DOCUMENT_SUFFIXES))
        raise ValueError(f"Unsupported document type: {path.suffix}. Supported: {supported}")

    file_item: Dict[str, Any] = {
        "name": path.name,
        "is_ocr": is_ocr,
    }
    if page_ranges:
        file_item["page_ranges"] = page_ranges

    payload = {
        "files": [file_item],
        "model_version": model_version,
        "language": language,
        "enable_formula": enable_formula,
        "enable_table": enable_table,
    }
    response = requests.post(
        f"{BASE_URL}/file-urls/batch",
        headers=_auth_headers(),
        json=payload,
        timeout=_request_timeout(),
    )
    result = _json_response(response)
    batch_id = result["data"]["batch_id"]
    upload_url = result["data"]["file_urls"][0]

    with path.open("rb") as file_obj:
        upload_response = requests.put(upload_url, data=file_obj, timeout=_request_timeout())
    if upload_response.status_code not in (200, 201, 204):
        raise RuntimeError(
            f"MinerU upload failed: status={upload_response.status_code}, "
            f"body={upload_response.text[:500]}"
        )

    batch_result = _poll_batch(batch_id, poll_interval=poll_interval, timeout=timeout)
    return _download_markdown_from_zip(batch_result["full_zip_url"], output_dir=output_dir)


def mineru_parse_pdf_file(file_path: str, **kwargs: Any) -> str:
    """Backward-compatible alias for local file parsing."""
    return mineru_parse_document_file(file_path=file_path, **kwargs)


def _poll_task(task_id: str, poll_interval: int, timeout: int) -> Dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = requests.get(
            f"{BASE_URL}/extract/task/{task_id}",
            headers=_auth_headers(),
            timeout=_request_timeout(),
        )
        result = _json_response(response)
        data = result["data"]
        state = data.get("state")
        if state == DONE_STATE:
            return data
        if state == FAILED_STATE:
            raise RuntimeError(f"MinerU parse failed: {data.get('err_msg') or data}")
        time.sleep(poll_interval)

    raise TimeoutError(f"MinerU parse timed out after {timeout}s, task_id={task_id}")


def _poll_batch(batch_id: str, poll_interval: int, timeout: int) -> Dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = requests.get(
            f"{BASE_URL}/extract-results/batch/{batch_id}",
            headers=_auth_headers(),
            timeout=_request_timeout(),
        )
        result = _json_response(response)
        extract_result = result["data"].get("extract_result", [])
        if not extract_result:
            time.sleep(poll_interval)
            continue

        data = extract_result[0]
        state = data.get("state")
        if state == DONE_STATE:
            return data
        if state == FAILED_STATE:
            raise RuntimeError(f"MinerU parse failed: {data.get('err_msg') or data}")
        time.sleep(poll_interval)

    raise TimeoutError(f"MinerU parse timed out after {timeout}s, batch_id={batch_id}")


def _download_markdown_from_zip(full_zip_url: str, output_dir: Optional[str]) -> str:
    response = requests.get(full_zip_url, timeout=_request_timeout())
    if response.status_code != 200:
        raise RuntimeError(
            f"MinerU result download failed: status={response.status_code}, "
            f"body={response.text[:500]}"
        )

    if output_dir:
        target_dir = Path(output_dir).expanduser().resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        zip_path = target_dir / "mineru_result.zip"
        zip_path.write_bytes(response.content)
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(target_dir)
            markdown_name = _find_markdown_name(archive)
            return (target_dir / markdown_name).read_text(encoding="utf-8")

    with TemporaryDirectory() as temp_dir:
        zip_path = Path(temp_dir) / "mineru_result.zip"
        zip_path.write_bytes(response.content)
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(temp_dir)
            markdown_name = _find_markdown_name(archive)
            return (Path(temp_dir) / markdown_name).read_text(encoding="utf-8")


def _find_markdown_name(archive: zipfile.ZipFile) -> str:
    names = archive.namelist()
    for name in names:
        if name.endswith("full.md"):
            return name
    for name in names:
        if name.lower().endswith(".md"):
            return name
    raise RuntimeError("MinerU result zip does not contain a Markdown file.")


def _auth_headers() -> Dict[str, str]:
    token = os.getenv("MINERU_API_TOKEN") or os.getenv("MINERU_TOKEN")
    if not token:
        raise ValueError("Please set MINERU_API_TOKEN in .env before calling MinerU.")
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }


def _json_response(response: requests.Response) -> Dict[str, Any]:
    try:
        result = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"MinerU returned non-JSON response: status={response.status_code}, "
            f"body={response.text[:500]}"
        ) from exc

    if response.status_code != 200 or result.get("code") != 0:
        raise RuntimeError(
            f"MinerU API error: status={response.status_code}, "
            f"code={result.get('code')}, msg={result.get('msg')}"
        )
    return result


def _request_timeout() -> int:
    return int(os.getenv("MINERU_REQUEST_TIMEOUT", "60"))
