"""B07 draft: structured tender requirements with locatable evidence."""
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict


RequirementCategory = Literal[
    'overview',
    'qualification',
    'rejection',
    'commercial',
    'technical',
    'scoring',
]

ReviewStatus = Literal['draft', 'confirmed', 'rejected', 'conflict']


class SourceRef(BaseModel):
    block_id: str | None = None
    section_index: int | None = None
    section_path: list[str] = Field(default_factory=list)
    page: int | None = Field(default=None, ge=1)
    quote: str = Field(default='', max_length=2000)


class RequirementItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str
    project_id: str
    document_version_id: str
    job_id: str | None = None
    category: RequirementCategory
    field_key: str | None = None
    title: str
    raw_text: str
    normalized_value: str | None = None
    confidence: float = Field(ge=0, le=1)
    review_status: ReviewStatus = 'draft'
    source_refs: list[SourceRef] = Field(default_factory=list)
    extractor_version: str = 'b07-rule-v1'
    created_at: str
    updated_at: str


class RequirementExtractResponse(BaseModel):
    document_version_id: str
    job_id: str | None = None
    extractor_version: str
    counts: dict[str, int]
    items: list[RequirementItem]


class RequirementReviewBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    review_status: ReviewStatus
    normalized_value: str | None = Field(default=None, max_length=2000)
