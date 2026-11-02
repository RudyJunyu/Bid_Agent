"""SQLite repository extracted from legacy persistence; HTTP-independent."""
from pathlib import Path
from typing import Any
from bid_agent.core.settings import DB_PATH
from bid_agent.infrastructure.database import (
    init_database, _connect, _project_row_to_dict, _project_table_order_by,
    _row_to_dict, quote_identifier, PROJECT_DETAIL_TABLES, CONFIRMABLE_TABLES,
    PROJECT_SCOPED_TABLES, DELETABLE_PROJECT_RECORD_TABLES,
)


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
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone():
            if conn.execute("SELECT 1 FROM jobs WHERE project_id=? AND status NOT IN ('succeeded','failed','cancelled')", (project_id,)).fetchone():
                from bid_agent.repositories.platform import ConflictError
                raise ConflictError('请先取消或等待项目内的解析任务完成，再删除项目')
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
