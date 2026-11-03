from bid_agent.analysis.rule_extractor import extract_rule_project_profile
from bid_agent.parsing.document_parser import BidDocumentSection
from bid_agent.schemas.documents import ParsedBlock
from bid_agent.services.requirement_extract import extract_requirements_from_parsed


def _anyang_announcement_sections() -> list[BidDocumentSection]:
    return [
        BidDocumentSection(
            index=1, title='1.项目基本情况', level=2,
            content=(
                '1.1项目编号：安财招标采购-2026-23\n'
                '1.2项目名称：安阳市政务大数据中心安阳市第二批市本级政务信息化运维项目\n'
                '1.3采购方式：公开招标\n'
                '1.4预算金额：7293656元\n'
                '1.7本项目（是/否）接受联合体投标：否\n'
            ),
            markdown=(
                '## 1.项目基本情况\n'
                '1.1项目编号：安财招标采购-2026-23\n'
                '1.7本项目（是/否）接受联合体投标：否\n'
            ),
            metadata={'title_path': ['第一章 招标公告', '1.项目基本情况'], 'page_start': 1},
        ),
        BidDocumentSection(
            index=2, title='4.提交投标文件截止时间（投标截止时间及地点）', level=2,
            content='4.1时间：2026年8月10日09 时00分（北京时间）\n4.2地点：安阳市公共资源交易平台',
            markdown=(
                '## 4.提交投标文件截止时间（投标截止时间及地点）\n'
                '4.1时间：2026年8月10日09 时00分（北京时间）\n'
                '4.2地点：安阳市公共资源交易平台'
            ),
            metadata={'title_path': ['第一章 招标公告', '4.提交投标文件截止时间（投标截止时间及地点）'], 'page_start': 4},
        ),
        BidDocumentSection(
            index=3, title='5.开标时间和地点', level=2,
            content='5.1时间：2026年8月10日09 时00分（北京时间）\n5.2地点：安阳市公共资源交易中心',
            markdown=(
                '## 5.开标时间和地点\n'
                '5.1时间：2026年8月10日09 时00分（北京时间）\n'
                '5.2地点：安阳市公共资源交易中心'
            ),
            metadata={'title_path': ['第一章 招标公告', '5.开标时间和地点'], 'page_start': 5},
        ),
    ]


def test_rule_profile_reads_datetime_on_next_line():
    profile = extract_rule_project_profile(_anyang_announcement_sections())
    assert '2026年8月10日' in str(profile.get('开标时间') or '')
    assert '09' in str(profile.get('开标时间') or '')
    assert '2026年8月10日' in str(profile.get('投标文件提交截止时间') or '')
    assert profile.get('是否允许联合体投标') == '否'


def test_requirement_extract_times_and_joint_venture_evidence():
    sections = _anyang_announcement_sections()
    blocks = [
        ParsedBlock(
            id='block_basics', type='section', text=sections[0].markdown,
            section_index=1, section_path=['1.项目基本情况'], page=1,
        ),
        ParsedBlock(
            id='block_deadline', type='section', text=sections[1].markdown,
            section_index=2, section_path=['4.提交投标文件截止时间（投标截止时间及地点）'], page=4,
        ),
        ParsedBlock(
            id='block_open', type='section', text=sections[2].markdown,
            section_index=3, section_path=['5.开标时间和地点'], page=5,
        ),
    ]
    items = extract_requirements_from_parsed(
        project_id='prj_demo',
        document_version_id='dv_demo',
        job_id='job_demo',
        parsed={'sections': sections, 'blocks': blocks},
    )
    overview = {item.field_key: item for item in items if item.category == 'overview'}
    assert '2026年8月10日' in (overview['open_time'].normalized_value or '')
    assert '2026年8月10日' in (overview['bid_deadline'].normalized_value or '')
    assert overview['open_time'].source_refs and overview['open_time'].source_refs[0].block_id
    assert overview['bid_deadline'].source_refs and overview['bid_deadline'].source_refs[0].block_id
    assert overview['joint_venture'].normalized_value == '否'
    assert overview['joint_venture'].source_refs and overview['joint_venture'].source_refs[0].block_id
