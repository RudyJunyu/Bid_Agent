from bid_agent.parsing.document_parser import (
    consolidate_bid_sections,
    split_bid_markdown_sections,
    _detect_heading,
)


def test_page_markdown_heading_is_ignored():
    assert _detect_heading('## 第 3 页') is None
    assert _detect_heading('第 12 页') is None


def test_chapter_heading_still_detected():
    assert _detect_heading('第一章 招标公告') == (1, '第一章 招标公告')
    assert _detect_heading('## 第二章 招标项目要求及采购需求') == (2, '第二章 招标项目要求及采购需求')


def test_numbered_value_line_is_not_heading():
    assert _detect_heading('1.1项目编号：安财招标采购-2026-23') is None
    assert _detect_heading('1.4预算金额：7293656元') is None
    assert _detect_heading('1.7本项目（是/否）接受联合体投标：否') is None
    assert _detect_heading('（1）供应商应当无不良信用记录。(未列入“信用中国”') is None
    # Trailing colon with no value is still a section title.
    assert _detect_heading('2.申请人的资格要求：') is not None


def test_numbered_title_without_value_is_heading():
    level_title = _detect_heading('1.项目基本情况')
    assert level_title is not None
    assert level_title[1].startswith('1.')


def test_split_and_consolidate_reduces_page_noise():
    markdown = '''<!-- page:1 -->

安阳市政务大数据中心
招标文件

<!-- page:2 -->

## 第 2 页

目录

第一章 招标公告

1.项目基本情况
1.1项目编号：安财招标采购-2026-23
1.2项目名称：示例项目

## 第 3 页

第二章 招标项目要求及采购需求

2.申请人的资格要求：
2.1满足政府采购法规定
'''
    sections = consolidate_bid_sections(split_bid_markdown_sections(markdown))
    titles = [section.title for section in sections]
    assert not any(title.startswith('第') and title.endswith('页') for title in titles)
    assert any('第一章' in title for title in titles)
    assert any('第二章' in title for title in titles)
    # Value-bearing numbered lines should live in content, not as their own sections.
    assert '1.1项目编号：安财招标采购-2026-23' not in titles
    basics = next(section for section in sections if '项目基本情况' in section.title)
    assert '安财招标采购-2026-23' in (basics.content or basics.markdown)
