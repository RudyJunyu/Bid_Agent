"""B09 enterprise assets: versions, expiry, project link, generation filter."""
import io
from datetime import date, timedelta

from docx import Document


def _project(client):
    return client.post('/v1/projects', json={'title': '企业资产样例项目'}).json()


def _docx_bytes(text='证明材料'):
    document = Document()
    document.add_paragraph(text)
    stream = io.BytesIO()
    document.save(stream)
    return stream.getvalue()


def test_expired_asset_not_usable_and_flagged_in_review(client):
    project = _project(client)
    project_id = project['id']
    # Business expiry uses Asia/Shanghai calendar days.
    yesterday = (date.today() - timedelta(days=2)).isoformat()
    tomorrow = (date.today() + timedelta(days=30)).isoformat()

    expired = client.post(
        '/v1/enterprise-assets',
        json={
            'category': 'qualification',
            'title': 'ISO9001（已过期）',
            'subject_name': '测试公司',
            'expires_on': yesterday,
            'status': 'active',
        },
    )
    assert expired.status_code == 201, expired.text
    assert expired.json()['status'] == 'expired'
    assert expired.json()['usable'] is False

    valid = client.post(
        '/v1/enterprise-assets',
        json={
            'category': 'qualification',
            'title': '安全生产许可证',
            'subject_name': '测试公司',
            'expires_on': tomorrow,
            'status': 'active',
        },
    )
    assert valid.status_code == 201, valid.text
    assert valid.json()['usable'] is True

    uploaded = client.post(
        f'/v1/enterprise-assets/{valid.json()["id"]}/versions',
        files={
            'file': (
                'license.docx',
                _docx_bytes('安全生产许可证'),
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            ),
        },
        data={'notes': '初版'},
    )
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()['version']['version'] == 1

    client.post(f'/v1/projects/{project_id}/assets/{expired.json()["id"]}/link')
    client.post(f'/v1/projects/{project_id}/assets/{valid.json()["id"]}/link')

    linked = client.get(f'/v1/projects/{project_id}/assets')
    assert linked.status_code == 200
    assert len(linked.json()['assets']) == 2
    assert len(linked.json()['expired']) >= 1
    usable = client.get(f'/v1/projects/{project_id}/assets?usable_only=true')
    assert usable.status_code == 200
    assert len(usable.json()['assets']) == 1
    assert usable.json()['assets'][0]['title'] == '安全生产许可证'

    review = client.post(
        f'/v1/projects/{project_id}/review-runs',
        json={'use_llm': False},
    )
    assert review.status_code == 201, review.text
    titles = [item['title'] for item in review.json()['findings']]
    assert any('已过期' in title for title in titles)


def test_usable_only_list_excludes_draft_and_disabled(client):
    client.post(
        '/v1/enterprise-assets',
        json={'category': 'case', 'title': '草稿案例', 'status': 'draft'},
    )
    disabled = client.post(
        '/v1/enterprise-assets',
        json={'category': 'case', 'title': '停用案例', 'status': 'disabled'},
    )
    assert disabled.status_code == 201
    usable = client.get('/v1/enterprise-assets?usable_only=true')
    assert usable.status_code == 200
    titles = {item['title'] for item in usable.json()['assets']}
    assert '草稿案例' not in titles
    assert '停用案例' not in titles
