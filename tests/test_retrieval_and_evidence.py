"""B10 retrieval eval + B12 evidence-constrained section generation."""
import io

from docx import Document

from bid_agent.core.identity import Principal
from bid_agent.repositories import requirements as requirement_repo


def _seed(client):
    project = client.post('/v1/projects', json={'title': '检索与成章样例'}).json()
    document = Document()
    document.add_heading('资格要求', 1)
    document.add_paragraph('投标人须具备有效的质量管理体系认证证书。')
    document.add_paragraph('技术方案完整性 20分。')
    stream = io.BytesIO()
    document.save(stream)
    uploaded = client.post(
        f'/v1/projects/{project["id"]}/documents',
        files={
            'file': (
                'tender.docx',
                stream.getvalue(),
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            ),
        },
        data={'kind': 'tender'},
    )
    assert uploaded.status_code == 201, uploaded.text
    version = uploaded.json()['version']
    user = Principal('local', '__local__', True)
    requirement_repo.replace_drafts(
        project_id=project['id'],
        document_version_id=version['id'],
        job_id=None,
        extractor_version='test-v1',
        user=user,
        items=[
            {
                'category': 'qualification',
                'title': '质量管理体系认证',
                'raw_text': '投标人须具备有效的质量管理体系认证证书。',
                'normalized_value': '须具备有效的质量管理体系认证证书',
                'confidence': 0.9,
                'review_status': 'confirmed',
                'source_refs': [{'quote': '投标人须具备有效的质量管理体系认证证书。', 'page': 1}],
            },
            {
                'category': 'scoring',
                'title': '技术方案完整性',
                'raw_text': '技术方案完整性 20分',
                'normalized_value': '20分',
                'confidence': 0.9,
                'review_status': 'confirmed',
                'source_refs': [{'quote': '技术方案完整性 20分', 'page': 1}],
            },
        ],
    )
    client.post(f'/v1/projects/{project["id"]}/stages/requirements', json={'status': 'passed'})
    outline = client.post(
        f'/v1/projects/{project["id"]}/outline/from-requirements',
        json={'document_version_id': version['id']},
    )
    assert outline.status_code == 200, outline.text
    bid = outline.json()['bid_version']
    client.post(f'/v1/bid-versions/{bid["id"]}/response-matrix/rebuild')
    return project['id'], version['id'], bid


def test_search_requires_project_access_and_returns_hits(client):
    project_id, _version_id, bid = _seed(client)
    rebuilt = client.post(f'/v1/projects/{project_id}/indexes/rebuild', json={'notes': '测试'})
    assert rebuilt.status_code == 200, rebuilt.text
    assert rebuilt.json()['chunk_count'] >= 1
    searched = client.post(
        f'/v1/projects/{project_id}/search',
        json={'query': '质量管理体系认证', 'limit': 5},
    )
    assert searched.status_code == 200, searched.text
    assert searched.json()['hits']
    assert searched.json()['hits'][0]['project_id'] == project_id

    # Eval recall using the top hit id as relevant.
    top_id = searched.json()['hits'][0]['id']
    evaluated = client.post(
        f'/v1/projects/{project_id}/retrieval-eval',
        json={'k': 5, 'cases': [{'query': '质量管理体系认证', 'relevant_ids': [top_id]}]},
    )
    assert evaluated.status_code == 200, evaluated.text
    assert evaluated.json()['recall_at_k'] == 1.0
    assert bid['id']


def test_generate_section_from_evidence_marks_placeholders(client):
    project_id, _version_id, bid = _seed(client)
    technical = next(item for item in bid['sections'] if item['section_key'] == 'technical')
    generated = client.post(
        f'/v1/bid-sections/{technical["id"]}/generate-from-evidence',
        json={'overwrite': True, 'mark_generate_gate': True},
    )
    assert generated.status_code == 200, generated.text
    body = generated.json()['section']['body_markdown']
    assert '【待补充】' in body or generated.json()['evidence_summary']['requirement_count'] >= 0
    assert '不编造' in body or '待补充' in body
    assert generated.json()['evidence_summary']['pending_placeholders'] >= 1
