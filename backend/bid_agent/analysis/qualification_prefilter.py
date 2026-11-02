# -*- coding: utf-8 -*-
"""Lightweight LLM prefilter for qualification and rejection clauses."""
from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, Iterable, Sequence

from bid_agent.parsing.document_parser import BidDocumentSection
from bid_agent.rag.section_retriever import retrieve_sections_for_module
from bid_agent.infrastructure.llm_client import LLM_Invoke


PREFILTER_SYSTEM_PROMPT = """你是招投标文件资格审查/废标条款预筛助手。
你的任务不是精提取，而是从候选段落中标记哪些段落疑似包含：
1. 资格要求、资格性审查、资格证明材料；
2. 符合性审查、响应性审查、初步审查；
3. 废标、否决投标、无效投标、重大偏差、一票否决条款。

必须严格输出 JSON，不要输出 Markdown、解释或代码块：
{
  "hits": [
    {
      "chunk_id": "S1-C1",
      "category": "qualification|compliance|rejection|both|none",
      "confidence": 0.0,
      "reason": "命中的简短原因",
      "evidence_keywords": ["原文关键词"]
    }
  ]
}

判定原则：
- 宁可多标一点，也不要漏掉可能导致资格不通过或废标的段落。
- 只有完全无关的段落才标记 none。
- evidence_keywords 必须来自原文。
"""


PREFILTER_USER_TEMPLATE = """请预筛以下段落，标出疑似资格审查、符合性审查和废标/否决投标段落。

{chunks_text}"""


def qualification_prefilter_enabled() -> bool:
    return os.getenv("BID_QUAL_PREFILTER_ENABLED", "true").lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def build_qualification_prefilter_chunks(
    sections: Sequence[BidDocumentSection],
    *,
    max_chunks: int | None = None,
    chunk_chars: int | None = None,
) -> list[dict[str, Any]]:
    """Rule-recall likely sections, then split them for lightweight review."""
    max_chunks = max_chunks or int(os.getenv("BID_QUAL_PREFILTER_MAX_CHUNKS", "48"))
    chunk_chars = chunk_chars or int(os.getenv("BID_QUAL_PREFILTER_CHUNK_CHARS", "4500"))
    candidate_sections = _rule_recall_qualification_sections(sections)
    chunks: list[dict[str, Any]] = []
    for section in candidate_sections:
        text = _section_text(section)
        if not text:
            continue
        windows = _split_text_windows(text, chunk_chars)
        for window_index, window in enumerate(windows, start=1):
            chunk_id = f"S{section.index}-C{window_index}"
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "section_index": section.index,
                    "section_title": section.title,
                    "section_level": section.level,
                    "content": window,
                }
            )
            if len(chunks) >= max_chunks:
                return chunks
    return chunks


def _rule_recall_qualification_sections(
    sections: Sequence[BidDocumentSection],
) -> list[BidDocumentSection]:
    if os.getenv("BID_QUAL_PREFILTER_RULE_RECALL_ENABLED", "true").lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        return list(sections)

    max_chars = int(os.getenv("BID_QUAL_PREFILTER_RULE_MAX_CHARS", "30000"))
    context_chars = int(os.getenv("BID_QUAL_PREFILTER_RULE_CONTEXT_CHARS", "3600"))
    recalled = retrieve_sections_for_module(
        "qualification_compliance",
        sections,
        context_chars=context_chars,
        max_chars=max_chars,
        neighbor_sections=1,
    )
    return recalled or list(sections)


