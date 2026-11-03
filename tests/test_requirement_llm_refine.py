from bid_agent.parsing.document_parser import BidDocumentSection
from bid_agent.schemas.documents import ParsedBlock
from bid_agent.services.requirement_extract import extract_requirements_from_parsed
from bid_agent.services.requirement_llm_refine import refine_requirements_with_llm


class _FakeLLM:
    def think_json(self, messages, schema, temperature=0):
        return """
        {
          "overview": [
            {
              "field_key": "open_time",
              "title": "开标时间",
              "value": "2026年8月10日09时00分",
              "quote": "5.1时间：2026年8月10日09 时00分（北京时间）"
            }
          ],
          "clauses": [
            {
              "category": "qualification",
              "title": "申请人的资格要求",
              "raw_text": "投标人须具备独立法人资格。",
              "quote": "投标人须具备独立法人资格。"
            }
          ]
        }
        """


def test_llm_refine_merges_overview_with_evidence():
    sections = [
        BidDocumentSection(
            index=1, title='5.开标时间和地点', level=2,
            content='5.1时间：2026年8月10日09 时00分（北京时间）',
            markdown='## 5.开标时间和地点\n5.1时间：2026年8月10日09 时00分（北京时间）',
            metadata={'title_path': ['5.开标时间和地点'], 'page_start': 5},
        ),
        BidDocumentSection(
            index=2, title='2.申请人的资格要求：', level=2,
            content='投标人须具备独立法人资格。',
            markdown='## 2.申请人的资格要求：\n投标人须具备独立法人资格。',
            metadata={'title_path': ['2.申请人的资格要求：'], 'page_start': 4},
        ),
    ]
    blocks = [
        ParsedBlock(
            id='block_open', type='section', text=sections[0].markdown,
            section_index=1, section_path=['5.开标时间和地点'], page=5,
        ),
        ParsedBlock(
            id='block_qual', type='section', text=sections[1].markdown,
            section_index=2, section_path=['2.申请人的资格要求：'], page=4,
        ),
    ]
    parsed = {'sections': sections, 'blocks': blocks}
    rule_items = extract_requirements_from_parsed(
        project_id='prj_demo',
        document_version_id='dv_demo',
        job_id='job_demo',
        parsed=parsed,
    )
    merged = refine_requirements_with_llm(
        project_id='prj_demo',
        document_version_id='dv_demo',
        job_id='job_demo',
        parsed=parsed,
        rule_items=rule_items,
        llm=_FakeLLM(),
    )
    overview = {item.field_key: item for item in merged if item.category == 'overview'}
    assert '2026年8月10日' in (overview['open_time'].normalized_value or '')
    assert overview['open_time'].source_refs and overview['open_time'].source_refs[0].block_id
    assert any(item.category == 'qualification' for item in merged)
    assert all(item.extractor_version == 'b07-hybrid-v1' for item in merged if item.category == 'overview')
