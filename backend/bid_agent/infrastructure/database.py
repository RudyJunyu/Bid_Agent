# -*- coding: utf-8 -*-
"""SQLite persistence demo for the bid agent."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from bid_agent.analysis.cleaner import clean_analysis_dict, is_duplicate_text

from bid_agent.core.settings import DB_PATH


KNOWLEDGE_TYPES = {
    "company": "公司信息",
    "qualification": "资质管理",
    "personnel": "人员信息",
    "finance": "财务信息",
    "performance": "业绩信息",
    "cases": "历史案例库",
    "bidFiles": "历史投标文件",
    "materials": "方案素材库",
}


TABLE_METADATA_HEADERS = {
    "business_requirements": ["\u6761\u6b3e", "\u8981\u6c42"],
    "technical_requirements": ["\u9879\u76ee", "\u53c2\u6570/\u8981\u6c42", "\u8bf4\u660e"],
    "qualification_requirements": ["\u5e8f\u53f7", "\u8d44\u683c\u8981\u6c42", "\u9700\u63d0\u4f9b\u8d44\u6599"],
    "rejection_items": ["\u5e8f\u53f7", "\u5e9f\u6807\u9879", "\u5177\u4f53\u8868\u73b0"],
    "scoring_items": ["\u8bc4\u5206\u9879", "\u8bc4\u5206\u6807\u51c6", "\u5206\u503c"],
}


def init_database(db_path: Path = DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    vector_index_result: dict[str, Any] = {}
    with _connect(db_path) as conn:
        conn.executescript(
            """
            create table if not exists projects (
                id text primary key,
                project_name text,
                project_code text,
                project_category text,
                buyer_name text,
                agency_name text,
                budget_amount real,
                status text default '待核对',
                created_at text not null,
                updated_at text not null
            );

            create table if not exists source_documents (
                id text primary key,
                project_id text,
                document_type text not null,
                file_name text not null,
                file_ext text,
                file_path text,
                parse_method text,
                parse_status text default '待解析',
                page_count integer,
                created_at text not null
            );

            create table if not exists document_sections (
                id text primary key,
                document_id text not null,
                project_id text not null,
                section_index integer not null,
                parent_section_id text,
                title text,
                level integer,
                page_start integer,
                page_end integer,
                markdown text not null,
                plain_text text,
                section_type text,
                metadata_json text default '{}',
                created_at text not null
            );

            create table if not exists document_chunks (
                id text primary key,
                project_id text,
                document_id text,
                section_id text,
                chunk_index integer not null default 0,
                chunk_type text not null,
                module text,
                title_path text,
                content text not null,
                content_markdown text,
                page_start integer,
                page_end integer,
                source_text text,
                tags_json text default '[]',
                metadata_json text default '{}',
                confirmed_status text default '未确认',
                created_at text not null
            );

            create table if not exists knowledge_entries (
                id text primary key,
                type text not null,
                title text not null,
                tags text default '',
                date_text text default '',
                files text default '',
                content text default '',
                notes text default '',
                created_at text not null,
                updated_at text not null
            );

            create index if not exists idx_knowledge_type on knowledge_entries(type);
            create index if not exists idx_sections_project on document_sections(project_id);
            create index if not exists idx_sections_document on document_sections(document_id);
            create index if not exists idx_chunks_project on document_chunks(project_id);

            create virtual table if not exists document_chunks_fts using fts5(
                chunk_id unindexed,
                project_id unindexed,
                module unindexed,
                item_type unindexed,
                section_id unindexed,
                title_path,
                content,
                metadata_text,
                tokenize = 'unicode61'
            );

            create table if not exists extraction_runs (
                id text primary key,
                project_id text not null,
                document_id text,
                run_type text not null,
                llm_vendor text,
                llm_model text,
                prompt_version text,
                input_chunk_ids_json text default '[]',
                status text not null,
                error_message text,
                started_at text not null,
                finished_at text
            );

            create table if not exists project_profile (
                id text primary key,
                project_id text not null,
                project_name text,
                project_code text,
                project_category text,
                service_period text,
                package_no text,
                budget_text text,
                budget_amount real,
                buyer_name text,
                agency_name text,
                industry_domain text,
                timeline_summary text,
                implementation_scope text,
                technical_features text,
                other_key_requirements text,
                is_sme_reserved integer,
                is_blind_bid integer,
                source_text text,
                confidence real,
                confirmed_status text default '未确认',
                created_at text not null,
                updated_at text not null
            );

            create table if not exists qualification_requirements (
                id text primary key,
                project_id text not null,
                review_type text not null,
                sequence_no text,
                requirement_text text not null,
                required_materials text,
                is_mandatory integer default 1,
                risk_level text,
                source_page_start integer,
                source_page_end integer,
                source_heading text,
                item_sequence text,
                source_text text,
                metadata_json text default '{}',
                chunk_id text,
                confirmed_status text default '未确认',
                created_at text not null
            );

            create table if not exists rejection_items (
                id text primary key,
                project_id text not null,
                sequence_no text,
                rejection_item text not null,
                specific_behavior text,
                risk_level text default '高',
                related_module text,
                check_method text,
                source_heading text,
                item_sequence text,
                source_text text,
                metadata_json text default '{}',
                chunk_id text,
                confirmed_status text default '未确认',
                created_at text not null
            );

            create table if not exists business_requirements (
                id text primary key,
                project_id text not null,
                requirement_type text not null,
                item_name text,
                requirement_text text not null,
                amount real,
                ratio real,
                deadline_text text,
                is_mandatory integer,
                source_heading text,
                item_sequence text,
                source_text text,
                metadata_json text default '{}',
                chunk_id text,
                confirmed_status text default '未确认',
                created_at text not null
            );

            create table if not exists technical_requirements (
                id text primary key,
                project_id text not null,
                requirement_group text,
                item_name text,
                parameter_name text,
                parameter_value text,
                requirement_text text not null,
                acceptance_criteria text,
                is_mandatory integer,
                importance_level text,
                source_heading text,
                item_sequence text,
                source_text text,
                metadata_json text default '{}',
                chunk_id text,
                confirmed_status text default '未确认',
                created_at text not null
            );

            create table if not exists scoring_items (
                id text primary key,
                project_id text not null,
                score_type text not null,
                parent_item_id text,
                item_name text not null,
                scoring_standard text not null,
                score_value real,
                score_text text,
                evidence_required text,
                self_assessment text,
                source_heading text,
                item_sequence text,
                source_text text,
                metadata_json text default '{}',
                chunk_id text,
                confirmed_status text default '未确认',
                created_at text not null
            );

            create table if not exists review_findings (
                id text primary key,
                project_id text not null,
                review_type text not null,
                module text not null,
                risk_level text not null,
                finding_title text not null,
                finding_detail text not null,
                source_text text,
                suggestion text,
                status text default '待处理',
                created_by text default '系统',
                created_at text not null
            );

            create table if not exists chunk_embeddings (
                id text primary key,
                chunk_id text not null,
                embedding_model text not null,
                embedding_dim integer not null,
                vector_store text not null,
                vector_id text not null,
                indexed_at text not null
            );

            create table if not exists companies (
                id text primary key,
                company_name text not null,
                short_name text,
                credit_code text,
                legal_representative text,
                registered_capital text,
                business_scope text,
                address text,
                contact_person text,
                contact_phone text,
                company_profile text,
                status text default '有效',
                created_at text not null,
                updated_at text not null
            );

            create table if not exists company_qualifications (
                id text primary key,
                company_id text,
                qualification_type text not null,
                qualification_name text not null,
                certificate_no text,
                issuer text,
                issue_date text,
                expire_date text,
                valid_status text default '待核对',
                file_path text,
                applicable_scope text,
                notes text,
                created_at text not null
            );

            create table if not exists company_personnel (
                id text primary key,
                company_id text,
                name text not null,
                role text,
                title text,
                certificates_json text default '[]',
                education text,
                years_experience real,
                project_experience text,
                file_path text,
                availability_status text default '可用',
                created_at text not null
            );

            create table if not exists financial_records (
                id text primary key,
                company_id text,
                record_type text not null,
                fiscal_year integer,
                revenue real,
                net_profit real,
                total_assets real,
                tax_status text,
                social_security_status text,
                file_path text,
                notes text,
                created_at text not null
            );

            create table if not exists performance_records (
                id text primary key,
                company_id text,
                project_name text not null,
                client_name text,
                industry_domain text,
                contract_amount real,
                contract_date text,
                acceptance_date text,
                project_scope text,
                proof_files_json text default '[]',
                reusable_points text,
                tags_json text default '[]',
                created_at text not null
            );

            create table if not exists historical_cases (
                id text primary key,
                case_title text not null,
                related_project_id text,
                industry_domain text,
                case_type text not null,
                summary text not null,
                success_factors text,
                failure_reasons text,
                risk_points text,
                reuse_suggestion text,
                tags_json text default '[]',
                created_at text not null
            );

            create table if not exists historical_bid_files (
                id text primary key,
                related_project_id text,
                file_type text not null,
                file_name text not null,
                file_path text,
                version text,
                project_name text,
                bid_result text,
                reusable_sections text,
                tags_json text default '[]',
                created_at text not null
            );

            create table if not exists solution_materials (
                id text primary key,
                material_type text not null,
                title text not null,
                content text not null,
                applicable_domain text,
                applicable_project_type text,
                quality_level text,
                source_case_id text,
                source_bid_file_id text,
                tags_json text default '[]',
                confirmed_status text default '未确认',
                created_at text not null,
                updated_at text not null
            );

            create table if not exists bid_generation_tasks (
                id text primary key,
                project_id text,
                task_type text not null,
                input_requirements_json text default '{}',
                retrieved_knowledge_ids_json text default '[]',
                output_markdown text,
                status text default '生成中',
                created_at text not null,
                updated_at text not null
            );
            """
        )
        _ensure_columns(
            conn,
            "business_requirements",
            {
                "source_heading": "text",
                "item_sequence": "text",
                "metadata_json": "text default '{}'",
            },
        )
        _ensure_columns(
            conn,
            "document_chunks",
            {
                "content_markdown": "text",
                "page_start": "integer",
                "page_end": "integer",
            },
        )
        _ensure_columns(
            conn,
            "document_sections",
            {
                "metadata_json": "text default '{}'",
            },
        )
        for table_name in ("qualification_requirements", "rejection_items", "scoring_items"):
            _ensure_columns(
                conn,
                table_name,
                {
                    "source_heading": "text",
                    "item_sequence": "text",
                    "metadata_json": "text default '{}'",
                },
            )
        _ensure_columns(
            conn,
            "technical_requirements",
            {
                "source_heading": "text",
                "item_sequence": "text",
                "metadata_json": "text default '{}'",
            },
        )
        _backfill_table_cell_header_maps(conn)
        _backfill_project_budget_amounts(conn)
        _rebuild_document_chunks_fts_if_empty(conn)


def list_knowledge_entries(
    entry_type: str | None = None,
    query: str | None = None,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    init_database(db_path)
    sql = "select * from knowledge_entries"
    params: list[Any] = []
    where = []
    if entry_type:
        where.append("type = ?")
        params.append(entry_type)
    if query:
        like = f"%{query}%"
        where.append(
            "(title like ? or tags like ? or date_text like ? or files like ? or content like ? or notes like ?)"
        )
        params.extend([like, like, like, like, like, like])
    if where:
        sql += " where " + " and ".join(where)
    sql += " order by updated_at desc"
    with _connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_knowledge_row_to_dict(row) for row in rows]


def get_knowledge_entry(entry_id: str, db_path: Path = DB_PATH) -> dict[str, Any] | None:
    init_database(db_path)
    with _connect(db_path) as conn:
        row = conn.execute("select * from knowledge_entries where id = ?", (entry_id,)).fetchone()
    return _knowledge_row_to_dict(row) if row else None


def upsert_knowledge_entry(data: dict[str, Any], db_path: Path = DB_PATH) -> dict[str, Any]:
    init_database(db_path)
    now = _now()
    entry_id = str(data.get("id") or f"kb_{uuid4().hex}")
    entry_type = str(data.get("type") or "company")
    if entry_type not in KNOWLEDGE_TYPES:
        raise ValueError(f"Unsupported knowledge type: {entry_type}")
    title = str(data.get("title") or "").strip()
    if not title:
        raise ValueError("Knowledge title is required.")

    existing = get_knowledge_entry(entry_id, db_path)
    created_at = existing["createdAt"] if existing else str(data.get("createdAt") or now)
    payload = {
        "id": entry_id,
        "type": entry_type,
        "title": title,
        "tags": str(data.get("tags") or "").strip(),
        "date_text": str(data.get("date") or data.get("dateText") or "").strip(),
        "files": str(data.get("files") or "").strip(),
        "content": str(data.get("content") or "").strip(),
        "notes": str(data.get("notes") or "").strip(),
        "created_at": created_at,
        "updated_at": now,
    }

    with _connect(db_path) as conn:
        conn.execute(
            """
            insert into knowledge_entries
                (id, type, title, tags, date_text, files, content, notes, created_at, updated_at)
            values
                (:id, :type, :title, :tags, :date_text, :files, :content, :notes, :created_at, :updated_at)
            on conflict(id) do update set
                type = excluded.type,
                title = excluded.title,
                tags = excluded.tags,
                date_text = excluded.date_text,
                files = excluded.files,
                content = excluded.content,
                notes = excluded.notes,
                updated_at = excluded.updated_at
            """,
            payload,
        )
    entry = get_knowledge_entry(entry_id, db_path)
    if not entry:
        raise RuntimeError("Knowledge entry save failed.")
    return entry


def delete_knowledge_entry(entry_id: str, db_path: Path = DB_PATH) -> bool:
    init_database(db_path)
    with _connect(db_path) as conn:
        cursor = conn.execute("delete from knowledge_entries where id = ?", (entry_id,))
    return cursor.rowcount > 0


def export_knowledge_store(db_path: Path = DB_PATH) -> dict[str, list[dict[str, Any]]]:
    entries = list_knowledge_entries(db_path=db_path)
    store: dict[str, list[dict[str, Any]]] = {key: [] for key in KNOWLEDGE_TYPES}
    for entry in entries:
        store.setdefault(entry["type"], []).append(entry)
    return store


def import_knowledge_store(store: dict[str, Any], db_path: Path = DB_PATH) -> int:
    init_database(db_path)
    count = 0
    for entry_type, entries in (store or {}).items():
        if entry_type not in KNOWLEDGE_TYPES or not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry = {**entry, "type": entry.get("type") or entry_type}
            upsert_knowledge_entry(entry, db_path)
            count += 1
    return count


PROJECT_DETAIL_TABLES = {
    "project_profile": "项目概览",
    "business_requirements": "商务要求",
    "technical_requirements": "技术要求",
    "qualification_requirements": "资格审查",
    "rejection_items": "废标项",
    "scoring_items": "评分项",
    "review_findings": "审查发现",
    "source_documents": "来源文件",
    "document_sections": "文档章节",
    "document_chunks": "语义切片",
    "extraction_runs": "抽取任务",
}


CONFIRMABLE_TABLES = {
    "project_profile",
    "business_requirements",
    "technical_requirements",
    "qualification_requirements",
    "rejection_items",
    "scoring_items",
    "document_chunks",
    "solution_materials",
}

PROJECT_SCOPED_TABLES = {
    "source_documents",
    "document_sections",
    "document_chunks",
    "extraction_runs",
    "project_profile",
    "qualification_requirements",
    "rejection_items",
    "business_requirements",
    "technical_requirements",
    "scoring_items",
    "review_findings",
}

DELETABLE_PROJECT_RECORD_TABLES = PROJECT_SCOPED_TABLES - {"extraction_runs", "source_documents"}


def list_projects(
    query: str | None = None,
    db_path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    init_database(db_path)
    sql = """
        select
            p.*,
            count(distinct d.id) as document_count,
            count(distinct c.id) as chunk_count
        from projects p
        left join source_documents d on d.project_id = p.id
        left join document_chunks c on c.project_id = p.id
    """
    params: list[Any] = []
    if query:
        like = f"%{query}%"
        sql += """
            where p.project_name like ?
               or p.project_code like ?
               or p.buyer_name like ?
               or p.agency_name like ?
        """
        params.extend([like, like, like, like])
    sql += " group by p.id order by p.updated_at desc, p.created_at desc"
    with _connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_project_row_to_dict(row) for row in rows]


def get_project_detail(project_id: str, db_path: Path = DB_PATH) -> dict[str, Any] | None:
    init_database(db_path)
    with _connect(db_path) as conn:
        project = conn.execute("select * from projects where id = ?", (project_id,)).fetchone()
        if not project:
            return None
        tables: dict[str, Any] = {}
        for table_name, title in PROJECT_DETAIL_TABLES.items():
            order_by = _project_table_order_by(table_name)
            rows = conn.execute(
                f"select * from {quote_identifier(table_name)} where project_id = ? {order_by}",
                (project_id,),
            ).fetchall()
            tables[table_name] = {
                "title": title,
                "rows": [_row_to_dict(row) for row in rows],
            }
    return {
        "project": _row_to_dict(project),
        "tables": tables,
    }


def update_record_confirmed_status(
    table_name: str,
    record_id: str,
    status: str,
    db_path: Path = DB_PATH,
) -> dict[str, Any]:
    init_database(db_path)
    if table_name not in CONFIRMABLE_TABLES:
        raise ValueError(f"Table is not confirmable: {table_name}")
    normalized_status = status if status in {"未确认", "已确认", "需复核"} else "未确认"
    with _connect(db_path) as conn:
        row = conn.execute(
            f"select * from {quote_identifier(table_name)} where id = ?",
            (record_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Record not found: {record_id}")
        conn.execute(
            f"update {quote_identifier(table_name)} set confirmed_status = ? where id = ?",
            (normalized_status, record_id),
        )
        updated = conn.execute(
            f"select * from {quote_identifier(table_name)} where id = ?",
            (record_id,),
        ).fetchone()
    return _row_to_dict(updated)


def delete_project(project_id: str, db_path: Path = DB_PATH) -> dict[str, Any]:
    init_database(db_path)
    deleted: dict[str, int] = {}
    with _connect(db_path) as conn:
        project = conn.execute("select id from projects where id = ?", (project_id,)).fetchone()
        if not project:
            return {"deleted": False, "tables": deleted}
        for table_name in PROJECT_SCOPED_TABLES:
            cursor = conn.execute(
                f"delete from {quote_identifier(table_name)} where project_id = ?",
                (project_id,),
            )
            deleted[table_name] = cursor.rowcount
        conn.execute("delete from document_chunks_fts where project_id = ?", (project_id,))
        cursor = conn.execute("delete from projects where id = ?", (project_id,))
        deleted["projects"] = cursor.rowcount
    return {"deleted": True, "tables": deleted}


def delete_project_record(
    table_name: str,
    record_id: str,
    db_path: Path = DB_PATH,
) -> dict[str, Any]:
    init_database(db_path)
    if table_name not in DELETABLE_PROJECT_RECORD_TABLES:
        raise ValueError(f"Table is not deletable: {table_name}")
    with _connect(db_path) as conn:
        row = conn.execute(
            f"select * from {quote_identifier(table_name)} where id = ?",
            (record_id,),
        ).fetchone()
        if not row:
            return {"deleted": False, "record": None}
        cursor = conn.execute(
            f"delete from {quote_identifier(table_name)} where id = ?",
            (record_id,),
        )
        if table_name == "document_chunks":
            conn.execute("delete from document_chunks_fts where chunk_id = ?", (record_id,))
    return {"deleted": cursor.rowcount > 0, "record": _row_to_dict(row)}


def save_analysis_result(
    sections: list[Any],
    analysis: dict[str, Any],
    *,
    file_name: str = "uploaded_document",
    document_type: str = "招标文件",
    parse_method: str = "",
    db_path: Path = DB_PATH,
) -> dict[str, Any]:
    """Persist parsed sections and five extracted modules into SQLite demo tables."""
    init_database(db_path)
    analysis = clean_analysis_dict(analysis)
    now = _now()
    project_id = f"prj_{uuid4().hex}"
    document_id = f"doc_{uuid4().hex}"
    profile_values = _parse_project_profile(analysis.get("project_overview", ""))
    project_name = profile_values.get("项目名称") or "未命名项目"
    project_code = profile_values.get("项目编号") or ""

    with _connect(db_path) as conn:
        conn.execute(
            """
            insert into projects
                (id, project_name, project_code, project_category, buyer_name, agency_name, budget_amount, status, created_at, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                project_name,
                project_code,
                profile_values.get("项目类别（服务类，货物类，工程类）和服务年限", ""),
                profile_values.get("招标人", ""),
                profile_values.get("招标代理机构", ""),
                _extract_budget_amount(profile_values),
                "待核对",
                now,
                now,
            ),
        )
        conn.execute(
            """
            insert into source_documents
                (id, project_id, document_type, file_name, file_ext, file_path, parse_method, parse_status, page_count, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                project_id,
                document_type,
                file_name,
                Path(file_name).suffix.lstrip(".").lower(),
                file_name,
                parse_method,
                "解析成功",
                None,
                now,
            ),
        )

        chunk_ids = _insert_sections_as_chunks(conn, project_id, document_id, sections, now)
        chunk_ids.extend(
            _insert_image_analysis_chunks(
                conn,
                project_id=project_id,
                document_id=document_id,
                items=analysis.get("image_analysis_items", []),
                now=now,
            )
        )
        _insert_project_profile(conn, project_id, analysis.get("project_overview", ""), profile_values, now)
        structured = analysis.get("structured_extraction") if isinstance(analysis.get("structured_extraction"), dict) else {}
        if structured:
            tech_refs = _insert_technical_requirements_structured(conn, project_id, structured.get("technical_scoring_requirements", {}), now)
            scoring_refs = _insert_scoring_items_structured(conn, project_id, structured.get("price_scoring_requirements", {}), now)
            _insert_business_requirements_structured(
                conn,
                project_id,
                structured.get("business_content", {}),
                now,
                tech_refs=tech_refs,
                scoring_refs=scoring_refs,
            )
            _insert_qualification_and_rejection_structured(conn, project_id, structured.get("qualification_compliance_requirements", {}), now)
        else:
            _insert_business_requirements(conn, project_id, analysis.get("business_content", ""), now)
            _insert_technical_requirements(conn, project_id, analysis.get("technical_scoring_requirements", ""), now)
            _insert_qualification_and_rejection(conn, project_id, analysis.get("qualification_compliance_requirements", ""), now)
            _insert_scoring_items(conn, project_id, analysis.get("price_scoring_requirements", ""), now)
        _insert_review_findings(conn, project_id, analysis.get("content_review_markdown", ""), now)

        conn.execute(
            """
            insert into extraction_runs
                (id, project_id, document_id, run_type, status, started_at, finished_at, input_chunk_ids_json)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"run_{uuid4().hex}",
                project_id,
                document_id,
                "五大模块结构化入库",
                "成功",
                now,
                now,
                dumps_json(chunk_ids),
            ),
        )

    try:
        from bid_agent.rag.vector_store import index_project_chunks

        vector_index_result = index_project_chunks(project_id, db_path=db_path)
    except Exception as exc:
        vector_index_result = {"enabled": False, "indexed": 0, "reason": str(exc)}

    return {
        "project_id": project_id,
        "document_id": document_id,
        "chunk_count": len(chunk_ids),
        "project_name": project_name,
        "database_path": str(db_path),
        "vector_index": vector_index_result,
    }