async def prefilter_qualification_sections(
    sections: Sequence[BidDocumentSection],
    llm: LLM_Invoke,
) -> list[BidDocumentSection]:
    """Ask a lightweight model to mark likely qualification/rejection chunks."""
    if not qualification_prefilter_enabled():
        return []
    chunks = build_qualification_prefilter_chunks(sections)
    if not chunks:
        return []

    batch_size = int(os.getenv("BID_QUAL_PREFILTER_BATCH_SIZE", "6"))
    max_concurrency = int(os.getenv("BID_QUAL_PREFILTER_CONCURRENCY", "2"))
    confidence_threshold = float(os.getenv("BID_QUAL_PREFILTER_CONFIDENCE", "0.45"))
    batches = [chunks[index : index + batch_size] for index in range(0, len(chunks), batch_size)]
    semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def run_batch(batch: list[dict[str, Any]]) -> dict[str, Any]:
        async with semaphore:
            return _parse_prefilter_response(
                await llm.athink(_build_prefilter_messages(batch), stream=False)
            )

    responses = await asyncio.gather(*(run_batch(batch) for batch in batches), return_exceptions=True)
    hit_by_id: dict[str, dict[str, Any]] = {}
    for response in responses:
        if isinstance(response, Exception):
            continue
        for hit in response.get("hits", []):
            if not isinstance(hit, dict):
                continue
            chunk_id = str(hit.get("chunk_id") or "").strip()
            category = str(hit.get("category") or "none").strip().lower()
            confidence = _safe_float(hit.get("confidence"))
            if chunk_id and category != "none" and confidence >= confidence_threshold:
                hit_by_id[chunk_id] = hit

    output: list[BidDocumentSection] = []
    for chunk in chunks:
        hit = hit_by_id.get(chunk["chunk_id"])
        if not hit:
            continue
        reason = str(hit.get("reason") or "").strip()
        category = str(hit.get("category") or "").strip()
        keywords = hit.get("evidence_keywords") or []
        if isinstance(keywords, list):
            keyword_text = "、".join(str(item) for item in keywords if str(item).strip())
        else:
            keyword_text = str(keywords)
        title = (
            f"轻量模型预筛 - {category} - 原章节{chunk['section_index']}: "
            f"{chunk['section_title']}"
        )
        prefix = "\n".join(
            item
            for item in [
                f"预筛类别：{category}",
                f"预筛理由：{reason}" if reason else "",
                f"证据关键词：{keyword_text}" if keyword_text else "",
            ]
            if item
        )
        content = f"{prefix}\n\n{chunk['content']}".strip()
        output.append(
            BidDocumentSection(
                index=len(output) + 1,
                title=title,
                level=int(chunk.get("section_level") or 2),
                content=content,
                markdown=f"## {title}\n\n{content}",
            )
        )
    return output


def prefilter_qualification_sections_sync(
    sections: Sequence[BidDocumentSection],
    llm: LLM_Invoke,
) -> list[BidDocumentSection]:
    return asyncio.run(prefilter_qualification_sections(sections, llm))


def merge_qualification_prefilter_sections(
    base_sections: Sequence[BidDocumentSection],
    prefilter_sections: Sequence[BidDocumentSection],
    *,
    max_total: int | None = None,
) -> list[BidDocumentSection]:
    """Put prefilter hits before normal recall results and dedupe by content."""
    max_total = max_total or int(os.getenv("BID_QUAL_PREFILTER_MERGE_MAX", "20"))
    output: list[BidDocumentSection] = []
    seen: set[str] = set()
    for section in [*prefilter_sections, *base_sections]:
        key = _normalize(section.content or section.markdown or section.title)
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(section)
        if len(output) >= max_total:
            break
    return output


def _build_prefilter_messages(chunks: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    chunk_blocks = []
    for chunk in chunks:
        chunk_blocks.append(
            "\n".join(
                [
                    f"### chunk_id: {chunk['chunk_id']}",
                    f"章节：{chunk['section_title']}",
                    str(chunk["content"]),
                ]
            )
        )
    return [
        {"role": "system", "content": PREFILTER_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": PREFILTER_USER_TEMPLATE.format(chunks_text="\n\n".join(chunk_blocks)),
        },
    ]


def _parse_prefilter_response(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {"hits": []}
    except Exception:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return {"hits": []}
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else {"hits": []}
        except Exception:
            return {"hits": []}


def _section_text(section: BidDocumentSection) -> str:
    text = section.markdown or section.content or ""
    title = section.title or ""
    return f"{title}\n\n{text}".strip()


def _split_text_windows(text: str, chunk_chars: int) -> list[str]:
    text = (text or "").strip()
    if len(text) <= chunk_chars:
        return [text] if text else []
    paragraphs = [item.strip() for item in re.split(r"\n{2,}", text) if item.strip()]
    windows: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > chunk_chars:
            if current:
                windows.append(current)
                current = ""
            for start in range(0, len(paragraph), chunk_chars):
                windows.append(paragraph[start : start + chunk_chars])
            continue
        if len(current) + len(paragraph) + 2 > chunk_chars:
            if current:
                windows.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}".strip()
    if current:
        windows.append(current)
    return windows


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _normalize(text: str) -> str:
    value = re.sub(r"\s+", "", str(text or ""))
    value = re.sub(r"[，,。；;：:、|/\\（）()\[\]【】《》\"'“”‘’`]+", "", value)
    return value[:400].lower()
