"""Synchronous DOCX／optional PDF export behind the check stage gate."""
from __future__ import annotations

import io

from bid_agent.core.identity import Principal
from bid_agent.infrastructure.docx_export import build_bid_docx, inspect_docx_structure
from bid_agent.infrastructure.export_templates import TEMPLATE_VERSION, get_template, list_templates
from bid_agent.infrastructure.object_store import object_store
from bid_agent.infrastructure.pdf_convert import convert_docx_to_pdf, libreoffice_available
from bid_agent.repositories import bids, exports, stages
from bid_agent.services import response_matrix


def available_templates() -> dict:
    return {
        'template_version': TEMPLATE_VERSION,
        'templates': list_templates(),
        'pdf_converter_available': libreoffice_available(),
    }


def export_docx(
    project_id: str,
    user: Principal,
    *,
    bid_version_id: str,
    force_skip_gate: bool = False,
    notes: str = '',
    bidder_name: str = '',
    template_id: str = 'full',
    convert_pdf: bool = False,
) -> dict:
    stages.ensure_project_exists(project_id, user)
    if force_skip_gate:
        if not (user.is_admin or notes.strip()):
            raise ValueError('强制跳过检查闸门需要管理员身份或填写备注')
    else:
        stages.require_passed(project_id, 'check', user)

    bid = bids.get_bid_version(bid_version_id, user)
    if bid['project_id'] != project_id:
        raise ValueError('标书版本不属于当前项目')

    template = get_template(template_id)
    matrix = response_matrix.get_matrix(bid_version_id, user)
    missing = matrix.get('missing_materials') or []
    matrix_rows = matrix.get('rows') or []

    content = build_bid_docx(
        project_name=bid.get('title') or '投标文件',
        outline_tree=bid.get('outline_tree'),
        sections=bid.get('sections') or [],
        cover={'title': bid.get('title') or '投标文件', 'bidder_name': bidder_name},
        missing_materials=missing,
        matrix_rows=matrix_rows,
        template_id=template['id'],
    )
    structure = inspect_docx_structure(content)
    checklist = {
        'template_id': template['id'],
        'template_version': template['template_version'],
        'missing_count': len(missing),
        'matrix_rows': len(matrix_rows),
        'section_count': len(bid.get('sections') or []),
        'structure': structure,
        'pdf_requested': convert_pdf,
        'pdf_converter_available': libreoffice_available(),
    }
    stored = object_store.put(io.BytesIO(content), f'{bid_version_id}-{template["id"]}.docx')
    artifact = exports.create_artifact(
        project_id,
        user,
        bid_version_id=bid_version_id,
        file_name=stored['file_name'],
        object_key=stored['object_key'],
        sha256=stored['sha256'],
        size_bytes=stored['size_bytes'],
        kind='docx',
        force_skip_gate=force_skip_gate,
        notes=notes,
        template_id=template['id'],
        template_version=template['template_version'],
        checklist=checklist,
    )

    pdf_artifact = None
    pdf_status = {'ok': False, 'reason': '未请求 PDF 转换'}
    if convert_pdf:
        pdf_status = convert_docx_to_pdf(content)
        if pdf_status.get('ok'):
            pdf_stored = object_store.put(
                io.BytesIO(pdf_status['pdf_bytes']),
                f'{bid_version_id}-{template["id"]}.pdf',
            )
            pdf_artifact = exports.create_artifact(
                project_id,
                user,
                bid_version_id=bid_version_id,
                file_name=pdf_stored['file_name'],
                object_key=pdf_stored['object_key'],
                sha256=pdf_stored['sha256'],
                size_bytes=pdf_stored['size_bytes'],
                kind='pdf',
                force_skip_gate=force_skip_gate,
                notes=notes,
                template_id=template['id'],
                template_version=template['template_version'],
                checklist={**checklist, 'source_artifact_id': artifact['id']},
                parent_artifact_id=artifact['id'],
            )
        checklist['pdf_status'] = {
            'ok': bool(pdf_status.get('ok')),
            'reason': pdf_status.get('reason'),
        }

    return {
        'artifact': artifact,
        'pdf_artifact': pdf_artifact,
        'checklist': checklist,
        'template': {
            'id': template['id'],
            'label': template['label'],
            'version': template['template_version'],
        },
        'pdf_status': pdf_status if convert_pdf else None,
    }
