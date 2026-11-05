"""Common parsing contract used by queue workers and all supported source formats."""
import hashlib
from pathlib import Path

from bid_agent.parsing.document_parser import parse_bid_document
from bid_agent.parsing.strategy import inspect_document_profile, resolve_parse_method, build_parse_quality_report
from bid_agent.schemas.documents import ParseOptions, ParsedBlock, ParsedDocument


def parse_version(version: dict, path: Path, options: ParseOptions, progress=None) -> ParsedDocument:
    if progress:
        progress(10, 'verifying_source')
    with path.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != version['sha256']:
            raise ValueError('原件校验失败：文件内容与保存的 SHA-256 不一致')
    profile = inspect_document_profile(str(path))
    method, _ = resolve_parse_method(str(path), options.parse_method)
    if progress:
        progress(25, 'parsing')
    arguments = options.model_dump()
    arguments['parse_method'] = method
    sections = parse_bid_document(document=str(path), **arguments)
    if not sections:
        raise ValueError('解析结果为空，请选择 OCR 或其他解析方式')
    if progress:
        progress(85, 'normalizing')
    blocks = []
    warnings = []
    for section in sections:
        metadata = dict(section.metadata or {})
        hierarchy = metadata.get('title_path') or metadata.get('hierarchy_path') or section.title
        if isinstance(hierarchy, list):
            section_path = [str(part).strip() for part in hierarchy if str(part).strip()]
        else:
            section_path = [part.strip() for part in str(hierarchy).split('>') if part.strip()]
        page = metadata.get('page_start') or metadata.get('page')
        page = int(page) if str(page).isdigit() and int(page) > 0 else None
        page_end = metadata.get('page_end')
        page_end = int(page_end) if str(page_end).isdigit() and int(page_end) > 0 else page
        if page_end and page:
            metadata['page_end'] = page_end
        digest = hashlib.sha256(f"{version['id']}:{section.index}:{section.markdown}".encode()).hexdigest()[:24]
        blocks.append(
            ParsedBlock(
                id='block_' + digest,
                type='section',
                text=section.markdown,
                section_index=section.index,
                section_path=section_path,
                page=page,
                bbox=None,
                metadata=metadata,
            )
        )
        for table_index, table in enumerate(metadata.get('tables') or []):
            if not isinstance(table, dict):
                continue
            table_text = str(table.get('markdown') or '').strip()
            if not table_text:
                continue
            table_page = table.get('page') or page
            table_page = int(table_page) if str(table_page).isdigit() and int(table_page) > 0 else page
            bbox = _coerce_bbox(table.get('bbox'))
            table_meta = {
                'headers': table.get('headers') or [],
                'row_count': table.get('row_count'),
                'source_section_index': section.index,
                'table_index': table_index,
            }
            if bbox:
                table_meta['bbox'] = list(bbox)
            table_digest = hashlib.sha256(
                f"{version['id']}:{section.index}:table:{table_index}:{table_text}".encode()
            ).hexdigest()[:24]
            blocks.append(
                ParsedBlock(
                    id='block_' + table_digest,
                    type='table',
                    text=table_text,
                    section_index=section.index,
                    section_path=section_path,
                    page=table_page,
                    bbox=bbox,
                    metadata=table_meta,
                )
            )
    quality = build_parse_quality_report(
        sections=sections,
        parse_method_used=method,
        parse_method_recommended=profile.get('recommended_parse_method', method),
        image_count=int(profile.get('image_count') or 0),
        preflight_profile=profile,
    )
    if any(block.page is None for block in blocks):
        warnings.append('部分解析器未提供准确物理页码；当前按章节定位，不推断页码或坐标。')
    if any(block.type == 'section' and block.bbox is None for block in blocks):
        warnings.append('章节块未提供 bbox（本地文本解析仅保证页码；版面坐标需 MinerU/Docling 等结构化解析器）。')
    table_blocks = [block for block in blocks if block.type == 'table']
    if table_blocks and all(block.bbox is None for block in table_blocks):
        warnings.append('已产出表格块但缺少单元格几何框，仅保留表格 Markdown 与页码。')
    return ParsedDocument(
        document_version_id=version['id'],
        source_sha256=version['sha256'],
        parse_method=method,
        parser_version='bid-parser-v2',
        markdown='\n\n'.join(section.markdown for section in sections),
        sections=sections,
        blocks=blocks,
        quality=quality,
        warnings=warnings,
    )


def _coerce_bbox(value) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)) and len(value) == 4:
        try:
            return tuple(float(part) for part in value)  # type: ignore[return-value]
        except (TypeError, ValueError):
            return None
    return None