def list_database_tables(db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    init_database(db_path)
    with _connect(db_path) as conn:
        table_rows = conn.execute(
            "select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name"
        ).fetchall()
        output = []
        for row in table_rows:
            name = row["name"]
            count = conn.execute(f"select count(*) as count from {name}").fetchone()["count"]
            output.append({"name": name, "count": count})
    return output


@contextmanager
def _connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _ensure_columns(conn: sqlite3.Connection, table_name: str, columns: dict[str, str]) -> None:
    existing = {
        row["name"]
        for row in conn.execute(f"pragma table_info({quote_identifier(table_name)})").fetchall()
    }
    for column_name, column_type in columns.items():
        if column_name not in existing:
            conn.execute(
                f"alter table {quote_identifier(table_name)} add column {quote_identifier(column_name)} {column_type}"
            )


def _backfill_table_cell_header_maps(conn: sqlite3.Connection) -> None:
    for table_name, default_headers in TABLE_METADATA_HEADERS.items():
        rows = conn.execute(
            f"""
            select id, metadata_json
            from {quote_identifier(table_name)}
            where metadata_json like '%"cells"%'
              and metadata_json not like '%"cell_header_map"%'
            """
        ).fetchall()
        for row in rows:
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(metadata, dict):
                continue
            cells = metadata.get("cells")
            if not isinstance(cells, list) or not cells:
                continue
            cell_values = [str(cell).strip() for cell in cells]
            header_paths = metadata.get("header_paths")
            if not isinstance(header_paths, list) or not header_paths:
                header_paths = default_headers[: len(cell_values)]
            header_values = [
                str(header).strip() if str(header).strip() else f"col_{index + 1}"
                for index, header in enumerate(header_paths)
            ]
            while len(header_values) < len(cell_values):
                header_values.append(f"col_{len(header_values) + 1}")
            header_values = header_values[: len(cell_values)]
            metadata["cells"] = cell_values
            metadata["header_paths"] = header_values
            metadata["cell_header_map"] = {
                header_values[index]: cell
                for index, cell in enumerate(cell_values)
            }
            metadata["parent_table_header"] = metadata.get("parent_table_header") or " > ".join(header_values)
            metadata["source_format"] = metadata.get("source_format") or "markdown_table"
            conn.execute(
                f"update {quote_identifier(table_name)} set metadata_json = ? where id = ?",
                (json.dumps(metadata, ensure_ascii=False), row["id"]),
            )


def _backfill_project_budget_amounts(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        select p.id, p.project_name, p.budget_amount, pp.budget_text, pp.package_no
        from projects p
        left join project_profile pp on pp.project_id = p.id
        where pp.budget_text is not null and trim(pp.budget_text) <> ''
        """
    ).fetchall()
    for row in rows:
        package_hint = str(row["package_no"] or "")
        if not package_hint:
            match = re.search(r"(?:包|第)\s*([A-Za-z0-9一二三四五六七八九十]+)\s*(?:包)?", str(row["project_name"] or ""))
            package_hint = match.group(1) if match else ""
        amount = _extract_budget_amount(str(row["budget_text"] or ""), package_hint=package_hint)
        if amount is None:
            continue
        current = row["budget_amount"]
        if current is None or abs(float(current) - amount) > 0.01:
            conn.execute(
                "update projects set budget_amount = ?, updated_at = ? where id = ?",
                (amount, _now(), row["id"]),
            )
            conn.execute(
                "update project_profile set budget_amount = ?, updated_at = ? where project_id = ?",
                (amount, _now(), row["id"]),
            )


def _rebuild_document_chunks_fts_if_empty(conn: sqlite3.Connection) -> None:
    try:
        count = conn.execute("select count(*) as count from document_chunks_fts").fetchone()["count"]
    except sqlite3.OperationalError:
        return
    if int(count or 0) > 0:
        return
    rows = conn.execute("select * from document_chunks").fetchall()
    for row in rows:
        _upsert_document_chunk_fts(conn, dict(row))


def _upsert_document_chunk_fts(conn: sqlite3.Connection, chunk: dict[str, Any]) -> None:
    metadata = _safe_json_loads(chunk.get("metadata_json"), {})
    item_type = str(metadata.get("item_type") or chunk.get("chunk_type") or "")
    metadata_text = " ".join(
        str(value)
        for value in (
            metadata.get("hierarchy_path"),
            metadata.get("parent_table_header"),
            metadata.get("source_format"),
            metadata.get("vector_role"),
            metadata.get("image_id"),
            metadata.get("ocr_text"),
            metadata.get("ai_note"),
        )
        if value
    )
    conn.execute("delete from document_chunks_fts where chunk_id = ?", (chunk.get("id"),))
    conn.execute(
        """
        insert into document_chunks_fts
            (chunk_id, project_id, module, item_type, section_id, title_path, content, metadata_text)
        values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(chunk.get("id") or ""),
            str(chunk.get("project_id") or ""),
            str(chunk.get("module") or metadata.get("module") or ""),
            item_type,
            str(chunk.get("section_id") or ""),
            str(chunk.get("title_path") or ""),
            "\n".join(
                part
                for part in (
                    str(chunk.get("content") or ""),
                    str(chunk.get("content_markdown") or ""),
                    str(chunk.get("source_text") or ""),
                )
                if part
            ),
            metadata_text,
        ),
    )


