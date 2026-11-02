"""SQLite repository extracted from legacy persistence; HTTP-independent."""
from pathlib import Path
from typing import Any
from uuid import uuid4
from bid_agent.core.settings import DB_PATH
from bid_agent.infrastructure.database import (
    init_database, _connect, _now, _knowledge_row_to_dict, KNOWLEDGE_TYPES,
)


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
