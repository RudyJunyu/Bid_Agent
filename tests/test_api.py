import io
import json
from pathlib import Path

import pytest


def test_original_route_contracts_are_preserved(client):
    original = json.loads((Path(__file__).parent / 'fixtures/legacy_routes.json').read_text())
    schema = client.get('/openapi.json').json()['paths']
    for route in original:
        assert route['method'].lower() in schema[route['path']]


def test_health_readiness_and_cors(client):
    assert client.get('/health').json()['status'] == 'ok'
    assert client.get('/ready').json()['status'] == 'ready'
    result = client.get('/health', headers={'Origin': 'https://untrusted.example'})
    assert 'access-control-allow-origin' not in result.headers


def test_knowledge_crud_and_export(client):
    created = client.post('/knowledge/entries', json={
        'type': 'company', 'title': '容器回归公司', 'content': '软件服务',
    })
    assert created.status_code == 200, created.text
    entry = created.json()['entry']
    assert any(row['id'] == entry['id'] for row in client.get('/knowledge/entries').json()['entries'])
    assert client.get('/knowledge/export').status_code == 200
    assert client.delete('/knowledge/entries/' + entry['id']).status_code == 200
    assert all(row['id'] != entry['id'] for row in client.get('/knowledge/entries').json()['entries'])


def test_docx_upload_without_external_services(client):
    from docx import Document
    document = Document()
    document.add_heading('招标公告', 1)
    document.add_paragraph('项目名称：示例信息化建设项目。投标截止日期为2026年12月1日。')
    stream = io.BytesIO()
    document.save(stream)
    result = client.post('/bid-documents/upload', files={
        'file': ('招标.docx', stream.getvalue(), 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
    }, data={'parse_method': 'docx2python'})
    assert result.status_code == 200, result.text
    assert result.json()['sections']
    assert '示例信息化' in json.dumps(result.json(), ensure_ascii=False)


def test_pdf_upload_without_external_services(client):
    import fitz
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), 'Tender project: example. Submission deadline: 2026-12-01.')
        payload = document.tobytes()
    result = client.post('/bid-documents/upload', files={'file': ('bid.pdf', payload, 'application/pdf')},
                         data={'parse_method': 'pdfplumber'})
    assert result.status_code == 200, result.text
    assert 'Tender project' in json.dumps(result.json())


@pytest.mark.parametrize('endpoint', ['upload', 'upload-analyze', 'upload-analyze-stream'])
def test_empty_upload_is_rejected(client, endpoint):
    result = client.post('/bid-documents/' + endpoint, files={'file': ('empty.pdf', b'', 'application/pdf')})
    assert result.status_code == 422


def test_upload_limits_and_output_paths(client, monkeypatch):
    from bid_agent.api import uploads
    monkeypatch.setattr(uploads, 'MAX_UPLOAD_BYTES', 3)
    result = client.post('/bid-documents/upload', files={'file': ('large.pdf', b'1234', 'application/pdf')})
    assert result.status_code == 413
    result = client.post('/bid-documents/upload', files={'file': ('x.pdf', b'1', 'application/pdf')},
                         data={'output_dir': '/app/backend'})
    assert result.status_code == 422


def test_server_path_endpoint_is_disabled(client):
    assert client.post('/bid-documents/parse', json={'document': '/etc/passwd'}).status_code == 422
    assert client.get('/projects/nonexistent').status_code == 404


def test_model_selection_does_not_mutate_environment(monkeypatch):
    import os
    from bid_agent.core.model_config import resolve_llm_selection
    monkeypatch.setenv('LLM_MODEL_ID', 'original')
    monkeypatch.setenv('LLM_BASE_URL', 'https://original.example/v1')
    model, url = resolve_llm_selection('siliconflow', 'Qwen3-8B (轻量)')
    assert model == 'Qwen/Qwen3-8B'
    assert url == 'https://api.siliconflow.cn/v1'
    assert os.environ['LLM_MODEL_ID'] == 'original'
    assert os.environ['LLM_BASE_URL'] == 'https://original.example/v1'


def test_project_persistence_retrieval_generation_and_delete(client):
    from bid_agent.infrastructure.database import save_analysis_result
    from bid_agent.parsing.document_parser import split_bid_markdown_sections
    sections = split_bid_markdown_sections('# 招标公告\n项目名称：测试项目\n## 技术要求\n提供软件开发和部署服务。')
    saved = save_analysis_result(sections, {'project_overview': '项目名称：测试项目'}, file_name='test.docx')
    project_id = saved['project_id']
    assert saved['chunk_count'] > 0
    assert saved['vector_index']['enabled'] is False
    assert client.get('/projects/' + project_id).status_code == 200
    assert client.get('/projects/' + project_id + '/bid-outline').status_code == 200
    draft = client.post('/projects/' + project_id + '/bid-section-draft', json={'section_title': '技术方案'})
    assert draft.status_code == 200, draft.text
    assert draft.json()['draft_markdown']
    search = client.post('/vector/search', json={'query': '软件开发', 'project_id': project_id})
    assert search.status_code == 200, search.text
    assert search.json()['results']
    assert client.delete('/projects/' + project_id).status_code == 200
    assert client.get('/projects/' + project_id).status_code == 404


def test_section_generation_reaches_configured_model(client, monkeypatch):
    from bid_agent.api.routes import projects
    from bid_agent.schemas.requests import BidSectionDraftRequest
    captured = {}
    def build(**kwargs):
        captured.update(kwargs)
        return object()
    def generate(**kwargs):
        assert kwargs['llm'] is not None
        return {'draft_markdown': 'draft'}
    monkeypatch.setattr(projects, '_build_llm', build)
    monkeypatch.setattr('bid_agent.generation.section_writer.generate_bid_section_draft', generate)
    projects.create_project_bid_section_draft('example', BidSectionDraftRequest(section_title='技术方案', enable_deep_thinking=True))
    assert captured['enable_deep_thinking'] is True
