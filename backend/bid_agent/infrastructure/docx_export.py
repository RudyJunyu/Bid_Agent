"""Programmatic DOCX export for bid outlines and section bodies."""
from __future__ import annotations

import io
from typing import Any


def build_bid_docx(
    *,
    project_name: str,
    outline_tree: dict | list | None = None,
    sections: list[dict] | None = None,
    cover: dict | None = None,
) -> bytes:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.54)
        section.bottom_margin = Cm(2.54)
        section.left_margin = Cm(3.18)
        section.right_margin = Cm(2.54)

    normal = doc.styles['Normal']
    normal.font.name = 'Times New Roman'
    normal.font.size = Pt(12)
    if normal.element.rPr is not None and normal.element.rPr.rFonts is not None:
        normal.element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')

    for level in range(1, 4):
        style_name = f'Heading {level}'
        if style_name in doc.styles:
            style = doc.styles[style_name]
            style.font.bold = True
            style.font.color.rgb = RGBColor(0, 0, 0)
            style.font.size = Pt(16 - level)
            style.font.name = '黑体'
            if style.element.rPr is not None and style.element.rPr.rFonts is not None:
                style.element.rPr.rFonts.set(qn('w:eastAsia'), '黑体')

    cover_data = cover or {}
    title = cover_data.get('title') or project_name or '投标文件'
    bidder = cover_data.get('bidder_name') or '（填写投标人名称）'
    for text, size, bold in (
        (title, 22, True),
        ('投 标 文 件', 18, True),
        ('', 12, False),
        (f'投标人：{bidder}', 14, False),
    ):
        para = doc.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = para.add_run(text)
        run.bold = bold
        run.font.size = Pt(size)
        run.font.name = '黑体'
        run.element.rPr.rFonts.set(qn('w:eastAsia'), '黑体')
    doc.add_page_break()

    written_keys: set[str] = set()
    if sections:
        for section in sorted(sections, key=lambda item: int(item.get('sort_order') or 0)):
            level = min(max(int(section.get('level') or 1), 1), 3)
            doc.add_heading(section.get('title') or '章节', level=level)
            body = (section.get('body_markdown') or '').strip()
            if body:
                for line in body.splitlines() or ['']:
                    doc.add_paragraph(line)
            else:
                doc.add_paragraph('【待补充】')
            written_keys.add(str(section.get('section_key') or ''))
    else:
        chapters = []
        if isinstance(outline_tree, dict):
            chapters = outline_tree.get('chapters') or []
        elif isinstance(outline_tree, list):
            chapters = outline_tree
        _add_tree(doc, chapters, written_keys)

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _add_tree(doc: Any, chapters: list[dict], written_keys: set[str], level: int = 1) -> None:
    for chapter in chapters or []:
        title = chapter.get('title') or '章节'
        doc.add_heading(title, level=min(level, 3))
        key = str(chapter.get('id') or title)
        written_keys.add(key)
        body = (chapter.get('body_markdown') or '').strip()
        if body:
            for line in body.splitlines():
                doc.add_paragraph(line)
        else:
            doc.add_paragraph('【待补充】')
        children = chapter.get('children') or []
        if children:
            _add_tree(doc, children, written_keys, level=level + 1)
