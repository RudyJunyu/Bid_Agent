"""Versioned, parser-independent output. Unknown physical coordinates remain null."""
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict

from bid_agent.parsing.document_parser import BidDocumentSection


class ParseOptions(BaseModel):
    model_config = ConfigDict(extra='forbid')
    parse_method: Literal['auto', 'pdfplumber', 'docx2python', 'docx2python_image_ocr', 'pymupdf4llm',
                          'docling', 'mineru_vlm', 'mineru_pipeline', 'mineru_parallel_pages', 'mineru_html'] = 'auto'
    model_version: Literal['vlm', 'pipeline'] = 'vlm'
    language: str = Field(default='ch', min_length=1, max_length=20)
    is_ocr: bool | None = None
    enable_formula: bool = True
    enable_table: bool = True
    page_ranges: str | None = Field(default=None, max_length=200)
    poll_interval: int = Field(default=5, ge=1, le=30)
    timeout: int = Field(default=600, ge=30, le=1800)


class ParsedBlock(BaseModel):
    id: str
    type: Literal['section', 'paragraph', 'table', 'image']
    text: str
    section_index: int
    section_path: list[str] = Field(default_factory=list)
    page: int | None = Field(default=None, ge=1)
    bbox: tuple[float, float, float, float] | None = None
    metadata: dict = Field(default_factory=dict)


class ParsedDocument(BaseModel):
    schema_version: str = '1.0'
    parser_version: str = 'bid-parser-v1'
    document_version_id: str
    source_sha256: str
    parse_method: str
    markdown: str
    sections: list[BidDocumentSection]
    blocks: list[ParsedBlock]
    quality: dict = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
