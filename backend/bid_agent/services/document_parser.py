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
    for section in sections:
        metadata = section.metadata or {}
        hierarchy = metadata.get('hierarchy_path') or section.title
        section_path = hierarchy if isinstance(hierarchy, list) else [part.strip() for part in str(hierarchy).split('>') if part.strip()]
        page = metadata.get('page_start') or metadata.get('page')
        page = int(page) if str(page).isdigit() and int(page) > 0 else None
        digest = hashlib.sha256(f"{version['id']}:{section.index}:{section.markdown}".encode()).hexdigest()[:24]
        blocks.append(ParsedBlock(id='block_' + digest, type='section', text=section.markdown,
                                  section_index=section.index, section_path=section_path, page=page, metadata=metadata))
    quality = build_parse_quality_report(sections=sections, parse_method_used=method,
        parse_method_recommended=profile.get('recommended_parse_method', method),
        image_count=int(profile.get('image_count') or 0), preflight_profile=profile)
    warnings = []
    if any(block.page is None for block in blocks):
        warnings.append('部分解析器未提供准确物理页码；当前按章节定位，不推断页码或坐标。')
    return ParsedDocument(document_version_id=version['id'], source_sha256=version['sha256'],
                          parse_method=method, markdown='\n\n'.join(section.markdown for section in sections),
                          sections=sections, blocks=blocks, quality=quality, warnings=warnings)
