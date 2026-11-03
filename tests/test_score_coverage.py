from bid_agent.services.score_coverage import (
    build_aligned_outline,
    compute_score_coverage,
    scoring_matrix_from_requirements,
)


def test_scoring_matrix_and_coverage():
    items = [
        {
            'id': 'r1',
            'category': 'scoring',
            'title': '技术方案完整性',
            'raw_text': '技术方案完整性 20分',
            'normalized_value': '20分：方案完整、可落地',
            'review_status': 'confirmed',
        },
        {
            'id': 'r2',
            'category': 'scoring',
            'title': '报价合理性',
            'raw_text': '报价合理性 10分',
            'normalized_value': '10分',
            'review_status': 'confirmed',
        },
        {
            'id': 'r3',
            'category': 'rejection',
            'title': '未递交保证金',
            'raw_text': '未递交保证金废标',
            'review_status': 'confirmed',
        },
    ]
    rows = scoring_matrix_from_requirements(items)
    assert len(rows) == 2
    assert rows[0]['score'] == 20
    built = build_aligned_outline(project_name='示例项目', scoring_rows=rows)
    assert '技术方案' in built['outline_markdown']
    coverage = compute_score_coverage(rows, built['sections'])
    assert coverage['total'] == 2
    assert coverage['covered'] >= 1
    assert 0 <= coverage['coverage_rate'] <= 1