def _safe_json_loads(value: Any, default: Any) -> Any:
    try:
        return json.loads(value or "{}")
    except Exception:
        return default


def _knowledge_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "type": row["type"],
        "title": row["title"],
        "tags": row["tags"],
        "date": row["date_text"],
        "files": row["files"],
        "content": row["content"],
        "notes": row["notes"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    return dict(row) if row else {}


def _project_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = _row_to_dict(row)
    return {
        "id": data.get("id"),
        "projectName": data.get("project_name") or "未命名项目",
        "projectCode": data.get("project_code") or "",
        "projectCategory": data.get("project_category") or "",
        "buyerName": data.get("buyer_name") or "",
        "agencyName": data.get("agency_name") or "",
        "budgetAmount": data.get("budget_amount"),
        "status": data.get("status") or "待核对",
        "documentCount": data.get("document_count") or 0,
        "chunkCount": data.get("chunk_count") or 0,
        "createdAt": data.get("created_at") or "",
        "updatedAt": data.get("updated_at") or "",
    }


def _project_table_order_by(table_name: str) -> str:
    if table_name == "document_sections":
        return "order by section_index asc"
    if table_name == "document_chunks":
        return "order by chunk_index asc"
    if table_name in {"qualification_requirements", "rejection_items"}:
        return "order by sequence_no asc, created_at asc"
    if table_name == "scoring_items":
        return "order by score_type asc, created_at asc"
    if table_name == "source_documents":
        return "order by created_at desc"
    if table_name == "extraction_runs":
        return "order by started_at desc"
    return "order by created_at desc"


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def dumps_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def _insert_sections_as_chunks(
    conn: sqlite3.Connection,
    project_id: str,
    document_id: str,
    sections: list[Any],
    now: str,
) -> list[str]:
    chunk_ids = []
    chunk_index = 0
    for index, section in enumerate(sections or [], start=1):
        markdown = _section_value(section, "markdown") or _section_value(section, "content")
        title = _section_value(section, "title") or f"章节{index}"
        if not str(markdown).strip():
            continue
        section_id = f"sec_{uuid4().hex}"
        section_type = _guess_module(title, markdown)
        conn.execute(
            """
            insert into document_sections
                (id, document_id, project_id, section_index, parent_section_id, title, level, page_start, page_end,
                 markdown, plain_text, section_type, metadata_json, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                section_id,
                document_id,
                project_id,
                index,
                _section_value(section, "parent_section_id"),
                title,
                _to_int(_section_value(section, "level")),
                _to_int(_section_value(section, "page_start")),
                _to_int(_section_value(section, "page_end")),
                str(markdown),
                _plain_text_from_markdown(str(markdown)),
                section_type,
                dumps_json(_section_metadata(section)),
                now,
            ),
        )
        section_metadata = _section_metadata(section)
        hierarchy_base = _section_hierarchy_path(section_metadata, title)
        for chunk in _semantic_chunks_from_markdown(
            markdown=str(markdown),
            section_title=hierarchy_base,
            module=section_type,
        ):
            if (chunk.get("metadata") or {}).get("vector_role") == "section_summary":
                chunk["metadata"]["summary_of"] = section_id
                chunk["metadata"]["summary_scope"] = "section"
            chunk_index += 1
            chunk_id = f"chk_{uuid4().hex}"
            chunk_ids.append(chunk_id)
            metadata_json = dumps_json(
                _chunk_metadata(
                    chunk=chunk,
                    section_title=title,
                    section_id=section_id,
                    section_metadata=section_metadata,
                    module=section_type,
                )
            )
            conn.execute(
                """
                insert into document_chunks
                    (id, project_id, document_id, section_id, chunk_index, chunk_type, module, title_path, content,
                     content_markdown, page_start, page_end, source_text, tags_json, metadata_json, confirmed_status, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk_id,
                    project_id,
                    document_id,
                    section_id,
                    chunk_index,
                    chunk["chunk_type"],
                    section_type,
                    chunk["title_path"],
                    chunk["content"],
                    chunk.get("content_markdown", ""),
                    _to_int(_section_value(section, "page_start")),
                    _to_int(_section_value(section, "page_end")),
                    chunk["source_text"][:2000],
                    dumps_json(chunk.get("tags", [])),
                    metadata_json,
                    "未确认",
                    now,
                ),
            )
            _upsert_document_chunk_fts(
                conn,
                {
                    "id": chunk_id,
                    "project_id": project_id,
                    "document_id": document_id,
                    "section_id": section_id,
                    "chunk_type": chunk["chunk_type"],
                    "module": section_type,
                    "title_path": chunk["title_path"],
                    "content": chunk["content"],
                    "content_markdown": chunk.get("content_markdown", ""),
                    "source_text": chunk["source_text"][:2000],
                    "metadata_json": metadata_json,
                },
            )
    return chunk_ids


def _insert_image_analysis_chunks(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    document_id: str,
    items: Any,
    now: str,
) -> list[str]:
    if not isinstance(items, list):
        return []
    current = conn.execute(
        "select coalesce(max(chunk_index), 0) as max_index from document_chunks where project_id = ?",
        (project_id,),
    ).fetchone()
    chunk_index = int(current["max_index"] or 0)
    chunk_ids: list[str] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        image_id = str(item.get("image_id") or f"img_{index:04d}")
        ocr_text = str(item.get("ocr_text") or "").strip()
        ai_note = str(item.get("ai_note") or "").strip()
        file_name = str(item.get("file_name") or item.get("source") or image_id)
        content = "\n".join(
            part
            for part in [
                f"图片ID：{image_id}",
                f"文件：{file_name}",
                f"OCR：{ocr_text}" if ocr_text else "",
                f"AI描述：{ai_note}" if ai_note else "",
            ]
            if part
        ).strip()
        if not content:
            continue
        chunk_index += 1
        chunk_id = f"chk_{uuid4().hex}"
        chunk_ids.append(chunk_id)
        thumbnail_data_url = str(item.get("thumbnail_data_url") or "")
        image_data_url = str(item.get("image_data_url") or "")
        metadata = {
            "source_format": "image_analysis",
            "item_type": "图片文字",
            "image_id": image_id,
            "image_ref": str(item.get("image_ref") or item.get("source") or ""),
            "file_name": file_name,
            "source": str(item.get("source") or ""),
            "thumbnail_data_url": thumbnail_data_url,
            "has_image_payload": bool(thumbnail_data_url or image_data_url),
            "has_multimodal_embedding": bool(item.get("has_multimodal_embedding")),
            "ocr_text": ocr_text,
            "ai_note": ai_note,
            "importance_score": 1.15,
            "vector_role": "image_evidence",
        }
        if image_data_url and len(image_data_url) <= 2_000_000:
            metadata["image_data_url"] = image_data_url
        elif image_data_url:
            metadata["image_data_url_omitted"] = True
            metadata["image_data_url_size"] = len(image_data_url)
        metadata_json = dumps_json(
            _chunk_metadata(
                chunk={
                    "chunk_type": "图片文字",
                    "title_path": f"图片解析 > 图片 {index}",
                    "metadata": metadata,
                },
                section_title="图片解析",
                section_id="",
                section_metadata={},
                module="图片解析",
            )
        )
        conn.execute(
            """
            insert into document_chunks
                (id, project_id, document_id, section_id, chunk_index, chunk_type, module, title_path, content,
                 content_markdown, page_start, page_end, source_text, tags_json, metadata_json, confirmed_status, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk_id,
                project_id,
                document_id,
                None,
                chunk_index,
                "图片文字",
                "图片解析",
                f"图片解析 > 图片 {index}",
                content,
                f"![图片 {index}]({thumbnail_data_url})\n\n{content}" if thumbnail_data_url else content,
                None,
                None,
                content[:2000],
                dumps_json(["图片解析", "图片文字", image_id]),
                metadata_json,
                "未确认",
                now,
            ),
        )
        _upsert_document_chunk_fts(
            conn,
            {
                "id": chunk_id,
                "project_id": project_id,
                "document_id": document_id,
                "section_id": "",
                "chunk_type": "图片文字",
                "module": "图片解析",
                "title_path": f"图片解析 > 图片 {index}",
                "content": content,
                "content_markdown": f"![图片 {index}]({thumbnail_data_url})\n\n{content}" if thumbnail_data_url else content,
                "source_text": content[:2000],
                "metadata_json": metadata_json,
            },
        )
    return chunk_ids


def _insert_project_profile(
    conn: sqlite3.Connection,
    project_id: str,
    markdown: str,
    values: dict[str, str],
    now: str,
) -> None:
    conn.execute(
        """
        insert into project_profile
            (id, project_id, project_name, project_code, project_category, service_period, package_no, budget_text,
             budget_amount, buyer_name, agency_name, industry_domain, timeline_summary, implementation_scope,
             technical_features, other_key_requirements, is_sme_reserved, is_blind_bid, source_text, confidence,
             confirmed_status, created_at, updated_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"profile_{uuid4().hex}",
            project_id,
            values.get("项目名称", ""),
            values.get("项目编号", ""),
            values.get("项目类别（服务类，货物类，工程类）和服务年限", ""),
            values.get("项目类别（服务类，货物类，工程类）和服务年限", ""),
            values.get("包号", ""),
            values.get("项目规模和预算", ""),
            _extract_budget_amount(values),
            values.get("招标人", ""),
            values.get("招标代理机构", ""),
            values.get("项目所属领域", ""),
            values.get("各种时间安排", "") or values.get("项目时间安排", ""),
            values.get("项目要实施的具体内容", ""),
            values.get("主要技术特点", ""),
            values.get("其他关键要求", ""),
            _to_bool_int(values.get("是否专门面向中小微企业采购", "")),
            _to_bool_int(values.get("是否为暗标", "")),
            markdown,
            0.7,
            "未确认",
            now,
            now,
        ),
    )


def _insert_business_requirements_structured(
    conn: sqlite3.Connection,
    project_id: str,
    data: dict[str, Any],
    now: str,
    *,
    tech_refs: list[dict[str, Any]] | None = None,
    scoring_refs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    inserted: list[dict[str, Any]] = []
    for index, row in enumerate(_structured_rows(data, "business_requirements"), start=1):
        row_id = f"biz_{uuid4().hex}"
        requirement = str(row.get("requirement_text") or "")
        normalized = _normalization_metadata(" ".join(str(row.get(key) or "") for key in ("amount", "ratio", "deadline_text", "requirement_text", "source_text")))
        metadata = {
            "source_format": "json_schema",
            **row,
            **normalized,
            "related_tech_requirement_ids": _related_record_ids(row, tech_refs or []),
            "related_scoring_item_ids": _related_record_ids(row, scoring_refs or []),
        }
        conn.execute(
            """
            insert into business_requirements
                (id, project_id, requirement_type, item_name, requirement_text, amount, ratio, deadline_text,
                 is_mandatory, source_heading, item_sequence, source_text, metadata_json, confirmed_status, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row_id,
                project_id,
                row.get("requirement_type") or "其他",
                row.get("item_name") or "",
                requirement,
                normalized.get("amount_value") or _extract_amount(requirement),
                row.get("ratio") or _extract_ratio(requirement),
                row.get("deadline_text") or _extract_deadline(requirement),
                1 if row.get("is_mandatory") else 0,
                row.get("source_heading") or "",
                str(index),
                row.get("source_text") or row.get("evidence_snippet") or requirement,
                dumps_json(metadata),
                "未确认",
                now,
            ),
        )
        inserted.append({"id": row_id, "text": requirement, "source_chunk_id": row.get("source_chunk_id"), "metadata": metadata})
    return inserted


def _insert_technical_requirements_structured(conn: sqlite3.Connection, project_id: str, data: dict[str, Any], now: str) -> list[dict[str, Any]]:
    inserted: list[dict[str, Any]] = []
    for index, row in enumerate(_structured_rows(data, "technical_requirements"), start=1):
        row_id = f"tech_{uuid4().hex}"
        requirement = str(row.get("requirement_text") or "")
        metadata = {"source_format": "json_schema", **row, **_normalization_metadata(" ".join(str(row.get(key) or "") for key in ("parameter_value", "acceptance_criteria", "requirement_text", "source_text")))}
        conn.execute(
            """
            insert into technical_requirements
                (id, project_id, requirement_group, item_name, parameter_name, parameter_value, requirement_text,
                 acceptance_criteria, is_mandatory, importance_level, source_heading, item_sequence, source_text,
                 metadata_json, confirmed_status, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row_id,
                project_id,
                row.get("requirement_group") or "",
                row.get("item_name") or f"技术条目{index}",
                row.get("parameter_name") or row.get("item_name") or "",
                row.get("parameter_value") or "",
                requirement,
                row.get("acceptance_criteria") or "",
                1 if row.get("is_mandatory") else 0,
                row.get("importance_level") or "未明确",
                row.get("source_heading") or "",
                str(index),
                row.get("source_text") or row.get("evidence_snippet") or requirement,
                dumps_json(metadata),
                "未确认",
                now,
            ),
        )
        inserted.append({"id": row_id, "text": requirement, "source_chunk_id": row.get("source_chunk_id"), "metadata": metadata})
    return inserted


def _insert_qualification_and_rejection_structured(conn: sqlite3.Connection, project_id: str, data: dict[str, Any], now: str) -> None:
    for index, row in enumerate(_structured_rows(data, "qualification_requirements"), start=1):
        conn.execute(
            """
            insert into qualification_requirements
                (id, project_id, review_type, sequence_no, requirement_text, required_materials, is_mandatory,
                 risk_level, source_heading, item_sequence, source_text, metadata_json, confirmed_status, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"qual_{uuid4().hex}",
                project_id,
                row.get("review_type") or "资格性",
                row.get("sequence_no") or str(index),
                row.get("requirement_text") or "",
                row.get("required_materials") or "",
                1 if row.get("is_mandatory") else 0,
                row.get("risk_level") or "未明确",
                row.get("source_heading") or "",
                str(index),
                row.get("source_text") or row.get("evidence_snippet") or row.get("requirement_text") or "",
                dumps_json({"source_format": "json_schema", **row, **_normalization_metadata(" ".join(str(row.get(key) or "") for key in ("requirement_text", "required_materials", "source_text")))}),
                "未确认",
                now,
            ),
        )
    for index, row in enumerate(_structured_rows(data, "rejection_items"), start=1):
        conn.execute(
            """
            insert into rejection_items
                (id, project_id, sequence_no, rejection_item, specific_behavior, risk_level, related_module,
                 source_heading, item_sequence, source_text, metadata_json, confirmed_status, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"rej_{uuid4().hex}",
                project_id,
                row.get("sequence_no") or str(index),
                row.get("rejection_item") or "",
                row.get("specific_behavior") or "",
                row.get("risk_level") or "未明确",
                row.get("legal_nature") or row.get("related_module") or "其他",
                row.get("source_heading") or "",
                str(index),
                row.get("source_text") or row.get("evidence_snippet") or row.get("specific_behavior") or "",
                dumps_json({"source_format": "json_schema", **row, **_normalization_metadata(" ".join(str(row.get(key) or "") for key in ("rejection_item", "specific_behavior", "source_text")))}),
                "未确认",
                now,
            ),
        )


def _insert_scoring_items_structured(conn: sqlite3.Connection, project_id: str, data: dict[str, Any], now: str) -> list[dict[str, Any]]:
    inserted: list[dict[str, Any]] = []
    for index, row in enumerate(_structured_rows(data, "scoring_items"), start=1):
        row_id = f"score_{uuid4().hex}"
        score_text = str(row.get("score_text") or row.get("max_score") or "")
        metadata = {"source_format": "json_schema", **row, **_normalization_metadata(" ".join(str(row.get(key) or "") for key in ("standard", "score_text", "source_text")))}
        conn.execute(
            """
            insert into scoring_items
                (id, project_id, score_type, item_name, scoring_standard, score_value, score_text,
                 source_heading, item_sequence, source_text, metadata_json, confirmed_status, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row_id,
                project_id,
                row.get("type") or "其他",
                row.get("item") or "",
                row.get("standard") or "",
                row.get("max_score") if isinstance(row.get("max_score"), (int, float)) else _extract_amount(score_text),
                score_text,
                row.get("source_heading") or "",
                str(index),
                row.get("source_text") or row.get("evidence_snippet") or row.get("standard") or "",
                dumps_json(metadata),
                "未确认",
                now,
            ),
        )
        inserted.append({"id": row_id, "text": f"{row.get('item') or ''} {row.get('standard') or ''}", "source_chunk_id": row.get("source_chunk_id"), "metadata": metadata})
    return inserted


def _structured_rows(data: Any, key: str) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    rows = data.get(key)
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _normalization_metadata(text: str) -> dict[str, Any]:
    money = _normalize_money(text)
    time_value = _normalize_time(text)
    output: dict[str, Any] = {}
    if money:
        output.update(money)
    if time_value:
        output.update(time_value)
    return output


def _normalize_money(text: str) -> dict[str, Any]:
    amount_cny = _extract_money_amount(str(text or ""), prefer_budget_context=False)
    if amount_cny is None:
        return {}
    return {
        "amount_value": amount_cny,
        "amount_cny": amount_cny,
        "amount_currency": "CNY",
        "amount_normalized": _format_plain_number(amount_cny),
    }


def _format_plain_number(value: float) -> str:
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return text or "0"


def _normalize_time(text: str) -> dict[str, Any]:
    value = str(text or "")
    date_match = re.search(r"(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})", value)
    if date_match:
        year, month, day = (int(part) for part in date_match.groups())
        return {"date_iso": f"{year:04d}-{month:02d}-{day:02d}"}
    duration_match = re.search(r"([0-9]+)\s*(日历天|工作日|天|日|个月|月|年)", value)
    if not duration_match:
        return {}
    number = int(duration_match.group(1))
    unit = duration_match.group(2)
    if unit in {"个月", "月"}:
        days = number * 30
    elif unit == "年":
        days = number * 365
    else:
        days = number
    return {
        "duration_days": days,
        "duration_normalized": f"{days} calendar_days",
        "duration_source_unit": unit,
    }


def _related_record_ids(row: dict[str, Any], refs: list[dict[str, Any]], limit: int = 5) -> list[str]:
    row_text = " ".join(str(row.get(key) or "") for key in ("item_name", "requirement_text", "source_text", "evidence_snippet"))
    row_source = str(row.get("source_chunk_id") or "")
    ranked: list[tuple[float, str]] = []
    for ref in refs:
        score = _relation_score(row_text, str(ref.get("text") or ""))
        if row_source and row_source == str(ref.get("source_chunk_id") or ""):
            score += 5.0
        if score >= 2.0:
            ranked.append((score, str(ref["id"])))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [record_id for _, record_id in ranked[:limit]]


def _relation_score(left: str, right: str) -> float:
    left_terms = _relation_terms(left)
    right_terms = _relation_terms(right)
    if not left_terms or not right_terms:
        return 0.0
    overlap = left_terms & right_terms
    score = float(len(overlap))
    important = {"方案", "技术", "服务", "实施", "交付", "验收", "付款", "保证金", "售后", "文档", "材料"}
    score += len(overlap & important) * 1.5
    return score


def _relation_terms(text: str) -> set[str]:
    value = re.sub(r"\s+", "", str(text or ""))
    terms = set(re.findall(r"[\u4e00-\u9fff]{2,6}", value))
    keywords = {"方案", "技术", "服务", "实施", "交付", "验收", "付款", "保证金", "售后", "文档", "材料"}
    return {term for term in terms if term in keywords or len(term) >= 3}


def _insert_business_requirements(conn: sqlite3.Connection, project_id: str, markdown: str, now: str) -> None:
    rows = _markdown_tables(markdown)
    seen: set[str] = set()
    if not rows:
        for item in _structured_markdown_items(markdown, "商务内容"):
            requirement = item["text"]
            if is_duplicate_text(requirement, seen):
                continue
            conn.execute(
                """
                insert into business_requirements
                    (id, project_id, requirement_type, item_name, requirement_text, amount, ratio, deadline_text,
                     is_mandatory, source_heading, item_sequence, source_text, metadata_json, confirmed_status, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"biz_{uuid4().hex}",
                    project_id,
                    _business_type(item["section"], item["item_name"]),
                    item["item_name"],
                    requirement,
                    _extract_amount(requirement),
                    _extract_ratio(requirement),
                    _extract_deadline(requirement),
                    _mandatory(requirement),
                    item["section"],
                    item["sequence"],
                    item["source_text"],
                    dumps_json(item["metadata"]),
                    "未确认",
                    now,
                ),
            )
        return
    for row in rows:
        cells = row["cells"]
        if len(cells) < 2:
            continue
        item_name, requirement = cells[0], " | ".join(cells[1:])
        if not requirement.strip():
            continue
        if is_duplicate_text(f"{item_name} {requirement}", seen):
            continue
        conn.execute(
            """
            insert into business_requirements
                (id, project_id, requirement_type, item_name, requirement_text, amount, ratio, deadline_text,
                 is_mandatory, source_heading, item_sequence, source_text, metadata_json, confirmed_status, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"biz_{uuid4().hex}",
                project_id,
                _business_type(row["section"], item_name),
                item_name,
                requirement,
                _extract_amount(requirement),
                _extract_ratio(requirement),
                _extract_deadline(requirement),
                _mandatory(requirement),
                row["section"],
                cells[0] if cells else "",
                requirement,
                dumps_json(_table_row_metadata(row)),
                "未确认",
                now,
            ),
        )


def _insert_technical_requirements(conn: sqlite3.Connection, project_id: str, markdown: str, now: str) -> None:
    rows = _markdown_tables(markdown)
    seen: set[str] = set()
    if rows:
        for row in rows:
            cells = row["cells"]
            if not cells:
                continue
            if is_duplicate_text(" | ".join(cells), seen):
                continue
            conn.execute(
                """
                insert into technical_requirements
                    (id, project_id, requirement_group, item_name, parameter_name, parameter_value, requirement_text,
                     acceptance_criteria, is_mandatory, importance_level, source_heading, item_sequence, source_text,
                     metadata_json, confirmed_status, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"tech_{uuid4().hex}",
                    project_id,
                    row["section"],
                    cells[0],
                    cells[0],
                    cells[1] if len(cells) > 1 else "",
                    " | ".join(cells),
                    "",
                    _mandatory(" | ".join(cells)),
                    "高" if _mandatory(" | ".join(cells)) else "中",
                    row["section"],
                    cells[0] if cells else "",
                    " | ".join(cells),
                    dumps_json(_table_row_metadata(row)),
                    "未确认",
                    now,
                ),
            )
        return
    for index, item in enumerate(_structured_markdown_items(markdown, "技术要求"), start=1):
        requirement = item["text"]
        if is_duplicate_text(requirement, seen):
            continue
        conn.execute(
            """
            insert into technical_requirements
                (id, project_id, requirement_group, item_name, parameter_name, requirement_text, is_mandatory,
                 importance_level, source_heading, item_sequence, source_text, metadata_json, confirmed_status, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"tech_{uuid4().hex}",
                project_id,
                item["section"],
                item["item_name"] or f"技术条目{index}",
                item["item_name"] or f"技术条目{index}",
                requirement,
                _mandatory(requirement),
                "高" if _mandatory(requirement) else "中",
                item["section"],
                item["sequence"],
                item["source_text"],
                dumps_json(item["metadata"]),
                "未确认",
                now,
            ),
        )


def _insert_qualification_and_rejection(conn: sqlite3.Connection, project_id: str, markdown: str, now: str) -> None:
    seen_qualification: set[str] = set()
    seen_rejection: set[str] = set()
    for row in _markdown_tables(markdown):
        cells = row["cells"]
        section = row["section"]
        if not cells:
            continue
        if "废标" in section or "无效" in section or "否决" in section:
            if is_duplicate_text(" | ".join(cells), seen_rejection):
                continue
            conn.execute(
                """
                insert into rejection_items
                    (id, project_id, sequence_no, rejection_item, specific_behavior, risk_level, related_module,
                     source_heading, item_sequence, source_text, metadata_json, confirmed_status, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"rej_{uuid4().hex}",
                    project_id,
                    cells[0] if cells else "",
                    cells[1] if len(cells) > 1 else cells[0],
                    cells[2] if len(cells) > 2 else " | ".join(cells[1:]),
                    "高",
                    "资格",
                    section,
                    cells[0] if cells else "",
                    " | ".join(cells),
                    dumps_json(_table_row_metadata(row)),
                    "未确认",
                    now,
                ),
            )
        else:
            if is_duplicate_text(" | ".join(cells), seen_qualification):
                continue
            conn.execute(
                """
                insert into qualification_requirements
                    (id, project_id, review_type, sequence_no, requirement_text, required_materials, is_mandatory,
                     risk_level, source_heading, item_sequence, source_text, metadata_json, confirmed_status, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"qual_{uuid4().hex}",
                    project_id,
                    "符合性审查" if "符合" in section else "资格性审查",
                    cells[0] if cells else "",
                    cells[1] if len(cells) > 1 else cells[0],
                    cells[2] if len(cells) > 2 else "",
                    1,
                    "高",
                    section,
                    cells[0] if cells else "",
                    " | ".join(cells),
                    dumps_json(_table_row_metadata(row)),
                    "未确认",
                    now,
                ),
            )


def _insert_scoring_items(conn: sqlite3.Connection, project_id: str, markdown: str, now: str) -> None:
    seen: set[str] = set()
    for row in _markdown_tables(markdown):
        cells = row["cells"]
        if len(cells) < 2:
            continue
        if is_duplicate_text(" | ".join(cells), seen):
            continue
        score_text = cells[2] if len(cells) > 2 else ""
        conn.execute(
            """
            insert into scoring_items
                (id, project_id, score_type, item_name, scoring_standard, score_value, score_text,
                 source_heading, item_sequence, source_text, metadata_json, confirmed_status, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"score_{uuid4().hex}",
                project_id,
                "技术评分" if "技术" in row["section"] else "商务评分",
                cells[0],
                cells[1],
                _extract_amount(score_text),
                score_text,
                row["section"],
                cells[0],
                " | ".join(cells),
                    dumps_json(_table_row_metadata(row)),
                "未确认",
                now,
            ),
        )


def _insert_review_findings(conn: sqlite3.Connection, project_id: str, markdown: str, now: str) -> None:
    if not str(markdown or "").strip() or "尚未执行" in str(markdown):
        return
    for index, paragraph in enumerate(_paragraphs(markdown)[:30], start=1):
        if not any(keyword in paragraph for keyword in ("风险", "缺失", "失败", "需核对", "废标", "未命中")):
            continue
        conn.execute(
            """
            insert into review_findings
                (id, project_id, review_type, module, risk_level, finding_title, finding_detail, source_text, suggestion, status, created_by, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"rf_{uuid4().hex}",
                project_id,
                "内容完整性",
                "内容审查",
                "高" if "废标" in paragraph or "失败" in paragraph else "中",
                f"审查发现{index}",
                paragraph,
                paragraph,
                "请人工核对原文和提取结果。",
                "待处理",
                "系统",
                now,
            ),
        )


def _parse_project_profile(markdown: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in str(markdown or "").splitlines():
        clean = line.strip().strip("|").strip()
        if not clean or "---" in clean:
            continue
        parts = [part.strip() for part in clean.split("|") if part.strip()]
        if len(parts) >= 2:
            key, value = parts[0], parts[1]
        else:
            match = re.match(r"^[#*\-\d.、\s]*([^：:]{2,60})[：:]\s*(.+)$", clean)
            if not match:
                continue
            key, value = match.group(1).strip(), match.group(2).strip()
        values[key] = value
    return values


def _markdown_tables(markdown: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    section = "未分组"
    lines = str(markdown or "").splitlines()
    table_lines: list[str] = []
    for line in lines + [""]:
        stripped = line.strip()
        heading = re.match(r"^#{1,6}\s*(.+)$", stripped)
        if heading:
            if table_lines:
                rows.extend(_parse_table_lines(table_lines, section))
                table_lines = []
            section = heading.group(1).strip()
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            table_lines.append(stripped)
            continue
        if table_lines:
            rows.extend(_parse_table_lines(table_lines, section))
            table_lines = []
    return rows


def _parse_table_lines(lines: list[str], section: str) -> list[dict[str, Any]]:
    separator_index = next(
        (
            index
            for index, line in enumerate(lines)
            if re.match(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$", line)
        ),
        -1,
    )
    if separator_index <= 0:
        return []
    header_rows = _expand_merged_like_table_rows(
        [_table_cells(line) for line in lines[:separator_index]],
        fill_from_previous_row=False,
    )
    data_lines = lines[separator_index + 1 :]
    if not header_rows or not data_lines:
        return []
    header_paths = _table_header_paths(header_rows)
    output = []
    previous_cells: list[str] = []
    for line in data_lines:
        if not line.strip().startswith("|") or not line.strip().endswith("|"):
            continue
        cells = _expand_merged_like_table_row(_table_cells(line), previous_cells)
        previous_cells = cells
        if any(cells) and not all(cell in {"", "未提及", "未明确"} for cell in cells):
            output.append(
                {
                    "section": section,
                    "cells": cells,
                    "headers": header_paths[: len(cells)],
                    "cell_header_map": {
                        header_paths[index] if index < len(header_paths) else f"列{index + 1}": cell
                        for index, cell in enumerate(cells)
                    },
                }
            )
    return output


def _table_row_metadata(row: dict[str, Any]) -> dict[str, Any]:
    cells = [str(cell).strip() for cell in row.get("cells", [])]
    header_paths = [str(header).strip() for header in row.get("headers", [])]
    if not header_paths:
        header_paths = [f"列{index + 1}" for index in range(len(cells))]
    cell_header_map = row.get("cell_header_map")
    if not isinstance(cell_header_map, dict) or not cell_header_map:
        cell_header_map = {
            header_paths[index] if index < len(header_paths) else f"列{index + 1}": cell
            for index, cell in enumerate(cells)
        }
    return {
        "source_format": "markdown_table",
        "section": row.get("section") or "未分组",
        "cells": cells,
        "header_paths": header_paths[: len(cells)],
        "cell_header_map": cell_header_map,
        "parent_table_header": " > ".join(header_paths[: len(cells)]),
    }


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in str(line).strip().split("|")[1:-1]]


def _expand_merged_like_table_rows(
    rows: list[list[str]],
    *,
    fill_from_previous_row: bool = True,
) -> list[list[str]]:
    expanded: list[list[str]] = []
    previous: list[str] = []
    for row in rows:
        normalized = _expand_merged_like_table_row(
            row,
            previous if fill_from_previous_row else [],
            fill_from_left=True,
        )
        expanded.append(normalized)
        previous = normalized
    return expanded


def _expand_merged_like_table_row(
    row: list[str],
    previous_row: list[str] | None = None,
    *,
    fill_from_left: bool = False,
) -> list[str]:
    previous = previous_row or []
    width = max(len(row), len(previous))
    output: list[str] = []
    last_value = ""
    for index in range(width):
        value = str(row[index]).strip() if index < len(row) else ""
        if value:
            last_value = value
        elif fill_from_left and last_value:
            value = last_value
        elif index < len(previous):
            value = str(previous[index]).strip()
        output.append(value)
    return output


def _table_header_paths(header_rows: list[list[str]]) -> list[str]:
    width = max((len(row) for row in header_rows), default=0)
    paths: list[str] = []
    last_seen = ["" for _ in header_rows]
    for col in range(width):
        parts = []
        for row_index, row in enumerate(header_rows):
            cell = row[col].strip() if col < len(row) else ""
            if cell:
                last_seen[row_index] = cell
            value = cell or last_seen[row_index]
            if value and value not in parts:
                parts.append(value)
        paths.append(" > ".join(parts) if parts else f"列{col + 1}")
    return paths


def _paragraphs(markdown: str) -> list[str]:
    return [
        re.sub(r"^[#*\-\d.、\s]+", "", line).strip()
        for line in str(markdown or "").splitlines()
        if line.strip() and not line.strip().startswith("|")
    ]


def _structured_markdown_items(markdown: str, default_section: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    current_section = default_section
    current_item = default_section
    current_item_seq = ""
    bullet_index = 0
    fallback_index = 0

    for raw_line in str(markdown or "").splitlines():
        line = _clean_markdown_inline(raw_line.strip())
        if not line or line.startswith("|") or re.match(r"^\|?\s*:?-{3,}:?", line):
            continue

        heading = re.match(r"^#{1,6}\s*(.+)$", raw_line.strip())
        chinese_heading = re.match(r"^([一二三四五六七八九十]+)[、.．]\s*(.+)$", line)
        numbered_title = re.match(r"^(\d+(?:\.\d+)*)[.、]\s*(.+)$", line)
        bullet = re.match(r"^[-*+]\s*(.+)$", line)

        if heading:
            current_section = _clean_markdown_inline(heading.group(1))
            current_item = current_section
            current_item_seq = ""
            bullet_index = 0
            continue
        if chinese_heading:
            current_section = chinese_heading.group(2).strip()
            current_item = current_section
            current_item_seq = chinese_heading.group(1)
            bullet_index = 0
            continue
        if numbered_title and _looks_like_item_title(numbered_title.group(2)):
            current_item_seq = numbered_title.group(1)
            current_item = numbered_title.group(2).strip()
            bullet_index = 0
            continue

        text = ""
        sequence = ""
        if bullet:
            bullet_index += 1
            text = bullet.group(1).strip()
            sequence = f"{current_item_seq}.{bullet_index}" if current_item_seq else str(bullet_index)
        elif numbered_title:
            fallback_index += 1
            sequence = numbered_title.group(1)
            text = numbered_title.group(2).strip()
        elif len(line) >= 8:
            fallback_index += 1
            sequence = f"{current_item_seq}.{fallback_index}" if current_item_seq else str(fallback_index)
            text = line

        text = _clean_markdown_inline(text)
        if not text:
            continue
        items.append(
            {
                "section": current_section or default_section,
                "item_name": current_item or default_section,
                "sequence": sequence,
                "text": text,
                "source_text": raw_line.strip(),
                "metadata": {
                    "source_format": "markdown_list",
                    "item_type": "列表项",
                    "section": current_section or default_section,
                    "parent_item": current_item or default_section,
                    "sequence": sequence,
                },
            }
        )

    return items


def _semantic_chunks_from_markdown(markdown: str, section_title: str, module: str) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    seen: set[str] = set()
    section_summary = _section_summary_text(markdown)
    if section_summary:
        chunks.append(
            {
                "chunk_type": "章节摘要",
                "title_path": section_title,
                "content": section_summary,
                "content_markdown": section_summary,
                "source_text": section_summary,
                "tags": [module, "章节摘要"],
                "metadata": {
                    "source_format": "section_summary",
                    "item_type": "章节摘要",
                    "vector_role": "section_summary",
                },
            }
        )

    for table_index, table in enumerate(_group_markdown_table_rows(_markdown_tables(markdown)), start=1):
        table_rows = table["rows"]
        if _is_large_table(table_rows):
            chunks.extend(
                _large_table_chunks(
                    table=table,
                    table_index=table_index,
                    section_title=section_title,
                    module=module,
                    seen=seen,
                )
            )
            continue
        for row_index, row in enumerate(table_rows, start=1):
            row_chunk = _table_row_chunk(
                row=row,
                row_index=row_index,
                section_title=section_title,
                module=module,
            )
            if row_chunk and not is_duplicate_text(row_chunk["content"], seen):
                chunks.append(row_chunk)

    for item in _structured_markdown_items(markdown, section_title):
        content = item["text"].strip()
        if not content or is_duplicate_text(content, seen):
            continue
        chunks.append(
            {
                "chunk_type": _semantic_chunk_type(module, content),
                "title_path": _append_path(section_title, item["section"], item["item_name"]),
                "content": content,
                "content_markdown": item["source_text"],
                "source_text": item["source_text"],
                "tags": [module, item["section"], item["item_name"]],
                "metadata": item["metadata"],
            }
        )

    if len(chunks) > (1 if section_summary else 0):
        return chunks

    for index, paragraph in enumerate(_merge_short_paragraphs(_paragraphs(markdown)), start=1):
        content = paragraph.strip()
        if not content or is_duplicate_text(content, seen):
            continue
        chunks.append(
            {
                "chunk_type": _semantic_chunk_type(module, content),
                "title_path": section_title,
                "content": content,
                "content_markdown": content,
                "source_text": content,
                "tags": [module],
                "metadata": {
                    "source_format": "paragraph",
                    "item_type": "段落",
                    "paragraph_index": index,
                },
            }
        )
    return chunks


TABLE_ROW_GROUP_SIZE = 3
LARGE_TABLE_ROW_THRESHOLD = 20


def _group_markdown_table_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in rows:
        key = (row.get("section") or "", tuple(row.get("headers") or []))
        if not current or current["key"] != key:
            current = {
                "key": key,
                "section": row.get("section") or "ungrouped",
                "headers": row.get("headers") or [],
                "rows": [],
            }
            tables.append(current)
        current["rows"].append(row)
    return tables


def _is_large_table(rows: list[dict[str, Any]]) -> bool:
    return len(rows) > LARGE_TABLE_ROW_THRESHOLD


def _table_row_chunk(
    *,
    row: dict[str, Any],
    row_index: int,
    section_title: str,
    module: str,
) -> dict[str, Any] | None:
    cells = [cell for cell in row["cells"] if str(cell).strip()]
    header_paths = row.get("headers") or []
    cell_header_map = row.get("cell_header_map") or {}
    content = _table_row_content(cells, cell_header_map)
    if not content:
        return None
    return {
        "chunk_type": "表格行",
        "title_path": _append_path(section_title, row["section"]),
        "content": content,
        "content_markdown": "| " + " | ".join(cells) + " |",
        "source_text": content,
        "tags": [module, "表格"],
        "metadata": {
            "source_format": "markdown_table",
            "item_type": "表格行",
            "table_size": "small",
            "row_index": row_index,
            "cells": cells,
            "header_paths": header_paths,
            "cell_header_map": cell_header_map,
            "table_header_path": _append_path(section_title, row["section"]),
            "parent_table_header": " > ".join(header_paths),
        },
    }


def _large_table_chunks(
    *,
    table: dict[str, Any],
    table_index: int,
    section_title: str,
    module: str,
    seen: set[str],
) -> list[dict[str, Any]]:
    rows = table["rows"]
    header_paths = [str(item).strip() for item in table.get("headers") or [] if str(item).strip()]
    title_path = _append_path(section_title, table.get("section") or "")
    overview_id = f"table_{table_index:03d}_overview"
    header_summary = " > ".join(header_paths)
    overview_content = (
        f"表格说明：{title_path}\n"
        f"字段：{header_summary or '未识别表头'}\n"
        f"行数：{len(rows)}\n"
        f"用途：该 chunk 用于说明大表结构，具体数据位于 table_row_group chunk。"
    )
    chunks: list[dict[str, Any]] = []
    if not is_duplicate_text(overview_content, seen):
        chunks.append(
            {
                "chunk_type": "表格说明",
                "title_path": title_path,
                "content": overview_content,
                "content_markdown": overview_content,
                "source_text": overview_content,
                "tags": [module, "表格", "表格说明"],
                "metadata": {
                    "source_format": "markdown_table",
                    "item_type": "table_overview",
                    "table_size": "large",
                    "table_index": table_index,
                    "table_overview_id": overview_id,
                    "row_count": len(rows),
                    "header_paths": header_paths,
                    "parent_table_header": header_summary,
                    "importance_score": 1.3,
                },
            }
        )

    for group_index, start in enumerate(range(0, len(rows), TABLE_ROW_GROUP_SIZE), start=1):
        group_rows = rows[start : start + TABLE_ROW_GROUP_SIZE]
        row_texts = []
        markdown_lines = []
        group_metadata_rows = []
        for offset, row in enumerate(group_rows, start=start + 1):
            cells = [cell for cell in row["cells"] if str(cell).strip()]
            cell_header_map = row.get("cell_header_map") or {}
            row_content = _table_row_content(cells, cell_header_map)
            if not row_content:
                continue
            row_texts.append(f"第{offset}行：{row_content}")
            markdown_lines.append("| " + " | ".join(cells) + " |")
            group_metadata_rows.append(
                {
                    "row_index": offset,
                    "cells": cells,
                    "cell_header_map": cell_header_map,
                }
            )
        content = "\n".join(row_texts).strip()
        if not content or is_duplicate_text(content, seen):
            continue
        chunks.append(
            {
                "chunk_type": "表格行组",
                "title_path": title_path,
                "content": content,
                "content_markdown": "\n".join(markdown_lines),
                "source_text": content,
                "tags": [module, "表格", "表格行组"],
                "metadata": {
                    "source_format": "markdown_table",
                    "item_type": "table_row_group",
                    "table_size": "large",
                    "table_index": table_index,
                    "group_index": group_index,
                    "row_start": start + 1,
                    "row_end": start + len(group_rows),
                    "row_count": len(group_rows),
                    "header_paths": header_paths,
                    "rows": group_metadata_rows,
                    "parent_table_overview_id": overview_id,
                    "parent_table_header": header_summary or overview_id,
                },
            }
        )
    return chunks


def _table_row_content(cells: list[str], cell_header_map: dict[str, Any]) -> str:
    if cell_header_map:
        return "；".join(
            f"{header}: {cell}"
            for header, cell in cell_header_map.items()
            if str(cell).strip()
        ).strip()
    return " | ".join(cells).strip()


def _section_summary_text(markdown: str, max_chars: int = 1200) -> str:
    paragraphs = _paragraphs(markdown)
    if not paragraphs:
        return ""
    summary = "\n".join(paragraphs[:8]).strip()
    return summary[:max_chars].rstrip()


def _chunk_metadata(
    *,
    chunk: dict[str, Any],
    section_title: str,
    section_id: str,
    section_metadata: dict[str, Any],
    module: str,
) -> dict[str, Any]:
    metadata = dict(chunk.get("metadata") or {})
    hierarchy_path = str(chunk.get("title_path") or metadata.get("hierarchy_path") or section_title)
    item_type = metadata.get("item_type") or _chunk_item_type(str(chunk.get("chunk_type") or ""))
    parent_table_header = metadata.get("parent_table_header") or metadata.get("table_header_path") or ""
    if isinstance(metadata.get("header_paths"), list) and metadata.get("header_paths"):
        parent_table_header = parent_table_header or " > ".join(str(item) for item in metadata["header_paths"])
    metadata.update(
        {
            "hierarchy_path": hierarchy_path,
            "item_type": item_type,
            "parent_table_header": parent_table_header,
            "importance_score": float(metadata.get("importance_score") or 1.0),
            "module": module,
            "section_title": section_title,
            "section_id": section_id,
            "section_metadata": section_metadata,
            "vector_filter": {
                "module": module,
                "item_type": item_type,
                "hierarchy_path": hierarchy_path,
            },
        }
    )
    return metadata


def _chunk_item_type(chunk_type: str) -> str:
    if "表格" in chunk_type:
        return "表格行"
    if "摘要" in chunk_type:
        return "章节摘要"
    if "图片" in chunk_type or "OCR" in chunk_type:
        return "图片文字"
    if "页脚" in chunk_type or "页眉" in chunk_type:
        return "页脚说明"
    if chunk_type and chunk_type != "段落":
        return "列表项"
    return "段落"


def _section_hierarchy_path(metadata: dict[str, Any], fallback_title: str) -> str:
    title_path = metadata.get("title_path")
    if isinstance(title_path, list):
        values = [str(item).strip() for item in title_path if str(item).strip()]
        if values:
            return " > ".join(values)
    if isinstance(title_path, str) and title_path.strip():
        return title_path.strip()
    return fallback_title


def _append_path(*parts: Any) -> str:
    output: list[str] = []
    for part in parts:
        for value in str(part or "").split(">"):
            clean = value.strip()
            if clean and (not output or output[-1] != clean):
                output.append(clean)
    return " > ".join(output)


def _semantic_chunk_type(module: str, content: str) -> str:
    text = f"{module} {content}"
    if "技术" in module:
        return "技术要求"
    if "商务" in module:
        return "商务条款"
    if "评分" in module:
        return "评分项"
    if "资格" in module:
        return "资格条款"
    if re.search(r"资格|符合性|营业执照|资质|证书", text):
        return "资格条款"
    if re.search(r"废标|无效|否决|重大偏差", text):
        return "废标项"
    if re.search(r"评分|评审|分值|得分", text):
        return "评分项"
    if re.search(r"商务|合同|付款|交付|验收|保证金|售后", text):
        return "商务条款"
    if re.search(r"技术|参数|系统|功能|性能|实施|服务", text):
        return "技术要求"
    return "段落"


def _merge_short_paragraphs(paragraphs: list[str], target_chars: int = 900) -> list[str]:
    merged: list[str] = []
    buffer: list[str] = []
    length = 0
    for paragraph in paragraphs:
        text = paragraph.strip()
        if not text:
            continue
        if buffer and length + len(text) > target_chars:
            merged.append("\n".join(buffer))
            buffer = []
            length = 0
        buffer.append(text)
        length += len(text)
    if buffer:
        merged.append("\n".join(buffer))
    return merged


def _clean_markdown_inline(value: str) -> str:
    value = str(value or "").strip()
    value = re.sub(r"^\s*>+\s*", "", value)
    value = re.sub(r"\*\*(.*?)\*\*", r"\1", value)
    value = re.sub(r"`([^`]*)`", r"\1", value)
    return re.sub(r"\s+", " ", value).strip()


def _looks_like_item_title(text: str) -> bool:
    text = _clean_markdown_inline(text)
    if not text:
        return False
    if len(text) <= 40 and not re.search(r"[。；;，,]$", text):
        return True
    return False


def _section_value(section: Any, key: str) -> str:
    if isinstance(section, dict):
        return str(section.get(key) or "")
    return str(getattr(section, key, "") or "")


def _section_metadata(section: Any) -> dict[str, Any]:
    if isinstance(section, dict):
        metadata = section.get("metadata") or {}
    else:
        metadata = getattr(section, "metadata", {}) or {}
    return metadata if isinstance(metadata, dict) else {}


def _to_int(value: Any) -> int | None:
    try:
        text = str(value or "").strip()
        return int(text) if text else None
    except (TypeError, ValueError):
        return None


def _plain_text_from_markdown(markdown: str) -> str:
    lines = []
    for line in str(markdown or "").splitlines():
        clean = line.strip()
        if not clean or re.match(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$", clean):
            continue
        clean = clean.replace("|", " ")
        clean = re.sub(r"^[#*\-\d.、\s]+", "", clean).strip()
        clean = re.sub(r"\s+", " ", clean)
        if clean:
            lines.append(clean)
    return "\n".join(lines)


def _guess_module(title: str, content: str) -> str:
    text = f"{title}\n{content}"
    if re.search(r"资格|符合|废标|无效|否决", text):
        return "资格审查"
    if re.search(r"评分|评审|分值|得分", text):
        return "评分要求"
    if re.search(r"商务|合同|付款|交付|保证金", text):
        return "商务内容"
    if re.search(r"技术|参数|服务方案|实施方案", text):
        return "技术要求"
    return "投标人须知"


def _business_type(section: str, item_name: str) -> str:
    text = f"{section} {item_name}"
    for keyword in ("报价", "合同", "付款", "交付", "验收", "保证金", "售后", "联合体", "分包"):
        if keyword in text:
            return keyword
    return "其他"


def _extract_amount(text: str) -> float | None:
    return _extract_money_amount(str(text or ""), prefer_budget_context=False)


def _extract_budget_amount(values: dict[str, str] | str, package_hint: str = "") -> float | None:
    if isinstance(values, dict):
        preferred_keys = [
            "项目规模和预算",
            "预算金额",
            "项目预算",
            "采购预算",
            "最高限价",
            "最高投标限价",
            "控制价",
            "拦标价",
            "限价",
        ]
        preferred_text = " ".join(
            str(value)
            for key, value in values.items()
            if any(keyword in str(key) for keyword in preferred_keys) and value
        )
        all_text = " ".join(str(value) for value in values.values() if value)
        text = f"{preferred_text} {all_text}".strip()
        package_hint = package_hint or _profile_package_hint(values)
    else:
        text = str(values or "")
    return _extract_money_amount(text, prefer_budget_context=True, package_hint=package_hint)


def _extract_money_amount(text: str, *, prefer_budget_context: bool = False, package_hint: str = "") -> float | None:
    value = str(text or "")
    if not value.strip():
        return None
    candidates = _money_candidates(value)
    if not candidates:
        return None
    package_patterns = _package_hint_patterns(package_hint)
    if package_patterns:
        package_contextual = [
            item
            for item in candidates
            if any(re.search(pattern, value[max(0, item["start"] - 32) : item["start"]]) for pattern in package_patterns)
        ]
        if package_contextual:
            candidates = package_contextual
    if prefer_budget_context:
        context_keywords = ("预算", "最高限价", "采购金额", "项目金额", "控制价", "拦标价", "限价", "总价", "合同估算价")
        contextual = [
            item
            for item in candidates
            if any(keyword in value[max(0, item["start"] - 24) : item["end"] + 24] for keyword in context_keywords)
        ]
        if contextual:
            candidates = contextual
    return max(float(item["amount"]) for item in candidates)


def _profile_package_hint(values: dict[str, str]) -> str:
    for key, value in values.items():
        if "包号" in str(key) and value:
            return str(value)
    combined = " ".join(str(value) for value in values.values() if value)
    match = re.search(r"(?:包|第)\s*([A-Za-z0-9一二三四五六七八九十]+)\s*(?:包)?", combined)
    return match.group(1) if match else ""


def _package_hint_patterns(package_hint: str) -> list[str]:
    value = str(package_hint or "").strip()
    if not value:
        return []
    match = re.search(r"([A-Za-z0-9一二三四五六七八九十]+)", value)
    if not match:
        return []
    token = re.escape(match.group(1))
    return [
        rf"包\s*{token}",
        rf"第\s*{token}\s*包",
        rf"{token}\s*包",
    ]


def _money_candidates(text: str) -> list[dict[str, Any]]:
    normalized = str(text or "").replace(",", "").replace("，", "")
    pattern = re.compile(
        r"(?<![\d.])(?:人民币|RMB|CNY|￥)?\s*([0-9]+(?:\.[0-9]+)?)\s*(亿元|亿|万元|万|元|CNY|RMB)?",
        re.IGNORECASE,
    )
    output: list[dict[str, Any]] = []
    for match in pattern.finditer(normalized):
        number_text = match.group(1)
        unit = match.group(2) or ""
        amount = float(number_text)
        if unit in {"亿元", "亿"}:
            amount *= 100000000
        elif unit in {"万元", "万"}:
            amount *= 10000
        elif unit.lower() in {"cny", "rmb"}:
            amount = float(number_text)
        if not unit and amount < 1000:
            nearby = normalized[max(0, match.start() - 8) : match.end() + 8]
            if not re.search(r"预算|金额|限价|报价|人民币|RMB|CNY|￥", nearby, re.IGNORECASE):
                continue
        output.append({"amount": amount, "start": match.start(), "end": match.end(), "unit": unit})
    chinese_pattern = re.compile(r"(?:人民币)?\s*([零〇一二两三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟]+)\s*(亿元|亿|万元|万|元)")
    for match in chinese_pattern.finditer(normalized):
        if match.group(1) in {"万", "亿"}:
            continue
        amount = _chinese_number_to_float(match.group(1))
        if amount is None:
            continue
        unit = match.group(2)
        if unit in {"亿元", "亿"}:
            amount *= 100000000
        elif unit in {"万元", "万"}:
            amount *= 10000
        output.append({"amount": amount, "start": match.start(), "end": match.end(), "unit": unit})
    return output


def _chinese_number_to_float(text: str) -> float | None:
    digits = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "壹": 1,
        "贰": 2,
        "叁": 3,
        "肆": 4,
        "伍": 5,
        "陆": 6,
        "柒": 7,
        "捌": 8,
        "玖": 9,
    }
    units = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
    section_units = {"万": 10000, "亿": 100000000}
    total = 0
    section = 0
    number = 0
    seen = False
    for char in str(text or ""):
        if char in digits:
            number = digits[char]
            seen = True
        elif char in units:
            seen = True
            section += (number or 1) * units[char]
            number = 0
        elif char in section_units:
            seen = True
            section = (section + number) or 1
            total += section * section_units[char]
            section = 0
            number = 0
        else:
            return None
    if not seen:
        return None
    return float(total + section + number)


def _extract_ratio(text: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", str(text or ""))
    return float(match.group(1)) / 100 if match else None


def _extract_deadline(text: str) -> str:
    match = re.search(r"[^，。；;\n]*(?:日内|天内|工作日|截止|期限|服务期|交付)[^，。；;\n]*", str(text or ""))
    return match.group(0).strip() if match else ""


def _mandatory(text: str) -> int | None:
    if re.search(r"必须|不得|应当|应|须|★|实质性|无效|废标", str(text or "")):
        return 1
    return None


def _to_bool_int(text: str) -> int | None:
    value = str(text or "")
    if re.search(r"是|专门|面向|true", value, re.IGNORECASE):
        return 1
    if re.search(r"否|不是|非|false", value, re.IGNORECASE):
        return 0
    return None
