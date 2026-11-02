"""Extracted from the original API; public request contracts are retained."""
from typing import Optional
from fastapi import HTTPException
from bid_agent.infrastructure.database import DB_PATH, delete_project, delete_project_record, get_project_detail, list_database_tables, list_projects, update_record_confirmed_status
from fastapi import APIRouter
from bid_agent.services.analysis_workflow import (
    _build_llm,
    _raise_api_error,
)
from bid_agent.schemas.requests import (
    BidSectionDraftRequest,
    ConfirmRecordRequest,
    VectorSearchRequest,
)

router = APIRouter()

@router.get("/database/tables")
def get_database_tables() -> dict:
    try:
        tables = list_database_tables()
    except Exception as exc:
        _raise_api_error(exc)
    return {"database_path": str(DB_PATH), "tables": tables}


@router.get("/projects")
def get_projects(q: Optional[str] = None) -> dict:
    try:
        projects = list_projects(query=q)
    except Exception as exc:
        _raise_api_error(exc)
    return {"projects": projects}


@router.get("/projects/{project_id}")
def get_project(project_id: str) -> dict:
    try:
        detail = get_project_detail(project_id)
    except Exception as exc:
        _raise_api_error(exc)
    if not detail:
        raise HTTPException(status_code=404, detail="Project not found")
    return detail


@router.post("/vector/search")
def vector_search(request: VectorSearchRequest) -> dict:
    try:
        from bid_agent.rag.vector_store import search_project_chunks

        return search_project_chunks(
            request.query,
            project_id=request.project_id,
            module=request.module,
            item_type=request.item_type,
            top_k=request.top_k,
        )
    except Exception as exc:
        _raise_api_error(exc)


@router.get("/projects/{project_id}/bid-outline")
def get_project_bid_outline(project_id: str) -> dict:
    try:
        from bid_agent.generation.outline import generate_bid_outline

        return generate_bid_outline(project_id)
    except Exception as exc:
        _raise_api_error(exc)


@router.get("/projects/bid-outline/{project_id}")
def get_project_bid_outline_alias(project_id: str) -> dict:
    return get_project_bid_outline(project_id)


@router.post("/projects/{project_id}/bid-section-draft")
def create_project_bid_section_draft(project_id: str, request: BidSectionDraftRequest) -> dict:
    try:
        from bid_agent.generation.section_writer import generate_bid_section_draft

        llm = None
        try:
            llm = _build_llm(
                llm_vendor=request.llm_vendor,
                llm_model=request.llm_model,
                enable_deep_thinking=request.enable_deep_thinking,
            )
        except Exception:
            llm = None
        return generate_bid_section_draft(
            project_id=project_id,
            section_title=request.section_title,
            outline_markdown=request.outline_markdown,
            llm=llm,
        )
    except Exception as exc:
        _raise_api_error(exc)


@router.post("/projects/bid-section-draft/{project_id}")
def create_project_bid_section_draft_alias(project_id: str, request: BidSectionDraftRequest) -> dict:
    return create_project_bid_section_draft(project_id, request)


@router.post("/projects/records/{table_name}/{record_id}/confirm")
def confirm_project_record(table_name: str, record_id: str, request: ConfirmRecordRequest) -> dict:
    try:
        record = update_record_confirmed_status(table_name, record_id, request.status)
    except Exception as exc:
        _raise_api_error(exc)
    return {"record": record}


@router.delete("/projects/{project_id}")
def remove_project(project_id: str) -> dict:
    try:
        result = delete_project(project_id)
        try:
            from bid_agent.rag.vector_store import delete_project_vectors

            result["vector_delete"] = delete_project_vectors(project_id)
        except Exception as vector_exc:
            result["vector_delete"] = {"enabled": False, "deleted": False, "reason": str(vector_exc)}
    except Exception as exc:
        _raise_api_error(exc)
    return result


@router.delete("/projects/records/{table_name}/{record_id}")
def remove_project_record(table_name: str, record_id: str) -> dict:
    try:
        result = delete_project_record(table_name, record_id)
    except Exception as exc:
        _raise_api_error(exc)
    return result

