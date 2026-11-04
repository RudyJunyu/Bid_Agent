"""Programmatic DOCX export for bid outlines and section bodies."""
from __future__ import annotations

import io
from typing import Any

from bid_agent.infrastructure.export_templates import filter_sections, get_template


def build_bid_docx(
    *,
    project_name: str,
    outline_tree: dict | list | None = None,
    sections: list[dict] | None = None,
    cover: dict | None = None,
    missing_materials: list[dict] | None = None,
    matrix_rows: list[dict] | None = None,
    template_id: str | None = 'full',
) -> bytes:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    template = get_template(template_id)
    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.54)
        section.bottom_margin = Cm(2.54)
        section.left_margin = Cm(3.18)
        section.right_margin = Cm(2.54)
        if template.get('include_page_numbers'):
            _add_page_number(section.footer)

    normal = doc.styles['Normal']
    normal.font.name = 'Times New Roman'
    normal.font.size = Pt(12)
    if normal.element.rPr is not None and normal.element.rPr.rFonts is not None:
        normal.element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')
    pf = normal.paragraph_format
    pf.line_spacing_rule = WD_LINE_SPACING.ONE_POINT_FIVE

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
    if template.get('dark_bid'):
        bidder = '（暗标：不填写投标人名称）'
        subtitle = f'{template.get("label") or "技术标"}（暗标）'
    else:
        bidder = cover_data.get('bidder_name') or '（填写投标人名称）'
        subtitle = template.get('label') or '投 标 文 件'
    for text, size, bold in (
        (title, 22, True),
        (subtitle, 18, True),
        ('', 12, False),
        (f'投标人：{bidder}', 14, False),
        (f'导出模板：{template["id"]} / {template["template_version"]}', 10, False),
    ):
        para = doc.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = para.add_run(text)
        run.bold = bold
        run.font.size = Pt(size)
        run.font.name = '黑体'
        run.element.rPr.rFonts.set(qn('w:eastAsia'), '黑体')
    doc.add_page_break()

    selected = filter_sections(sections or [], template)
    if template.get('include_toc'):
        _append_toc(doc, selected, outline_tree if not selected else None)
        doc.add_page_break()

    written_keys: set[str] = set()
    if selected:
        for section in sorted(selected, key=lambda item: int(item.get('sort_order') or 0)):
            level = min(max(int(section.get('level') or 1), 1), 3)
            doc.add_heading(section.get('title') or '章节', level=level)
            body = (section.get('body_markdown') or '').strip()
            if body:
                for line in body.splitlines() or ['']:
                    doc.add_paragraph(line)
            else:
                doc.add_paragraph('【待补充】')
            written_keys.add(str(section.get('section_key') or ''))
    elif not sections:
        chapters = []
        if isinstance(outline_tree, dict):
            chapters = outline_tree.get('chapters') or []
        elif isinstance(outline_tree, list):
            chapters = outline_tree
        _add_tree(doc, chapters, written_keys)

    if template.get('include_matrix_appendix') and matrix_rows:
        _append_matrix(doc, matrix_rows)
    if template.get('include_missing_appendix') and missing_materials:
        _append_missing_materials(doc, missing_materials)

    core = doc.core_properties
    core.title = title
    core.subject = f'Bid Agent export ({template["id"]})'
    core.comments = f'template={template["id"]};version={template["template_version"]}'

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def inspect_docx_structure(content: bytes) -> dict[str, Any]:
    """Lightweight golden-structure checks for exported DOCX bytes."""
    from docx import Document

    doc = Document(io.BytesIO(content))
    headings = [p.text.strip() for p in doc.paragraphs if p.style and str(p.style.name).startswith('Heading')]
    texts = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
    has_footer_page = False
    for section in doc.sections:
        footer_xml = section.footer._element.xml
        if 'PAGE' in footer_xml or 'w:fldChar' in footer_xml:
            has_footer_page = True
            break
    return {
        'heading_count': len(headings),
        'paragraph_count': len(texts),
        'has_cover_marker': any('投标' in text for text in texts[:8]),
        'has_toc': any(text == '目录' or text.startswith('目录') for text in texts[:30]),
        'has_missing_appendix': any('缺失材料' in text for text in texts),
        'has_page_numbers': has_footer_page,
        'headings_sample': headings[:12],
    }


def _append_toc(doc: Any, sections: list[dict], outline_tree: dict | list | None) -> None:
    doc.add_heading('目录', level=1)
    doc.add_paragraph('（打开 Word 后可按需更新域／页码；以下为导出时章节清单。）')
    if sections:
        for section in sorted(sections, key=lambda item: int(item.get('sort_order') or 0)):
            level = int(section.get('level') or 1)
            indent = '　' * max(level - 1, 0)
            doc.add_paragraph(f'{indent}{section.get("title") or "章节"}')
        return
    chapters = []
    if isinstance(outline_tree, dict):
        chapters = outline_tree.get('chapters') or []
    elif isinstance(outline_tree, list):
        chapters = outline_tree
    for chapter in chapters:
        doc.add_paragraph(chapter.get('title') or '章节')
        for child in chapter.get('children') or []:
            doc.add_paragraph(f'　{child.get("title") or "小节"}')


def _append_matrix(doc: Any, matrix_rows: list[dict]) -> None:
    doc.add_page_break()
    doc.add_heading('响应矩阵摘要', level=1)
    doc.add_paragraph('要求—章节—状态一览（导出时快照）。')
    for index, row in enumerate(matrix_rows[:80], start=1):
        title = row.get('requirement_title') or f'条目 {index}'
        status = row.get('response_status') or ''
        section = row.get('section_title') or '未映射'
        mandatory = '强制' if row.get('is_mandatory') else '普通'
        doc.add_paragraph(f'{index}. [{mandatory}] {title} → {section}（{status}）')


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


def _append_missing_materials(doc: Any, missing_materials: list[dict]) -> None:
    doc.add_page_break()
    doc.add_heading('缺失材料与待办清单', level=1)
    doc.add_paragraph('以下条目来自响应矩阵，导出时仍未闭环；定稿前请逐项处理。')
    for index, item in enumerate(missing_materials, start=1):
        title = item.get('requirement_title') or item.get('title') or f'条目 {index}'
        status = item.get('response_status') or ''
        mandatory = '强制' if item.get('is_mandatory') else '普通'
        doc.add_heading(f'{index}. [{mandatory}] {title}', level=2)
        if status:
            doc.add_paragraph(f'状态：{status}')
        if item.get('section_title'):
            doc.add_paragraph(f'关联章节：{item["section_title"]}')
        materials = item.get('materials') or item.get('missing_materials') or []
        if materials:
            doc.add_paragraph('待补：')
            for material in materials:
                doc.add_paragraph(str(material), style='List Bullet')
        else:
            doc.add_paragraph('待补：请核对要求与章节响应。')


def _add_page_number(footer) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    paragraph = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run('第 ')
    _add_field(run, 'PAGE')
    paragraph.add_run(' 页')


def _add_field(run, field_code: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    fld_char_begin = OxmlElement('w:fldChar')
    fld_char_begin.set(qn('w:fldCharType'), 'begin')
    instr = OxmlElement('w:instrText')
    instr.set(qn('xml:space'), 'preserve')
    instr.text = field_code
    fld_char_end = OxmlElement('w:fldChar')
    fld_char_end.set(qn('w:fldCharType'), 'end')
    run._r.append(fld_char_begin)
    run._r.append(instr)
    run._r.append(fld_char_end)
