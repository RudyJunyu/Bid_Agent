"""Extracted from the original API; public request contracts are retained."""
from typing import Optional
from bid_agent.infrastructure.database import DB_PATH, KNOWLEDGE_TYPES, delete_knowledge_entry, export_knowledge_store, import_knowledge_store, list_knowledge_entries, upsert_knowledge_entry
from fastapi import APIRouter
from bid_agent.services.analysis_workflow import (
    _raise_api_error,
)
from bid_agent.schemas.requests import (
    KnowledgeEntryRequest,
    KnowledgeEntryResponse,
    KnowledgeImportRequest,
    KnowledgeImportResponse,
    KnowledgeListResponse,
)

router = APIRouter()

@router.get("/knowledge/types")
def get_knowledge_types() -> dict:
    return {
        "types": [
            {"id": key, "title": value}
            for key, value in KNOWLEDGE_TYPES.items()
        ]
    }


@router.get("/knowledge/entries", response_model=KnowledgeListResponse)
def get_knowledge_entries(
    type: Optional[str] = None,
    q: Optional[str] = None,
) -> KnowledgeListResponse:
    try:
        entries = list_knowledge_entries(entry_type=type, query=q)
    except Exception as exc:
        _raise_api_error(exc)
    return KnowledgeListResponse(entries=entries)


@router.post("/knowledge/entries", response_model=KnowledgeEntryResponse)
def save_knowledge_entry(request: KnowledgeEntryRequest) -> KnowledgeEntryResponse:
    try:
        entry = upsert_knowledge_entry(request.model_dump())
    except Exception as exc:
        _raise_api_error(exc)
    return KnowledgeEntryResponse(entry=entry)


@router.delete("/knowledge/entries/{entry_id}")
def remove_knowledge_entry(entry_id: str) -> dict:
    try:
        deleted = delete_knowledge_entry(entry_id)
    except Exception as exc:
        _raise_api_error(exc)
    return {"deleted": deleted}


@router.get("/knowledge/export")
def export_knowledge() -> dict:
    try:
        store = export_knowledge_store()
    except Exception as exc:
        _raise_api_error(exc)
    return {"store": store, "db_path": str(DB_PATH)}


@router.post("/knowledge/import", response_model=KnowledgeImportResponse)
def import_knowledge(request: KnowledgeImportRequest) -> KnowledgeImportResponse:
    try:
        count = import_knowledge_store(request.store)
    except Exception as exc:
        _raise_api_error(exc)
    return KnowledgeImportResponse(imported_count=count)

