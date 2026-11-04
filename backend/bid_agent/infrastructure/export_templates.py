"""Built-in DOCX export templates for bid packages (B14 draft)."""
from __future__ import annotations

from typing import Any

TEMPLATE_VERSION = 'export-template-v1'

TEMPLATES: dict[str, dict[str, Any]] = {
    'full': {
        'id': 'full',
        'label': '完整投标文件',
        'description': '封面、目录、全部章节、响应矩阵摘要与缺失材料附录。',
        'include_toc': True,
        'include_page_numbers': True,
        'include_matrix_appendix': True,
        'include_missing_appendix': True,
        'section_keys': None,  # all
        'dark_bid': False,
    },
    'technical': {
        'id': 'technical',
        'label': '技术标',
        'description': '封面、目录、技术与评分相关章节；适合技术标分册。',
        'include_toc': True,
        'include_page_numbers': True,
        'include_matrix_appendix': True,
        'include_missing_appendix': True,
        'section_keys': {'cover', 'technical', 'other'},
        'section_key_prefixes': ('score_',),
        'dark_bid': False,
    },
    'commercial': {
        'id': 'commercial',
        'label': '商务标',
        'description': '封面、目录、资格／商务／报价章节。',
        'include_toc': True,
        'include_page_numbers': True,
        'include_matrix_appendix': True,
        'include_missing_appendix': True,
        'section_keys': {'cover', 'qualification', 'commercial', 'pricing', 'other'},
        'section_key_prefixes': (),
        'dark_bid': False,
    },
    'dark_technical': {
        'id': 'dark_technical',
        'label': '暗标技术标',
        'description': '技术标分册；封面隐藏投标人名称，避免暗标标识泄露。',
        'include_toc': True,
        'include_page_numbers': True,
        'include_matrix_appendix': False,
        'include_missing_appendix': True,
        'section_keys': {'cover', 'technical', 'other'},
        'section_key_prefixes': ('score_',),
        'dark_bid': True,
    },
}


def list_templates() -> list[dict]:
    return [
        {
            'id': item['id'],
            'label': item['label'],
            'description': item['description'],
            'template_version': TEMPLATE_VERSION,
            'dark_bid': bool(item.get('dark_bid')),
        }
        for item in TEMPLATES.values()
    ]


def get_template(template_id: str | None) -> dict[str, Any]:
    key = (template_id or 'full').strip() or 'full'
    if key not in TEMPLATES:
        raise ValueError(f'未知导出模板：{key}；可选：{", ".join(TEMPLATES)}')
    return {**TEMPLATES[key], 'template_version': TEMPLATE_VERSION}


def filter_sections(sections: list[dict], template: dict[str, Any]) -> list[dict]:
    allowed = template.get('section_keys')
    prefixes = tuple(template.get('section_key_prefixes') or ())
    if allowed is None:
        return list(sections)
    result = []
    for section in sections:
        key = str(section.get('section_key') or '')
        if key in allowed or any(key.startswith(prefix) for prefix in prefixes):
            result.append(section)
        elif int(section.get('level') or 1) == 1 and key in allowed:
            result.append(section)
    # Keep scoring children whose parent technical is included even if prefix missed.
    return result
