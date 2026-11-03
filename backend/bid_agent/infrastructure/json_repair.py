"""Lightweight JSON extraction and repair for LLM chat outputs."""
from __future__ import annotations

import json
import re
from typing import Any, Callable


class JsonRepairError(ValueError):
    """Raised when no repair strategy yields valid JSON."""


def extract_json_text(text: str) -> str:
    if not text or not text.strip():
        return text or ''
    cleaned = re.sub(r'<think.*?</think\s*>', '', text, flags=re.DOTALL | re.IGNORECASE)
    fenced = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', cleaned, re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    return cleaned.strip()


def _balanced_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    for open_char, close_char in (('{', '}'), ('[', ']')):
        stack: list[str] = []
        start = -1
        for index, char in enumerate(text):
            if char == open_char:
                if not stack:
                    start = index
                stack.append(char)
            elif char == close_char and stack and stack[-1] == open_char:
                stack.pop()
                if not stack and start >= 0:
                    candidates.append(text[start:index + 1])
    return candidates


def _repair_invalid_escapes(text: str) -> str:
    return re.sub(r'\\([.#$&*+<>?@^`|~])', r'\1', text)


def _try_parse(text: str) -> Any | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def repair_json(
    raw_text: str,
    *,
    repair_chat_fn: Callable[[str], str] | None = None,
    max_llm_attempts: int = 1,
) -> Any:
    """Parse model output into dict/list with deterministic repairs, optional LLM fallback."""
    text = extract_json_text(raw_text)
    parsed = _try_parse(text)
    if parsed is not None:
        return parsed

    candidates = [text, _repair_invalid_escapes(text), *_balanced_candidates(text)]
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        for variant in (candidate, _repair_invalid_escapes(candidate)):
            parsed = _try_parse(variant)
            if parsed is not None:
                return parsed

    last_error = 'unable to parse JSON'
    if repair_chat_fn and max_llm_attempts > 0:
        for _ in range(max_llm_attempts):
            repaired = repair_chat_fn(
                '请把下面内容修复为合法 JSON，只输出 JSON，不要解释：\n'
                + text[:12000]
            )
            repaired_text = extract_json_text(repaired)
            parsed = _try_parse(repaired_text)
            if parsed is not None:
                return parsed
            for candidate in _balanced_candidates(repaired_text):
                parsed = _try_parse(candidate)
                if parsed is not None:
                    return parsed
            last_error = 'LLM repair did not yield valid JSON'

    raise JsonRepairError(last_error)
