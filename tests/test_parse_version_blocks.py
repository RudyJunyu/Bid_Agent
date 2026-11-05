from pathlib import Path

from bid_agent.parsing.document_parser import BidDocumentSection
from bid_agent.schemas.documents import ParseOptions
from bid_agent.services import document_parser as service


def test_parse_version_emits_table_blocks_with_bbox(monkeypatch, tmp_path: Path):
    pdf = tmp_path / 'sample.pdf'
    pdf.write_bytes(b'%PDF-1.4 sample')
    sha = __import__('hashlib').sha256(pdf.read_bytes()).hexdigest()

    sections = [
        BidDocumentSection(
            index=1,
            title='一、投标人须知前附表',
            level=2,
            content='| 条款 | 内容 |\n| --- | --- |\n| 3.1 | 采购人 |',
            markdown='一、投标人须知前附表\n<!-- table page=4 bbox=1.0,2.0,3.0,4.0 -->\n| 条款 | 内容 |\n| --- | --- |\n| 3.1 | 采购人 |',
            metadata={
                'title_path': ['第二章 投标人须知', '一、投标人须知前附表'],
                'page_start': 4,
                'page_end': 4,
                'tables': [
                    {
                        'headers': ['条款', '内容'],
                        'rows': [['3.1', '采购人']],
                        'row_count': 1,
                        'markdown': '| 条款 | 内容 |\n| --- | --- |\n| 3.1 | 采购人 |',
                        'page': 4,
                        'bbox': (1.0, 2.0, 3.0, 4.0),
                    }
                ],
            },
        )
    ]

    monkeypatch.setattr(service, 'inspect_document_profile', lambda _path: {
        'recommended_parse_method': 'pdfplumber',
        'image_count': 0,
    })
    monkeypatch.setattr(service, 'resolve_parse_method', lambda _path, method: (method or 'pdfplumber', 'test'))
    monkeypatch.setattr(service, 'parse_bid_document', lambda **_kwargs: sections)
    monkeypatch.setattr(service, 'build_parse_quality_report', lambda **_kwargs: {'level': '较好', 'score': 100})

    result = service.parse_version(
        {'id': 'dv_test', 'sha256': sha},
        pdf,
        ParseOptions(parse_method='pdfplumber'),
    )
    assert result.parser_version == 'bid-parser-v2'
    assert result.blocks[0].type == 'section'
    assert result.blocks[0].section_path == ['第二章 投标人须知', '一、投标人须知前附表']
    tables = [block for block in result.blocks if block.type == 'table']
    assert len(tables) == 1
    assert tables[0].page == 4
    assert tables[0].bbox == (1.0, 2.0, 3.0, 4.0)
