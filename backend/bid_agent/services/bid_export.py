"""Synchronous DOCX export behind the check stage gate."""
from __future__ import annotations

import io

from bid_agent.core.identity import Principal
from bid_agent.infrastructure.docx_export import build_bid_docx
from bid_agent.infrastructure.object_store import object_store
from bid_agent.repositories import bids, exports, stages


def export_docx(
    project_id: str,
    user: Principal,
    *,
    bid_version_id: str,
    force_skip_gate: bool = False,
    notes: str = '',
    bidder_name: str = '',
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

    content = build_bid_docx(
        project_name=bid.get('title') or '投标文件',
        outline_tree=bid.get('outline_tree'),
        sections=bid.get('sections') or [],
        cover={'title': bid.get('title') or '投标文件', 'bidder_name': bidder_name},
    )
    stored = object_store.put(io.BytesIO(content), f'{bid_version_id}.docx')
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
    )
    return artifact
