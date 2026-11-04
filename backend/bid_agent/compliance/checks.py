"""Rule-first compliance checks; optional LLM helpers when enabled."""
from __future__ import annotations

import re
from typing import Iterable

from bid_agent.compliance.types import CheckContext, CheckFinding


def pricing_check(ctx: CheckContext) -> list[CheckFinding]:
    text = ctx.bid_text or ctx.outline_markdown or ''
    findings: list[CheckFinding] = []
    amounts = [float(match.group(1)) for match in re.finditer(r'(\d+(?:\.\d+)?)\s*万元', text)]
    if len(amounts) >= 2 and max(amounts) - min(amounts) > 0.01:
        findings.append(CheckFinding(
            check_name='pricing_check',
            severity='medium',
            title='文中出现多个不同“万元”金额',
            detail=f'检测到金额：{", ".join(str(v) for v in amounts[:8])}。请核对大小写与分项合计。',
        ))
    if '大写' not in text and amounts:
        findings.append(CheckFinding(
            check_name='pricing_check',
            severity='low',
            title='未检测到金额大写表述',
            detail='若报价页需要大写金额，请补充并与阿拉伯数字一致。',
        ))
    return findings


def rejection_alignment_check(ctx: CheckContext) -> list[CheckFinding]:
    findings: list[CheckFinding] = []
    bid_blob = _bid_blob(ctx)
    for item in _confirmed(ctx.requirements, categories={'rejection'}):
        needle = (item.get('normalized_value') or item.get('raw_text') or item.get('title') or '').strip()
        short = needle[:40]
        if short and short not in bid_blob and not _tokens_hit(short, bid_blob):
            findings.append(CheckFinding(
                check_name='rejection_alignment',
                severity='high',
                title=f'废标项可能未响应：{item.get("title") or "未命名"}',
                detail=f'要求摘录：{needle[:240]}',
                requirement_item_id=item.get('id'),
                evidence=item.get('source_refs') or [],
            ))
    return findings


def mandatory_star_check(ctx: CheckContext) -> list[CheckFinding]:
    findings: list[CheckFinding] = []
    bid_blob = _bid_blob(ctx)
    for item in ctx.requirements:
        if item.get('review_status') == 'rejected':
            continue
        text = f'{item.get("title") or ""} {item.get("normalized_value") or item.get("raw_text") or ""}'
        if '★' not in text and '▲' not in text and '实质性' not in text:
            continue
        needle = (item.get('normalized_value') or item.get('title') or '').strip()[:48]
        if needle and needle not in bid_blob and not _tokens_hit(needle, bid_blob):
            findings.append(CheckFinding(
                check_name='mandatory_req_check',
                severity='critical',
                title=f'实质性／★▲ 要求可能缺失：{item.get("title") or "未命名"}',
                detail=needle[:300],
                requirement_item_id=item.get('id'),
                evidence=item.get('source_refs') or [],
            ))
    return findings


def scoring_coverage_check(ctx: CheckContext) -> list[CheckFinding]:
    from bid_agent.services.score_coverage import compute_score_coverage, scoring_matrix_from_requirements

    rows = scoring_matrix_from_requirements([
        item for item in ctx.requirements if item.get('review_status') != 'rejected'
    ])
    coverage = compute_score_coverage(rows, ctx.bid_sections or [])
    findings: list[CheckFinding] = []
    if coverage['total'] and coverage['coverage_rate'] < 0.7:
        findings.append(CheckFinding(
            check_name='score_coverage',
            severity='high',
            title=f'评分项覆盖率偏低（{coverage["coverage_rate"]:.0%}）',
            detail=f'已覆盖 {coverage["covered"]}/{coverage["total"]}；未覆盖：'
                   + '；'.join(item['item'] for item in coverage.get('uncovered', [])[:8]),
        ))
    for uncovered in coverage.get('uncovered') or []:
        findings.append(CheckFinding(
            check_name='score_coverage',
            severity='medium',
            title=f'评分项未映射到目录：{uncovered.get("item")}',
            detail='请调整章节标题或补充评分响应小节。',
        ))
    return findings


def expired_asset_check(ctx: CheckContext) -> list[CheckFinding]:
    findings: list[CheckFinding] = []
    for asset in ctx.linked_assets or []:
        if asset.get('status') == 'expired' or asset.get('expired'):
            findings.append(CheckFinding(
                check_name='expired_asset',
                severity='high',
                title=f'关联企业资产已过期：{asset.get("title") or "未命名"}',
                detail=(
                    f'类别 {asset.get("category")}；到期日 {asset.get("expires_on") or "未知"}。'
                    '过期材料不能默认用于生成，请更换有效版本或取消关联。'
                ),
            ))
        elif asset.get('status') == 'active' and not asset.get('latest_version'):
            findings.append(CheckFinding(
                check_name='expired_asset',
                severity='medium',
                title=f'有效资产缺少附件：{asset.get("title") or "未命名"}',
                detail='请上传不可变附件版本后再用于投标生成。',
            ))
    return findings


