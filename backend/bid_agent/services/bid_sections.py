"""Persist and seed editable bid section bodies within a bid version."""
from __future__ import annotations

from bid_agent.core.identity import Principal
from bid_agent.repositories import bids, stages


def save_section(
    section_id: str,
    user: Principal,
    *,
    body_markdown: str,
    title: str | None = None,
    mark_generate_gate: bool = False,
) -> dict:
    section = bids.update_section(
        section_id,
        user,
        body_markdown=body_markdown,
        title=title,
    )
    if mark_generate_gate and str(body_markdown or '').strip():
        stages.mark_stage(
            section['project_id'],
            'generate',
            user,
            status='passed',
            notes='章节正文已保存',
        )
    bid = bids.get_bid_version(section['bid_version_id'], user)
    return {
        'section': section,
        'bid_version_id': section['bid_version_id'],
        'content_stats': bid.get('content_stats') or {},
    }


def seed_placeholder(section_id: str, user: Principal, *, overwrite: bool = False) -> dict:
    current = bids.get_section(section_id, user)
    existing = str(current.get('body_markdown') or '').strip()
    if existing and not overwrite:
        raise ValueError('章节已有正文；如需覆盖请传 overwrite=true')
    title = current.get('title') or '本章'
    body = (
        f'## {title}\n\n'
        '【待补充】请在此填写本章响应要点、证据引用与企业材料对应说明。\n'
        '缺少企业侧事实时保留【待补充】，不要编造证书编号、金额或人员姓名。\n'
    )
    return save_section(section_id, user, body_markdown=body, mark_generate_gate=False)
