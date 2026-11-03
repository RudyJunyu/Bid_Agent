"""Map scoring requirements to outline sections and measure coverage."""
from __future__ import annotations

import re
from typing import Any


def scoring_matrix_from_requirements(items: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for index, item in enumerate(items):
        if item.get('category') != 'scoring':
            continue
        if item.get('review_status') not in {None, 'draft', 'confirmed', 'conflict'}:
            # Still include draft/confirmed for outline drafting; rejected excluded.
            if item.get('review_status') == 'rejected':
                continue
        if item.get('review_status') == 'rejected':
            continue
        title = (item.get('title') or item.get('field_key') or f'评分项{index + 1}').strip()
        value = (item.get('normalized_value') or item.get('raw_text') or '').strip()
        score = _extract_score(value) or _extract_score(title)
        rows.append({
            'seq': len(rows) + 1,
            'requirement_item_id': item.get('id'),
            'item': title,
            'score': score,
            'criteria': value[:800],
            'suggested_section': _suggest_section(title, value),
            'review_status': item.get('review_status') or 'draft',
        })
    return rows


def build_aligned_outline(
    *,
    project_name: str,
    scoring_rows: list[dict],
    extra_sections: list[str] | None = None,
) -> dict[str, Any]:
    chapters = [
        {'id': 'cover', 'title': '封面与投标函', 'level': 1, 'children': []},
        {'id': 'qualification', 'title': '资格证明文件', 'level': 1, 'children': []},
        {'id': 'commercial', 'title': '商务响应', 'level': 1, 'children': []},
        {'id': 'technical', 'title': '技术响应与实施方案', 'level': 1, 'children': []},
        {'id': 'pricing', 'title': '报价与价格组成', 'level': 1, 'children': []},
        {'id': 'other', 'title': '其他材料', 'level': 1, 'children': []},
    ]
    by_id = {item['id']: item for item in chapters}
    for row in scoring_rows:
        parent_id = row.get('suggested_section') or 'technical'
        parent = by_id.get(parent_id) or by_id['technical']
        child_id = f"score_{row['seq']}"
        parent['children'].append({
            'id': child_id,
            'title': f"{row['item']}" + (f"（{row['score']}分）" if row.get('score') else ''),
            'level': 2,
            'children': [],
            'scoring_item': row['item'],
        })
    for title in extra_sections or []:
        if title and all(title not in chapter['title'] for chapter in chapters):
            chapters.append({
                'id': f'extra_{len(chapters) + 1}',
                'title': title,
                'level': 1,
                'children': [],
            })

    lines = [f'# {project_name or "未命名项目"} 投标文件目录（评分对齐）', '']
    section_flat: list[dict] = []
    counter = 0
    for chapter in chapters:
        counter += 1
        lines.append(f'{counter}. {chapter["title"]}')
        section_flat.append({
            'section_key': chapter['id'],
            'title': chapter['title'],
            'level': 1,
            'sort_order': len(section_flat),
            'body_markdown': '',
        })
        for child_index, child in enumerate(chapter.get('children') or [], start=1):
            lines.append(f'  {counter}.{child_index} {child["title"]}')
            section_flat.append({
                'section_key': child['id'],
                'title': child['title'],
                'level': 2,
                'sort_order': len(section_flat),
                'body_markdown': '',
            })
    lines.append('')
    coverage = compute_score_coverage(scoring_rows, section_flat)
    return {
        'outline_tree': {'chapters': chapters},
        'outline_markdown': '\n'.join(lines),
        'sections': section_flat,
        'scoring_matrix': scoring_rows,
        'score_coverage': coverage,
        'score_mapping': coverage.get('mapping') or {},
    }


def compute_score_coverage(scoring_rows: list[dict], sections: list[dict]) -> dict[str, Any]:
    titles = [str(section.get('title') or '') for section in sections]
    mapping: dict[str, str] = {}
    uncovered: list[dict] = []
    covered = 0
    for row in scoring_rows:
        item = str(row.get('item') or '')
        best_key = None
        best_score = 0.0
        tokens = _tokens(item)
        for section in sections:
            title = str(section.get('title') or '')
            score = _overlap(tokens, _tokens(title))
            if item and item in title:
                score = max(score, 0.9)
            if score > best_score:
                best_score = score
                best_key = section.get('section_key') or title
        if best_score >= 0.3 and best_key:
            covered += 1
            mapping[item] = str(best_key)
        else:
            uncovered.append({'item': item, 'score': row.get('score'), 'best_score': best_score})
    total = len(scoring_rows)
    rate = (covered / total) if total else 1.0
    return {
        'coverage_rate': round(rate, 4),
        'covered': covered,
        'total': total,
        'uncovered': uncovered,
        'mapping': mapping,
        'section_titles': titles,
    }


def _suggest_section(title: str, criteria: str) -> str:
    text = f'{title} {criteria}'
    if any(token in text for token in ('报价', '价格', '费用', '折扣')):
        return 'pricing'
    if any(token in text for token in ('资格', '资质', '业绩', '人员', '财务')):
        return 'qualification'
    if any(token in text for token in ('商务', '服务承诺', '售后', '质保')):
        return 'commercial'
    if any(token in text for token in ('技术', '方案', '实施', '功能', '性能', '系统')):
        return 'technical'
    return 'technical'


def _extract_score(text: str) -> float | None:
    match = re.search(r'(\d+(?:\.\d+)?)\s*分', text or '')
    if match:
        return float(match.group(1))
    match = re.search(r'(?:分值|得分|满分)[:：\s]*(\d+(?:\.\d+)?)', text or '')
    if match:
        return float(match.group(1))
    return None


def _tokens(text: str) -> set[str]:
    parts = re.findall(r'[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}', text or '')
    return {part.lower() for part in parts}


def _overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    inter = len(left & right)
    return inter / max(len(left), 1)
