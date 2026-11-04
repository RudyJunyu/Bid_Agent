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
    sections = payload['bid_version']['sections']
    assert sections
    assert payload['bid_version']['content_stats']['total'] == len(sections)
    assert payload['bid_version']['content_stats']['filled'] == 0

    stages_after_outline = client.get(f'/v1/projects/{project_id}/stages').json()['stages']
    outline_stage = next(item for item in stages_after_outline if item['stage'] == 'outline')
    assert outline_stage['passed'] is True

    coverage = client.get(f'/v1/bid-versions/{bid_id}/score-coverage')
    assert coverage.status_code == 200
    assert 'coverage_rate' in coverage.json()['score_coverage']

    target = next(item for item in sections if item['section_key'] == 'technical')
    saved = client.patch(
        f'/v1/bid-sections/{target["id"]}',
        json={
            'body_markdown': '技术方案完整性响应：提供运维值班与应急预案。【验收锚点-章节正文】',
            'mark_generate_gate': True,
        },
    )
    assert saved.status_code == 200, saved.text
    assert '验收锚点-章节正文' in saved.json()['section']['body_markdown']
    assert saved.json()['content_stats']['filled'] == 1
    reloaded = client.get(f'/v1/bid-versions/{bid_id}')
    assert reloaded.status_code == 200
    reloaded_section = next(
        item for item in reloaded.json()['sections'] if item['id'] == target['id']
    )
    assert '验收锚点-章节正文' in reloaded_section['body_markdown']
    generate_stage = next(
        item for item in client.get(f'/v1/projects/{project_id}/stages').json()['stages']
        if item['stage'] == 'generate'
    )
    assert generate_stage['passed'] is True

    matrix = client.post(f'/v1/bid-versions/{bid_id}/response-matrix/rebuild')
    assert matrix.status_code == 200, matrix.text
    assert matrix.json()['summary']['total'] >= 3
    assert matrix.json()['summary']['mandatory_total'] >= 1
    matrix_row = next(
        item for item in matrix.json()['rows']
        if item['requirement_category'] == 'technical'
    )
    patched = client.patch(
        f'/v1/requirement-responses/{matrix_row["id"]}',
        json={'response_status': 'responded', 'response_summary': '已在技术章节响应'},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()['row']['response_status'] == 'responded'

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
    run_id = review.json()['id']
    first_finding_id = review.json()['findings'][0]['id']

    open_high_before = [
        item for item in review.json()['findings']
        if item['decision_status'] == 'open' and item['severity'] in {'high', 'critical'}
    ]
    if open_high_before:
        blocked_check = client.post(
            f'/v1/projects/{project_id}/stages/check',
            json={'status': 'passed'},
        )
        assert blocked_check.status_code == 400

    for finding in review.json()['findings']:
        if finding['decision_status'] != 'open':
            continue
        if finding['severity'] not in {'high', 'critical'}:
            continue
        decided = client.post(
            f'/v1/review-findings/{finding["id"]}/decide',
            json={'decision_status': 'accepted', 'notes': f'已核对：{finding["title"]}'},
        )
        assert decided.status_code == 200, decided.text

    approved = client.post(
        f'/v1/review-runs/{run_id}/approve',
        json={'approval_status': 'approved', 'notes': '高风险已处理'},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()['approval_status'] == 'approved'

    history = client.get(f'/v1/review-findings/{first_finding_id}/history')
    assert history.status_code == 200
    if open_high_before and first_finding_id in {item['id'] for item in open_high_before}:
        assert history.json()['events']

    audit_logs = client.get(f'/v1/projects/{project_id}/audit-logs')
    assert audit_logs.status_code == 200
    assert any(item['action'].startswith('review.') for item in audit_logs.json()['logs'])

    passed_check = client.post(
        f'/v1/projects/{project_id}/stages/check',
        json={'status': 'passed', 'notes': '审查已批准'},
    )
    assert passed_check.status_code == 200, passed_check.text
    exported = client.post(
        f'/v1/projects/{project_id}/export-jobs',
        json={'bid_version_id': bid_id, 'bidder_name': '测试公司'},
    )
    assert exported.status_code == 201, exported.text
    artifact = exported.json()['artifact']
    path = object_store.path(artifact['object_key'])
    assert path.exists()
    assert path.read_bytes()[:2] == b'PK'
    exported_doc = Document(str(path))
    text = '\n'.join(paragraph.text for paragraph in exported_doc.paragraphs)
    assert '验收锚点-章节正文' in text
    assert '缺失材料与待办清单' in text
    download = client.get(f'/v1/exports/{artifact["id"]}/download')
    assert download.status_code == 200
    assert download.content[:2] == b'PK'

    mineru = client.get('/v1/integrations/mineru')
    assert mineru.status_code == 200
    assert 'configured' in mineru.json()


def test_high_risk_decision_requires_notes_and_blocks_check(client):
    project_id, version_id = _seed_project_with_version(client)
    client.post(f'/v1/projects/{project_id}/stages/requirements', json={'status': 'passed'})
    bid_id = client.post(
        f'/v1/projects/{project_id}/outline/from-requirements',
        json={'document_version_id': version_id},
    ).json()['bid_version']['id']
    client.post(f'/v1/bid-versions/{bid_id}/response-matrix/rebuild')
    review = client.post(
        f'/v1/projects/{project_id}/review-runs',
        json={'bid_version_id': bid_id, 'document_version_id': version_id},
    ).json()
    high = next(
        (item for item in review['findings'] if item['severity'] in {'high', 'critical'}),
        review['findings'][0],
    )
    rejected = client.post(
        f'/v1/review-findings/{high["id"]}/decide',
        json={'decision_status': 'waived', 'notes': ''},
    )
    assert rejected.status_code == 400
    blocked = client.post(
        f'/v1/projects/{project_id}/stages/check',
        json={'status': 'passed'},
    )
    # If this finding is high/critical and still open, check must fail.
    if high['severity'] in {'high', 'critical'}:
        assert blocked.status_code == 400
    forced = client.post(
        f'/v1/projects/{project_id}/stages/check',
        json={'status': 'passed', 'force_skip_high_risk': True, 'notes': '业务签字强制通过'},
    )
    assert forced.status_code == 200, forced.text


def test_response_matrix_preserves_manual_status(client):
    project_id, version_id = _seed_project_with_version(client)
    client.post(f'/v1/projects/{project_id}/stages/requirements', json={'status': 'passed'})
    bid_id = client.post(
        f'/v1/projects/{project_id}/outline/from-requirements',
        json={'document_version_id': version_id},
    ).json()['bid_version']['id']
    first = client.post(f'/v1/bid-versions/{bid_id}/response-matrix/rebuild').json()
    row_id = first['rows'][0]['id']
    client.patch(
        f'/v1/requirement-responses/{row_id}',
        json={'response_status': 'waived', 'notes': '业务确认豁免', 'response_summary': '豁免说明'},
    )
    second = client.post(f'/v1/bid-versions/{bid_id}/response-matrix/rebuild').json()
    kept = next(item for item in second['rows'] if item['id'] == row_id)
    assert kept['response_status'] == 'waived'
    assert '豁免' in (kept['response_summary'] or kept['notes'] or '')


def test_section_seed_placeholder_and_reject_overwrite(client):
    project_id, version_id = _seed_project_with_version(client)
    client.post(f'/v1/projects/{project_id}/stages/requirements', json={'status': 'passed'})
    outline = client.post(
        f'/v1/projects/{project_id}/outline/from-requirements',
        json={'document_version_id': version_id},
    ).json()
    section_id = outline['bid_version']['sections'][0]['id']
    seeded = client.post(f'/v1/bid-sections/{section_id}/seed-placeholder', json={})
    assert seeded.status_code == 200, seeded.text
    assert '【待补充】' in seeded.json()['section']['body_markdown']
    blocked = client.post(f'/v1/bid-sections/{section_id}/seed-placeholder', json={})
    assert blocked.status_code == 400
    overwritten = client.post(
        f'/v1/bid-sections/{section_id}/seed-placeholder',
        json={'overwrite': True},
    )
    assert overwritten.status_code == 200
