"""B14 export templates and DOCX structure checklist."""
import io

from docx import Document

from bid_agent.infrastructure.docx_export import build_bid_docx, inspect_docx_structure
from bid_agent.infrastructure.export_templates import filter_sections, get_template, list_templates


def test_builtin_templates_and_section_filter():
    templates = {item['id'] for item in list_templates()}
    assert {'full', 'technical', 'commercial', 'dark_technical'} <= templates
    sections = [
        {'section_key': 'cover', 'title': '封面', 'level': 1, 'sort_order': 0, 'body_markdown': ''},
        {'section_key': 'technical', 'title': '技术', 'level': 1, 'sort_order': 1, 'body_markdown': '方案'},
        {'section_key': 'score_1', 'title': '评分1', 'level': 2, 'sort_order': 2, 'body_markdown': ''},
        {'section_key': 'commercial', 'title': '商务', 'level': 1, 'sort_order': 3, 'body_markdown': ''},
        {'section_key': 'pricing', 'title': '报价', 'level': 1, 'sort_order': 4, 'body_markdown': ''},
    ]
    technical = filter_sections(sections, get_template('technical'))
    keys = {item['section_key'] for item in technical}
    assert 'technical' in keys and 'score_1' in keys
    assert 'pricing' not in keys
    commercial = filter_sections(sections, get_template('commercial'))
    assert {item['section_key'] for item in commercial} == {'cover', 'commercial', 'pricing'}


def test_docx_structure_has_toc_page_numbers_and_dark_cover():
    sections = [
        {
            'section_key': 'technical',
            'title': '技术方案',
            'level': 1,
            'sort_order': 0,
            'body_markdown': '响应正文【验收锚点】',
        },
    ]
    missing = [{
        'requirement_title': '★响应时间',
        'is_mandatory': True,
        'response_status': 'uncovered',
        'materials': ['待映射响应章节'],
    }]
    content = build_bid_docx(
        project_name='黄金样本项目',
        sections=sections,
        cover={'title': '黄金样本项目', 'bidder_name': '应被隐藏的公司'},
        missing_materials=missing,
        matrix_rows=[{
            'requirement_title': '技术方案完整性',
            'section_title': '技术方案',
            'response_status': 'drafted',
            'is_mandatory': True,
        }],
        template_id='dark_technical',
    )
    structure = inspect_docx_structure(content)
    assert structure['has_cover_marker']
    assert structure['has_toc']
    assert structure['has_page_numbers']
    assert structure['has_missing_appendix']
    assert structure['heading_count'] >= 2

    doc = Document(io.BytesIO(content))
    text = '\n'.join(p.text for p in doc.paragraphs)
    assert '暗标' in text
    assert '应被隐藏的公司' not in text
    assert '验收锚点' in text
    assert '缺失材料与待办清单' in text


def test_export_templates_api_and_template_export(client):
    # Lightweight API smoke: templates listing does not require a project.
    listed = client.get('/v1/export-templates')
    assert listed.status_code == 200
    payload = listed.json()
    assert payload['template_version']
    assert any(item['id'] == 'full' for item in payload['templates'])
    assert 'pdf_converter_available' in payload
