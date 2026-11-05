from bid_agent.parsing.document_parser import (
    consolidate_bid_sections,
    split_bid_markdown_sections,
    _detect_heading,
    _extract_markdown_tables_json,
)
from bid_agent.parsing.normalize import normalize_bid_sections, preprocess_bid_markdown


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


def test_table_row_like_lines_are_not_headings():
    assert _detect_heading('3.1 采购人 安徽水利水电职业技术学院') is None
    assert _detect_heading('3.4.5 □是 ☑否') is None
    assert _detect_heading('8.1 2024 年 6 月 11 日 17 时 30 分') is None


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
    sections = normalize_bid_sections(consolidate_bid_sections(split_bid_markdown_sections(markdown)))
    titles = [section.title for section in sections]
    assert not any(title.startswith('第') and title.endswith('页') for title in titles)
    assert any('第一章' in title for title in titles)
    assert any('第二章' in title for title in titles)
    # Value-bearing numbered lines should live in content, not as their own sections.
    assert '1.1项目编号：安财招标采购-2026-23' not in titles
    basics = next(section for section in sections if '项目基本情况' in section.title)
    assert '安财招标采购-2026-23' in (basics.content or basics.markdown)


def test_duplicate_toc_chapters_are_dropped():
    markdown = '''目录

第一章 投标邀请
第二章 投标人须知

第一章 投标邀请

一、项目名称及内容
项目编号：2024BFAHZ01300
项目概况说明文字足够长以便正文识别。

第二章 投标人须知

一、投标人须知前附表
条款说明正文。
'''
    sections = normalize_bid_sections(consolidate_bid_sections(split_bid_markdown_sections(markdown)))
    chapter_titles = [section.title for section in sections if section.title.startswith('第') and '章' in section.title]
    assert chapter_titles.count('第一章 投标邀请') == 1
    assert chapter_titles.count('第二章 投标人须知') == 1
    assert sum(1 for section in sections if section.title == '第一章 投标邀请') == 1
    assert any('2024BFAHZ01300' in (section.content or section.markdown) for section in sections)


def test_front_table_rows_stay_under_attachment_heading():
    markdown = '''第二章 投标人须知

一、投标人须知前附表
注：本表是具体要求。
3.1 采购人 安徽水利水电职业技术学院
3.2 采购代理机构 安徽省政府采购中心
3.4.5 □是 ☑否
7.3 现场考察

二、投标人须知正文
7.招标文件构成
正文条款说明足够长以确认退出前附表区间。
'''
    sections = normalize_bid_sections(consolidate_bid_sections(split_bid_markdown_sections(markdown)))
    titles = [section.title for section in sections]
    assert '3.1 采购人 安徽水利水电职业技术学院' not in titles
    assert '3.4.5 □是 ☑否' not in titles
    assert '7.3 现场考察' not in titles
    front = next(section for section in sections if section.title == '一、投标人须知前附表')
    assert '安徽水利水电职业技术学院' in (front.content or front.markdown)
    assert '□是' in (front.content or front.markdown)
    assert any(section.title == '二、投标人须知正文' for section in sections)
    assert len(front.content or '') < 500


def test_dotted_toc_does_not_swallow_body_chapters():
    markdown = '''<!-- page:1 -->
封面文字

<!-- page:2 -->
目 录
第一章 投标邀请............................................................................................
第二章 投标人须知...........................................................................................
第八章 询问函范本..........................................................................96

<!-- page:3 -->
第一章 投标邀请
一、项目名称及内容
项目编号：2024BFAHZ01300
项目概况说明文字足够长以便正文识别并不被目录抑制。
二、投标人资格
详见公告。

第二章 投标人须知
一、投标人须知前附表
3.1 采购人 安徽水利水电职业技术学院
二、投标人须知正文
7.招标文件构成
须知正文内容。

第三章 采购需求
一、采购需求前附表
付款方式 一次性付清
二、货物需求
货物清单说明文字。
'''
    sections = normalize_bid_sections(consolidate_bid_sections(split_bid_markdown_sections(markdown)))
    titles = [section.title for section in sections]
    assert titles.count('第一章 投标邀请') == 1
    assert titles.count('第二章 投标人须知') == 1
    assert '第八章 询问函范本' not in titles
    invite = next(section for section in sections if section.title == '第一章 投标邀请')
    # Body subsections should exist under chapter 1, not be buried in 前言.
    assert any(section.title == '一、项目名称及内容' for section in sections)
    assert '2024BFAHZ01300' in (next(s for s in sections if '项目名称及内容' in s.title).content or '')
    front = next(section for section in sections if section.title == '一、采购需求前附表')
    assert '一次性付清' in (front.content or front.markdown)
    assert any(section.title == '二、货物需求' for section in sections)
    assert len(front.content or '') < 200
    preface = next((section for section in sections if section.title == '前言'), None)
    if preface:
        assert '项目编号：2024BFAHZ01300' not in (preface.content or '')


