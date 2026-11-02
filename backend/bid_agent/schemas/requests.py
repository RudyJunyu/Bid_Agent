"""Extracted from the original API; public request contracts are retained."""
from typing import List, Optional
from pydantic import BaseModel, Field, model_validator
from bid_agent.core.settings import ALLOW_SERVER_PATHS
from bid_agent.analysis.service import BidAnalysisResult
from bid_agent.parsing.document_parser import BidDocumentSection

class ParseDocumentRequest(BaseModel):
    document: str = Field(description="Local file path or remote document URL.")
    output_dir: Optional[str] = Field(default=None)
    parse_method: str = Field(default="mineru_vlm")
    model_version: str = Field(default="vlm")
    llm_vendor: str = Field(default="siliconflow")
    llm_model: Optional[str] = Field(default=None)
    stream_output: bool = Field(default=True)
    enable_deep_thinking: bool = Field(default=False)
    language: str = Field(default="ch")
    is_ocr: Optional[bool] = Field(default=None)
    enable_formula: bool = Field(default=True)
    enable_table: bool = Field(default=True)
    page_ranges: Optional[str] = Field(default=None)
    poll_interval: int = Field(default=5, ge=1)
    timeout: int = Field(default=600, ge=30)


    @model_validator(mode="after")
    def validate_server_paths(self):
        if not ALLOW_SERVER_PATHS:
            if not self.document.startswith(("https://", "http://")):
                raise ValueError("Server file paths are disabled; use the upload endpoint")
            if self.output_dir:
                raise ValueError("Server output paths are disabled; omit output_dir")
        return self


class ParseDocumentResponse(BaseModel):
    sections: List[BidDocumentSection]
    parse_method_used: str = ""
    parse_method_recommended: str = ""
    parse_quality: dict = Field(default_factory=dict)


class AnalyzeDocumentResponse(BidAnalysisResult):
    pass


class AnalyzeContentRequest(BaseModel):
    file_content: str = Field(description="Edited parsed Markdown/text content.")
    llm_vendor: str = Field(default="siliconflow")
    llm_model: Optional[str] = Field(default=None)
    stream_output: bool = Field(default=True)
    enable_deep_thinking: bool = Field(default=False)


class ContentReviewRequest(BaseModel):
    sections: List[BidDocumentSection] = Field(default_factory=list)
    file_content: str = Field(default="")
    extracted: dict = Field(default_factory=dict)
    llm_vendor: str = Field(default="siliconflow")
    llm_model: Optional[str] = Field(default=None)
    enable_deep_thinking: bool = Field(default=False)


class ContentReviewResponse(BaseModel):
    content_review_markdown: str = ""
    content_review_report: dict = Field(default_factory=dict)


class VectorSearchRequest(BaseModel):
    query: str
    project_id: Optional[str] = None
    module: Optional[str] = None
    item_type: Optional[str] = None
    top_k: int = Field(default=8, ge=1, le=50)


class KnowledgeEntryRequest(BaseModel):
    id: Optional[str] = None
    type: str = Field(default="company")
    title: str
    tags: str = ""
    date: str = ""
    files: str = ""
    content: str = ""
    notes: str = ""
    createdAt: Optional[str] = None


class KnowledgeEntryResponse(BaseModel):
    entry: dict


class KnowledgeListResponse(BaseModel):
    entries: List[dict]


class KnowledgeImportRequest(BaseModel):
    store: dict = Field(default_factory=dict)


class KnowledgeImportResponse(BaseModel):
    imported_count: int


class ConfirmRecordRequest(BaseModel):
    status: str = Field(default="已确认")


class BidSectionDraftRequest(BaseModel):
    section_title: str = Field(min_length=1)
    outline_markdown: str = Field(default="")
    llm_vendor: str = Field(default="siliconflow")
    llm_model: Optional[str] = Field(default=None)
    enable_deep_thinking: bool = Field(default=False)
    enable_deep_thinking: bool = Field(default=False)

