from bid_agent.parsing.document_parser import BidDocumentSection
from bid_agent.schemas.documents import ParsedBlock
from bid_agent.services.requirement_extract import extract_requirements_from_parsed


def test_extract_overview_and_category_clauses_with_evidence():
    sections = [
        BidDocumentSection(
            index=1, title='第一章 招标公告', level=1,
            content='项目名称：安阳市政务信息化运维项目\n项目编号：安财招标采购-2026-23\n预算金额：7293656元\n采购人：安阳市政务大数据中心\n采购方式：公开招标',
            markdown='## 第一章 招标公告\n项目名称：安阳市政务信息化运维项目\n项目编号：安财招标采购-2026-23\n预算金额：7293656元\n采购人：安阳市政务大数据中心\n采购方式：公开招标',
            metadata={'title_path': ['第一章 招标公告'], 'page_start': 3},
        ),
        BidDocumentSection(
            index=2, title='2.申请人的资格要求：', level=2,
            content='投标人须具备独立法人资格。',
            markdown='## 2.申请人的资格要求：\n投标人须具备独立法人资格。',
            metadata={'title_path': ['第一章 招标公告', '2.申请人的资格要求：'], 'page_start': 4},
        ),
        BidDocumentSection(
            index=3, title='废标条款', level=2,
            content='有弄虚作假行为的，作废标处理。',
            markdown='## 废标条款\n有弄虚作假行为的，作废标处理。',
            metadata={'title_path': ['第三章 投标人须知', '废标条款'], 'page_start': 20},
        ),
        BidDocumentSection(
            index=4, title='第四章 评标办法（综合评分法）', level=1,
            content='技术部分 40 分，商务部分 20 分，价格 40 分。',
            markdown='## 第四章 评标办法（综合评分法）\n技术部分 40 分，商务部分 20 分，价格 40 分。',
            metadata={'title_path': ['第四章 评标办法（综合评分法）'], 'page_start': 50},
        ),
    ]
    blocks = [
        ParsedBlock(
            id='block_overview', type='section', text=sections[0].markdown,
            section_index=1, section_path=['第一章 招标公告'], page=3,
        ),
        ParsedBlock(
            id='block_qual', type='section', text=sections[1].markdown,
            section_index=2, section_path=['第一章 招标公告', '2.申请人的资格要求：'], page=4,
        ),
    ]
    items = extract_requirements_from_parsed(
        project_id='prj_demo',
        document_version_id='dv_demo',
        job_id='job_demo',
        parsed={'sections': sections, 'blocks': blocks},
    )
    categories = {item.category for item in items}
    assert 'overview' in categories
    assert 'qualification' in categories
    assert 'rejection' in categories
    assert 'scoring' in categories
    overview = [item for item in items if item.category == 'overview']
    assert any('安财招标采购-2026-23' in (item.normalized_value or '') for item in overview)
    assert any(item.source_refs and item.source_refs[0].block_id for item in overview)