def test_inline_front_table_mention_does_not_enter_attachment_mode():
    markdown = '''第二章 投标人须知

二、投标人须知正文
17.3投标人在招标文件投标人须知前附表规定的解密时间内完成解密
18.开标
开标说明文字。
'''
    sections = normalize_bid_sections(consolidate_bid_sections(split_bid_markdown_sections(markdown)))
    titles = [section.title for section in sections]
    assert '18.开标' in titles or any('开标' in title for title in titles)


def test_chapter_dedupe_keeps_body_with_children_not_empty_reprint():
    markdown = '''第一章 投标邀请
一、项目名称及内容
项目编号：2024BFAHZ01300
项目概况说明文字足够长。
二、投标人资格
资格要求说明。

第二章 投标人须知
一、投标人须知前附表
3.1 采购人 示例单位
二、投标人须知正文
7.招标文件构成
须知正文。

第一章 投标邀请
第二章 投标人须知
第三章 采购需求
第四章 评标方法和标准
第五章 政府采购合同
第六章 投标文件格式
第七章 操作规程
第八章 询问函范本
简短残留。

第三章 采购需求
一、采购需求前附表
付款方式说明
二、货物需求
货物清单。
'''
    sections = normalize_bid_sections(consolidate_bid_sections(split_bid_markdown_sections(markdown)))
    titles = [section.title for section in sections]
    assert titles.count('第一章 投标邀请') == 1
    assert titles.count('第二章 投标人须知') == 1
    assert titles.count('第三章 采购需求') == 1
    # Mid-document empty chapter stack should not surface 第八章 before real 第三章 body.
    chapter_order = [title for title in titles if title.startswith('第') and '章' in title]
    assert chapter_order.index('第一章 投标邀请') < chapter_order.index('第二章 投标人须知')
    assert chapter_order.index('第二章 投标人须知') < chapter_order.index('第三章 采购需求')
    assert any(section.title == '一、项目名称及内容' for section in sections)
    assert '2024BFAHZ01300' in (
        next(section for section in sections if section.title == '一、项目名称及内容').content or ''
    )
    # Mid-doc empty chapter stack must not steal later body (e.g. 第八章 before 第三章).
    assert '第八章 询问函范本' not in titles or titles.index('第八章 询问函范本') > titles.index(
        '第三章 采购需求'
    )


def test_preprocess_strips_recurring_footers():
    markdown = '''<!-- page:1 -->
政府采购示范文本
正文第一页内容
第 1 页/共 3 页

<!-- page:2 -->
政府采购示范文本
正文第二页内容
第 2 页/共 3 页

<!-- page:3 -->
政府采购示范文本
正文第三页内容
第 3 页/共 3 页
'''
    cleaned = preprocess_bid_markdown(markdown)
    assert '第 1 页/共 3 页' not in cleaned
    assert '第 2 页/共 3 页' not in cleaned
    assert cleaned.count('政府采购示范文本') == 0
    assert '正文第一页内容' in cleaned
    assert '<!-- page:1 -->' in cleaned


def test_table_meta_comment_roundtrip():
    markdown = '''<!-- table page=3 bbox=10.5,20.0,100.25,200.5 -->
| 条款 | 内容 |
| --- | --- |
| 3.1 | 采购人 |
'''
    tables = _extract_markdown_tables_json(markdown)
    assert len(tables) == 1
    assert tables[0]['page'] == 3
    assert tables[0]['bbox'] == (10.5, 20.0, 100.25, 200.5)
    assert tables[0]['headers'] == ['条款', '内容']
