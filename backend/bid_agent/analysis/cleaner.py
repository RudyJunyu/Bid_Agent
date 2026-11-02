# -*- coding: utf-8 -*-
"""Post-process LLM extraction text before display and persistence."""

from __future__ import annotations

import re
from typing import Any


EXTRACTION_TEXT_FIELDS = (
    "project_overview",
    "business_content",
    "technical_scoring_requirements",
    "qualification_compliance_requirements",
    "price_scoring_requirements",
)


def clean_analysis_dict(analysis: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(analysis or {})
    for field in EXTRACTION_TEXT_FIELDS:
        if isinstance(cleaned.get(field), str):
            cleaned[field] = clean_repeated_extraction_text(cleaned[field])
    return cleaned


def clean_repeated_extraction_text(text: str) -> str:
    text = str(text or "").strip()
    if not text:
        return ""
    if _looks_like_markdown_table(text):
        return _dedupe_markdown_table_rows(text)
    return _dedupe_markdown_blocks(text)


def normalize_for_dedupe(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"^[#*\-\d.、\s]+", "", value)
    value = re.sub(r"\*\*(.*?)\*\*", r"\1", value)
    value = re.sub(r"[《》\"'“”‘’`]", "", value)
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"[，,。；;：:、|/\\（）()\[\]【】]+", "", value)
    value = re.sub(r"^(投标人|供应商|投标人需|供应商需|需|应|须|必须|提供)+", "", value)
    return value.lower()


def is_duplicate_text(text: str, seen: set[str], min_key_len: int = 8) -> bool:
    key = normalize_for_dedupe(text)
    if len(key) < min_key_len:
        return False
    if key in seen:
        return True
    seen.add(key)
    return False


def _looks_like_markdown_table(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return len([line for line in lines if line.startswith("|") and line.endswith("|")]) >= 2


def _dedupe_markdown_table_rows(text: str) -> str:
    output = []
    seen_rows: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            output.append(line)
            continue
        if re.match(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$", stripped):
            output.append(line)
            continue
        cells = [cell.strip() for cell in stripped.split("|")[1:-1]]
        key = normalize_for_dedupe(" ".join(cells))
        if key and key in seen_rows:
            continue
        if key:
            seen_rows.add(key)
        output.append(line)
    return "\n".join(output).strip()


def _dedupe_markdown_blocks(text: str) -> str:
    output = []
    seen: set[str] = set()
    seen_materials: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if output and output[-1] != "":
                output.append("")
            continue
        if stripped.startswith("#") or re.match(r"^[一二三四五六七八九十]+[、.．]", stripped):
            output.append(line)
            continue
        parts = _split_repetitive_sentence(stripped)
        if len(parts) <= 1:
            if not _is_duplicate_part(stripped, seen, seen_materials):
                output.append(line)
            continue
        kept = [part for part in parts if not _is_duplicate_part(part, seen, seen_materials)]
        if kept:
            prefix = "- " if stripped.startswith(("-", "*", "+")) else ""
            output.extend(f"{prefix}{part}" for part in kept)
    return "\n".join(output).strip()


def _is_duplicate_part(part: str, seen: set[str], seen_materials: set[str]) -> bool:
    materials = _extract_material_names(part)
    if materials and all(material in seen_materials for material in materials):
        return True
    if is_duplicate_text(part, seen):
        return True
    seen_materials.update(materials)
    return False


def _extract_material_names(text: str) -> set[str]:
    names = {name.strip() for name in re.findall(r"《([^》]{2,80})》", str(text or ""))}
    return {name for name in names if name}


def _split_repetitive_sentence(line: str) -> list[str]:
    clean = re.sub(r"^[-*+]\s*", "", line.strip())
    parts = [
        part.strip()
        for part in re.split(r"[；;。]\s*", clean)
        if len(part.strip()) >= 4
    ]
    return parts if len(parts) >= 3 else [line.strip()]