def response_matrix_check(ctx: CheckContext) -> list[CheckFinding]:
    findings: list[CheckFinding] = []
    rows = ctx.response_matrix or []
    if not rows:
        return findings
    for row in rows:
        if not row.get('is_mandatory'):
            continue
        status = row.get('response_status') or 'uncovered'
        if status in {'responded', 'waived', 'drafted'}:
            continue
        title = row.get('requirement_title') or '未命名要求'
        if status == 'missing_material':
            severity = 'high'
            detail = '；'.join(row.get('missing_materials') or []) or '标记为缺失材料'
        elif status == 'uncovered':
            severity = 'critical'
            detail = '强制条款尚未映射到响应章节'
        else:
            severity = 'high'
            detail = '已映射章节但正文仍空，或材料未闭环'
        findings.append(CheckFinding(
            check_name='response_matrix',
            severity=severity,
            title=f'响应矩阵未闭环：{title}',
            detail=detail,
            requirement_item_id=row.get('requirement_item_id'),
            section_key=row.get('section_key'),
        ))
    return findings


def selfcheck_list(ctx: CheckContext) -> list[CheckFinding]:
    checklist = [
        ('资格文件齐全', any(item.get('category') == 'qualification' and item.get('review_status') == 'confirmed'
                         for item in ctx.requirements)),
        ('废标条款已核对', any(item.get('category') == 'rejection' and item.get('review_status') == 'confirmed'
                         for item in ctx.requirements)),
        ('评分响应目录已生成', bool(ctx.bid_sections)),
        ('技术方案章节存在', any('技术' in (section.get('title') or '') for section in ctx.bid_sections)),
        ('报价相关章节存在', any(any(token in (section.get('title') or '') for token in ('报价', '价格'))
                         for section in ctx.bid_sections)),
        ('响应矩阵已构建', bool(ctx.response_matrix)),
    ]
    findings: list[CheckFinding] = []
    for title, ok in checklist:
        if not ok:
            findings.append(CheckFinding(
                check_name='selfcheck_list',
                severity='medium',
                title=f'自查未通过：{title}',
                detail='请完成对应材料或确认要求后再开启检查闸门。',
            ))
    return findings


def risk_score(findings: Iterable[CheckFinding]) -> dict:
    weights = {'critical': 40, 'high': 25, 'medium': 12, 'low': 5, 'info': 1}
    score = 0
    by_sev = {key: 0 for key in weights}
    for finding in findings:
        by_sev[finding.severity] = by_sev.get(finding.severity, 0) + 1
        score += weights.get(finding.severity, 1)
    score = min(100, score)
    if score >= 70:
        level = 'critical'
    elif score >= 40:
        level = 'high'
    elif score >= 20:
        level = 'medium'
    else:
        level = 'low'
    return {'composite_score': score, 'risk_level': level, 'by_severity': by_sev}


def llm_disqualification_check(ctx: CheckContext) -> list[CheckFinding]:
    if not ctx.use_llm or ctx.llm is None:
        return []
    clauses = [
        f'- {item.get("title")}: {(item.get("normalized_value") or item.get("raw_text") or "")[:200]}'
        for item in _confirmed(ctx.requirements, categories={'rejection'})
    ][:20]
    if not clauses:
        return []
    prompt = (
        '你是投标合规助手。根据废标条款与投标目录／正文摘要，列出仍可能触发废标的缺口。'
        '只输出 JSON：{"items":[{"title":"...","detail":"...","severity":"high|medium|low"}]}。\n'
        f'废标条款：\n' + '\n'.join(clauses) + '\n'
        f'投标摘要：\n{(ctx.bid_text or ctx.outline_markdown)[:6000]}'
    )
    try:
        data = ctx.llm.collect_json(
            [{'role': 'user', 'content': prompt}],
            allow_llm_repair=False,
        )
    except Exception:  # noqa: BLE001
        return [CheckFinding(
            check_name='disqualification_check',
            severity='info',
            title='LLM 废标辅助检查跳过',
            detail='模型调用失败或返回无法解析，已保留规则检查结果。',
        )]
    findings: list[CheckFinding] = []
    for item in (data.get('items') if isinstance(data, dict) else None) or []:
        findings.append(CheckFinding(
            check_name='disqualification_check',
            severity=item.get('severity') if item.get('severity') in {'low', 'medium', 'high', 'critical'} else 'medium',
            title=str(item.get('title') or '废标风险'),
            detail=str(item.get('detail') or ''),
        ))
    return findings


def _confirmed(requirements: list[dict], *, categories: set[str]) -> list[dict]:
    return [
        item for item in requirements
        if item.get('category') in categories and item.get('review_status') == 'confirmed'
    ]


def _bid_blob(ctx: CheckContext) -> str:
    parts = [ctx.outline_markdown or '', ctx.bid_text or '']
    for section in ctx.bid_sections or []:
        parts.append(section.get('title') or '')
        parts.append(section.get('body_markdown') or '')
    return '\n'.join(parts)


def _tokens_hit(needle: str, haystack: str) -> bool:
    tokens = re.findall(r'[\u4e00-\u9fff]{2,}', needle)
    if not tokens:
        return False
    hits = sum(1 for token in tokens if token in haystack)
    return hits >= max(1, len(tokens) // 2)
