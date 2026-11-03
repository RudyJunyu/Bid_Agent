"""Stage gates, scoring outline, compliance review, and DOCX export."""
import io

from docx import Document

from bid_agent.core.identity import Principal
from bid_agent.infrastructure.object_store import object_store
from bid_agent.repositories import requirements as requirement_repo


def _seed_project_with_version(client):
    project = client.post('/v1/projects', json={'title': '投标闭环样例项目'}).json()
    document = Document()
    document.add_heading('招标公告', 1)
    document.add_paragraph('项目名称：政务信息化运维项目。技术方案完整性 20分。报价合理性 10分。')
    stream = io.BytesIO()
    document.save(stream)
    stream.seek(0)
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
                'category': 'scoring',
                'title': '技术方案完整性',
                'raw_text': '技术方案完整性 20分',
                'normalized_value': '20分',
                'confidence': 0.9,
                'review_status': 'confirmed',
                'source_refs': [],
            },
            {
                'category': 'scoring',
                'title': '报价合理性',
                'raw_text': '报价合理性 10分',
                'normalized_value': '10分',
                'confidence': 0.9,
                'review_status': 'confirmed',
                'source_refs': [],
            },
            {
                'category': 'rejection',
                'title': '弄虚作假',
                'raw_text': '弄虚作假作废标处理',
                'normalized_value': '弄虚作假作废标处理',
                'confidence': 0.9,
                'review_status': 'confirmed',
                'source_refs': [],
            },
            {
                'category': 'technical',
                'title': '★响应时间',
                'raw_text': '★故障响应时间不超过2小时',
                'normalized_value': '★故障响应时间不超过2小时',
                'confidence': 0.8,
                'review_status': 'confirmed',
                'source_refs': [],
            },
        ],
    )
    return project['id'], version['id']


def test_outline_blocked_without_requirements_gate(client):
    project_id, version_id = _seed_project_with_version(client)
    blocked = client.post(
        f'/v1/projects/{project_id}/outline/from-requirements',
        json={'document_version_id': version_id},
    )
    assert blocked.status_code == 400
    assert '闸门' in blocked.json()['detail']


def test_full_pipeline_outline_review_export(client):
    project_id, version_id = _seed_project_with_version(client)
    stages = client.get(f'/v1/projects/{project_id}/stages').json()['stages']
    assert len(stages) == 5
    assert all(item['status'] == 'pending' for item in stages)

    passed = client.post(
        f'/v1/projects/{project_id}/stages/requirements',
        json={'status': 'passed', 'notes': '测试确认'},
    )
    assert passed.status_code == 200, passed.text
    assert passed.json()['passed'] is True

    outline = client.post(
        f'/v1/projects/{project_id}/outline/from-requirements',
        json={'document_version_id': version_id},
    )
    assert outline.status_code == 200, outline.text
    payload = outline.json()
    assert payload['score_coverage']['total'] == 2
    bid_id = payload['bid_version']['id']

    coverage = client.get(f'/v1/bid-versions/{bid_id}/score-coverage')
    assert coverage.status_code == 200
    assert 'coverage_rate' in coverage.json()['score_coverage']

    export_blocked = client.post(
        f'/v1/projects/{project_id}/export-jobs',
        json={'bid_version_id': bid_id},
    )
    assert export_blocked.status_code == 400

    review = client.post(
        f'/v1/projects/{project_id}/review-runs',
        json={'bid_version_id': bid_id, 'document_version_id': version_id, 'use_llm': False},
    )
    assert review.status_code == 201, review.text
    assert review.json()['summary']['finding_count'] >= 1
    finding_id = review.json()['findings'][0]['id']
    decided = client.post(
        f'/v1/review-findings/{finding_id}/decide',
        json={'decision_status': 'accepted', 'notes': '已核对'},
    )
    assert decided.status_code == 200
    assert decided.json()['decision_status'] == 'accepted'

    client.post(f'/v1/projects/{project_id}/stages/check', json={'status': 'passed'})
    exported = client.post(
        f'/v1/projects/{project_id}/export-jobs',
        json={'bid_version_id': bid_id, 'bidder_name': '测试公司'},
    )
    assert exported.status_code == 201, exported.text
    artifact = exported.json()['artifact']
    path = object_store.path(artifact['object_key'])
    assert path.exists()
    assert path.read_bytes()[:2] == b'PK'
    download = client.get(f'/v1/exports/{artifact["id"]}/download')
    assert download.status_code == 200
    assert download.content[:2] == b'PK'

    mineru = client.get('/v1/integrations/mineru')
    assert mineru.status_code == 200
    assert 'configured' in mineru.json()
