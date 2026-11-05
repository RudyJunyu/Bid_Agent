# -*- coding: utf-8 -*-
"""Pre/post Markdown normalize: headers/footers, TOC, attachment-table noise."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from bid_agent.parsing.document_parser import BidDocumentSection

PAGE_COMMENT_RE = re.compile(r"<!--\s*page:(\d+)\s*-->", re.IGNORECASE)
PAGE_FOOTER_RE = re.compile(
    r"^(?:"
    r"第\s*\d+\s*页\s*/\s*共\s*\d+\s*页"
    r"|第\s*\d+\s*页\s*共\s*\d+\s*页"
    r"|第\s*\d+\s*页"
    r"|\d+\s*/\s*\d+"
    r")\s*$"
)
TOC_TITLE_RE = re.compile(r"^目\s*录$|^文件目录$|^招标文件目录$")
CHAPTER_TITLE_RE = re.compile(
    r"^第[一二三四五六七八九十百千万零〇\d]+[章节篇部分][\s、：:.-]*.+"
)
CHINESE_ORDER_TITLE_RE = re.compile(
    r"^[一二三四五六七八九十百千万零〇]+[、.．]\s*.+"
)
# Only real attachment headings ("一、投标人须知前附表"), not "……前附表规定的……".
FRONT_TABLE_HEADING_RE = re.compile(
    r"^(?:[一二三四五六七八九十百千万零〇\d]+[、.．]\s*)?(?:投标人须知|采购需求)?前附表\s*$|^附表\d*\s*$"
)
CHECKBOX_RE = re.compile(r"[□☑☒■✅✗×]")
# Legacy alias used by split_bid_markdown_sections.
FRONT_TABLE_RE = FRONT_TABLE_HEADING_RE


def is_front_table_heading(title: str) -> bool:
    return bool(FRONT_TABLE_HEADING_RE.match((title or "").strip()))


def preprocess_bid_markdown(markdown: str) -> str:
    """Strip recurring headers/footers before section split."""
    text = str(markdown or "")
    if not text.strip():
        return text
    pages = _split_markdown_pages(text)
    if len(pages) >= 2:
        recurring = _recurring_margin_lines(pages)
        cleaned_pages = []
        for page_no, body in pages:
            lines = []
            for line in body.splitlines():
                stripped = line.strip()
                if not stripped:
                    lines.append(line)
                    continue
                if PAGE_FOOTER_RE.fullmatch(stripped):
                    continue
                if stripped in recurring:
                    continue
                if _is_recurring_variant(stripped, recurring):
                    continue
                lines.append(line)
            cleaned = "\n".join(lines).strip()
            if page_no is None:
                cleaned_pages.append(cleaned)
            else:
                cleaned_pages.append(f"<!-- page:{page_no} -->\n\n{cleaned}".strip())
        text = "\n\n".join(part for part in cleaned_pages if part).strip()
    else:
        lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if PAGE_FOOTER_RE.fullmatch(stripped):
                continue
            lines.append(line)
        text = "\n".join(lines)
    return text


def normalize_bid_sections(sections: list[BidDocumentSection]) -> list[BidDocumentSection]:
    """Deduplicate TOC chapters, fold empty stubs, refresh table metadata."""
    from bid_agent.parsing.document_parser import _extract_markdown_tables_json

    if not sections:
        return sections
    sections = _drop_duplicate_chapters(sections)
    sections = _drop_empty_chapter_runs(sections)
    sections = _drop_misplaced_early_chapters(sections)
    sections = _merge_empty_stub_sections(sections)
    refreshed: list[BidDocumentSection] = []
    for index, section in enumerate(sections, start=1):
        metadata = dict(section.metadata or {})
        markdown = section.markdown or ""
        content = section.content or ""
        page_start, page_end = _page_span(markdown) or _page_span(content) or (None, None)
        if page_start:
            metadata["page_start"] = metadata.get("page_start") or page_start
        if page_end:
            metadata["page_end"] = page_end
        elif page_start:
            metadata["page_end"] = metadata.get("page_end") or page_start
        metadata["tables"] = _extract_markdown_tables_json(markdown)
        metadata["title_path"] = metadata.get("title_path") or [section.title]
        refreshed.append(
            section.model_copy(
                update={
                    "index": index,
                    "metadata": metadata,
                    "content": content,
                    "markdown": markdown,
                }
            )
        )
    return refreshed


def find_mid_toc_chapter_lines(lines: list[str], detect_heading) -> set[int]:
    """Suppress mid-document reprinted chapter stacks (第1–8章 with no body between).

    A chapter that already has real subsection/prose after it starts body content and
    must not be absorbed into the reprint stack (avoids eating 第一章 after 目录).
    """
    suppressed: set[int] = set()
    index = 0
    while index < len(lines):
        heading = detect_heading(lines[index])
        if not (heading and heading[0] <= 1 and CHAPTER_TITLE_RE.match(heading[1])):
            index += 1
            continue
        if _following_body_signal(lines, index + 1) >= 40:
            index += 1
            continue
        stack = [index]
        cursor = index + 1
        while cursor < len(lines):
            stripped = lines[cursor].strip()
            if not stripped or PAGE_COMMENT_RE.search(stripped):
                cursor += 1
                continue
            later = detect_heading(lines[cursor])
            if later and later[0] <= 1 and CHAPTER_TITLE_RE.match(later[1]):
                if _following_body_signal(lines, cursor + 1) >= 40:
                    break
                stack.append(cursor)
                cursor += 1
                continue
            break
        if len(stack) >= 3:
            suppressed.update(stack)
            # Trailing chapter of a 1..N reprint often has body signal from stolen
            # numbered clauses (第八章 → 8.1 须知). Drop it when it appears again later.
            cursor = stack[-1] + 1
            while cursor < len(lines):
                stripped = lines[cursor].strip()
                if not stripped or PAGE_COMMENT_RE.search(stripped):
                    cursor += 1
                    continue
                later = detect_heading(lines[cursor])
                if later and later[0] <= 1 and CHAPTER_TITLE_RE.match(later[1]):
                    key = _normalize_chapter_key(later[1])
                    if _chapter_key_appears_later(lines, cursor, key, detect_heading):
                        suppressed.add(cursor)
                break
        index = stack[-1] + 1
    return suppressed


def _chapter_key_appears_later(
    lines: list[str], after_index: int, key: str, detect_heading
) -> bool:
    for index in range(after_index + 1, len(lines)):
        heading = detect_heading(lines[index])
        if not heading:
            continue
        title = heading[1]
        if CHAPTER_TITLE_RE.match(title) and _normalize_chapter_key(title) == key:
            return True
    return False


def find_toc_suppressed_lines(lines: list[str], detect_heading) -> set[int]:
    """Suppress 目录 entries until the first real body chapter.

    Dotted TOC lines are often longer than the heading length cap, so they never
    register as headings. Relying on "second duplicate chapter" then pushes
    body_start deep into the document and wipes chapters 1–2 into 前言.
    """
    toc_start = None
    for index, line in enumerate(lines):
        compact = line.strip().replace(" ", "")
        if TOC_TITLE_RE.fullmatch(compact):
            toc_start = index
            break
    if toc_start is None:
        return set()

    suppressed: set[int] = set()
    for index in range(toc_start + 1, min(len(lines), toc_start + 200)):
        stripped = lines[index].strip()
        if not stripped or PAGE_COMMENT_RE.search(stripped):
            continue
        if _is_toc_entry_line(stripped):
            suppressed.add(index)
            continue

        heading = detect_heading(lines[index])
        title = heading[1] if heading else _toc_chapter_title(stripped)
        if title and CHAPTER_TITLE_RE.match(title):
            # Clean chapter title with following body prose → end of TOC.
            if _following_body_signal(lines, index + 1, limit=12) >= 40:
                break
            # Bare chapter stack still inside TOC (no dots, no prose yet).
            suppressed.add(index)
            continue

        if heading:
            # Mid-level titles between 目录 and body are almost always TOC noise.
            suppressed.add(index)
            continue

        # Substantial non-heading prose means body has started.
        if len(stripped) >= 20:
            break
    return suppressed


def _is_toc_entry_line(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    if re.search(r"[·．.]{3,}|\.{3,}|…{1,}|……", stripped):
        return True
    trimmed = _toc_chapter_title(stripped)
    if trimmed and trimmed != stripped and CHAPTER_TITLE_RE.match(trimmed):
        return True
    return False


def _toc_chapter_title(text: str) -> str | None:
    stripped = (text or "").strip()
    if not stripped:
        return None
    cut = re.split(r"[·．.]{2,}|…+", stripped, maxsplit=1)[0].strip()
    cut = re.sub(r"[\s\.·．…]+\d+\s*$", "", cut).strip()
    if CHAPTER_TITLE_RE.match(cut):
        return cut
    return None


def parse_table_meta_comment(comment_attrs: str) -> dict:
    meta: dict = {}
    for match in re.finditer(r"(\w+)\s*=\s*([^\s]+)", comment_attrs or ""):
        key = match.group(1).lower()
        value = match.group(2).strip()
        if key == "bbox":
            parts = value.split(",")
            if len(parts) == 4:
                try:
                    meta["bbox"] = tuple(float(part) for part in parts)
                except ValueError:
                    pass
        elif key == "page":
            try:
                meta["page"] = int(float(value))
            except ValueError:
                pass
    return meta


def _split_markdown_pages(markdown: str) -> list[tuple[int | None, str]]:
    parts = PAGE_COMMENT_RE.split(markdown)
    if len(parts) == 1:
        return [(None, markdown)]
    pages: list[tuple[int | None, str]] = []
    preface = parts[0].strip()
    if preface:
        pages.append((None, preface))
    for index in range(1, len(parts), 2):
        page_no = int(parts[index])
        body = parts[index + 1] if index + 1 < len(parts) else ""
        pages.append((page_no, body))
    return pages


def _recurring_margin_lines(pages: list[tuple[int | None, str]]) -> set[str]:
    counts: dict[str, int] = {}
    page_count = 0
    for page_no, body in pages:
        if page_no is None:
            continue
        page_count += 1
        seen: set[str] = set()
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped or len(stripped) > 40:
                continue
            if PAGE_COMMENT_RE.search(stripped):
                continue
            if stripped.startswith("|"):
                continue
            if stripped in seen:
                continue
            seen.add(stripped)
            counts[stripped] = counts.get(stripped, 0) + 1
    if page_count < 2:
        return set()
    threshold = max(3, int(page_count * 0.35 + 0.999))
    return {line for line, count in counts.items() if count >= threshold}


def _is_recurring_variant(line: str, recurring: Iterable[str]) -> bool:
    compact = re.sub(r"\s+", "", line)
    for item in recurring:
        other = re.sub(r"\s+", "", item)
        if compact == other:
            return True
        # Same template with only digits changed (page footers already handled).
        if len(compact) > 8 and re.sub(r"\d+", "#", compact) == re.sub(r"\d+", "#", other):
            return True
    return False


def _normalize_chapter_key(title: str) -> str:
    text = re.sub(r"\s+", "", title or "")
    match = re.match(r"(第[一二三四五六七八九十百千万零〇\d]+[章节篇部分])", text)
    return match.group(1) if match else text


def _chapter_cluster_weight(sections: list[BidDocumentSection], index: int) -> int:
    """Weight a chapter by its own content plus following subsections until the next chapter."""
    section = sections[index]
    weight = len((section.content or "").strip())
    for later in sections[index + 1 :]:
        title = (later.title or "").strip()
        if later.level <= 1 and CHAPTER_TITLE_RE.match(title):
            break
        weight += len((later.content or "").strip())
        weight += 10
    return weight


def _chapter_child_count(sections: list[BidDocumentSection], index: int) -> int:
    count = 0
    for later in sections[index + 1 :]:
        title = (later.title or "").strip()
        if later.level <= 1 and CHAPTER_TITLE_RE.match(title):
            break
        count += 1
    return count


def _drop_duplicate_chapters(sections: list[BidDocumentSection]) -> list[BidDocumentSection]:
    # value: (index, children, weight)
    best: dict[str, tuple[int, int, int]] = {}
    for index, section in enumerate(sections):
        title = (section.title or "").strip()
        if section.level != 1 or not CHAPTER_TITLE_RE.match(title):
            continue
        key = _normalize_chapter_key(title)
        children = _chapter_child_count(sections, index)
        weight = _chapter_cluster_weight(sections, index)
        current = best.get(key)
        if current is None:
            best[key] = (index, children, weight)
            continue
        cur_index, cur_children, cur_weight = current
        replace = False
        if children > cur_children:
            replace = True
        elif children == cur_children == 0:
            # Bare shells: keep the later one (end-matter over mid-doc TOC reprint).
            replace = index > cur_index
        elif children == cur_children and weight > cur_weight:
            replace = True
        elif children == cur_children and weight == cur_weight and index < cur_index:
            replace = True
        if replace:
            best[key] = (index, children, weight)

    keep = {index for index, _children, _weight in best.values()}
    output: list[BidDocumentSection] = []
    for index, section in enumerate(sections):
        title = (section.title or "").strip()
        if section.level == 1 and CHAPTER_TITLE_RE.match(title):
            if index not in keep:
                continue
        output.append(section)
    return output


def _is_toc_reprint_chapter(sections: list[BidDocumentSection], index: int) -> bool:
    """True for bare 第X章 shells with no subsections (typical mid-doc TOC reprint)."""
    return _chapter_child_count(sections, index) == 0


def _drop_empty_chapter_runs(sections: list[BidDocumentSection]) -> list[BidDocumentSection]:
    """Drop mid-document TOC reprints: consecutive bare 第X章 with no subsections."""
    if len(sections) < 3:
        return sections
    drop: set[int] = set()
    index = 0
    while index < len(sections):
        title = (sections[index].title or "").strip()
        if not (sections[index].level == 1 and CHAPTER_TITLE_RE.match(title)):
            index += 1
            continue
        if not _is_toc_reprint_chapter(sections, index):
            index += 1
            continue
        end = index + 1
        while end < len(sections):
            later_title = (sections[end].title or "").strip()
            if not (sections[end].level == 1 and CHAPTER_TITLE_RE.match(later_title)):
                break
            if not _is_toc_reprint_chapter(sections, end):
                break
            end += 1
        if end - index >= 3:
            drop.update(range(index, end))
        index = end
    if not drop:
        return sections
    return [section for i, section in enumerate(sections) if i not in drop]


def _merge_empty_stub_sections(sections: list[BidDocumentSection]) -> list[BidDocumentSection]:
    from bid_agent.parsing.document_parser import _extract_markdown_tables_json

    if not sections:
        return sections
    merged: list[BidDocumentSection] = [sections[0]]
    for section in sections[1:]:
        content = (section.content or "").strip()
        title = (section.title or "").strip()
        # Keep real structural headings even when body lives in child sections.
        if CHAPTER_TITLE_RE.match(title) or CHINESE_ORDER_TITLE_RE.match(title):
            merged.append(section)
            continue
        looks_stub = not content or content == title
        looks_table_fragment = bool(
            CHECKBOX_RE.search(title)
            or re.search(r"\d{4}\s*年", title)
            or (
                re.match(r"^\d+(?:[.．]\d+)+", title)
                and len(title) > 20
                and "：" not in title
                and ":" not in title
            )
        )
        if merged and section.level >= 2 and (looks_stub or looks_table_fragment):
            previous = merged[-1]
            piece = title if looks_stub and not content else f"{title}\n{content}".strip()
            new_content = "\n".join(part for part in [previous.content or "", piece] if part).strip()
            new_markdown = "\n".join(part for part in [previous.markdown or "", piece] if part).strip()
            metadata = dict(previous.metadata or {})
            metadata["tables"] = _extract_markdown_tables_json(new_markdown)
            merged[-1] = previous.model_copy(
                update={"content": new_content, "markdown": new_markdown, "metadata": metadata}
            )
            continue
        merged.append(section)
    return merged


def _page_span(text: str) -> tuple[int, int] | None:
    pages = [int(match.group(1)) for match in PAGE_COMMENT_RE.finditer(text or "")]
    if not pages:
        match = re.search(r"第\s*(\d+)\s*页", text or "")
        if not match:
            return None
        page = int(match.group(1))
        return page, page
    return min(pages), max(pages)


def _following_prose_chars(lines: list[str], start: int, limit: int = 8) -> int:
    return _following_body_signal(lines, start, limit=limit)


def _following_body_signal(lines: list[str], start: int, limit: int = 8) -> int:
    """Score upcoming lines as body (order titles + prose), not another chapter stack."""
    total = 0
    scanned = 0
    for line in lines[start:]:
        stripped = line.strip()
        if not stripped or PAGE_COMMENT_RE.search(stripped):
            continue
        if TOC_TITLE_RE.fullmatch(stripped.replace(" ", "")):
            break
        if _is_toc_entry_line(stripped):
            break
        chapter = _toc_chapter_title(stripped) or (
            stripped if CHAPTER_TITLE_RE.match(stripped) else None
        )
        if chapter and CHAPTER_TITLE_RE.match(chapter):
            break
        total += len(stripped)
        scanned += 1
        if scanned >= limit:
            break
    return total


def _drop_misplaced_early_chapters(sections: list[BidDocumentSection]) -> list[BidDocumentSection]:
    """Drop TOC remnant chapters that appear before the first chapter with real body."""
    if len(sections) < 2:
        return sections
    first_body_index = None
    for index, section in enumerate(sections):
        title = (section.title or "").strip()
        if section.level != 1 or not CHAPTER_TITLE_RE.match(title):
            continue
        content_len = len((section.content or "").strip())
        # Body chapters either carry content or are immediately followed by subsections.
        has_child = False
        for later in sections[index + 1 :]:
            if later.level <= 1 and CHAPTER_TITLE_RE.match((later.title or "").strip()):
                break
            if later.level >= 2 and len((later.content or "").strip()) >= 20:
                has_child = True
                break
        if content_len >= 40 or has_child:
            first_body_index = index
            break
    if first_body_index is None:
        return sections

    output: list[BidDocumentSection] = []
    for index, section in enumerate(sections):
        title = (section.title or "").strip()
        if (
            index < first_body_index
            and section.level == 1
            and CHAPTER_TITLE_RE.match(title)
            and len((section.content or "").strip()) < 40
        ):
            # Skip empty TOC remnant chapters ahead of real body.
            continue
        output.append(section)
    return output

