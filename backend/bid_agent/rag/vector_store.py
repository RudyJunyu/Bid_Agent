# -*- coding: utf-8 -*-
"""Optional Chroma vector index for persisted document chunks."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from bid_agent.core.settings import CHROMA_DIR
from openai import OpenAI

from bid_agent.infrastructure.database import DB_PATH, init_database


os.environ.setdefault("HF_ENDPOINT", os.getenv("HF_ENDPOINT") or "https://hf-mirror.com")

_LOCAL_EMBEDDING_MODEL = None
_LOCAL_RERANKER_MODEL = None


def vector_store_enabled() -> bool:
    return os.getenv("BID_VECTOR_STORE_ENABLED", "false").lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def index_project_chunks(project_id: str, db_path: Path = DB_PATH) -> dict[str, Any]:
    """Index all chunks of a project into Chroma and record mappings in SQLite."""
    if not vector_store_enabled():
        return {"enabled": False, "indexed": 0, "reason": "disabled"}
    try:
        import chromadb
    except Exception as exc:
        return {"enabled": False, "indexed": 0, "reason": f"chromadb not installed: {exc}"}

    chunks = _load_project_chunks(project_id, db_path)
    if not chunks:
        return {"enabled": True, "indexed": 0, "reason": "no chunks"}

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = client.get_or_create_collection(
        name=os.getenv("CHROMA_COLLECTION", "bid_document_chunks"),
        metadata={"hnsw:space": "cosine"},
    )
    batch_size = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))
    embedding_model = _embedding_model()
    indexed = 0
    vector_ids: list[tuple[str, str, int]] = []
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        documents = [_chunk_document(chunk) for chunk in batch]
        try:
            embeddings = embed_texts(documents)
        except Exception as exc:
            return {
                "enabled": False,
                "indexed": indexed,
                "reason": f"embedding unavailable: {exc}",
                "fallback": "sqlite_keyword_search",
            }
        ids = [_vector_id(chunk) for chunk in batch]
        metadatas = [_chroma_metadata(chunk) for chunk in batch]
        collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )
        indexed += len(batch)
        dim = len(embeddings[0]) if embeddings else 0
        vector_ids.extend((chunk["id"], vector_id, dim) for chunk, vector_id in zip(batch, ids))

    _record_chunk_embeddings(
        vector_ids=vector_ids,
        embedding_model=embedding_model,
        vector_store="chroma",
        db_path=db_path,
    )
    return {
        "enabled": True,
        "indexed": indexed,
        "project_id": project_id,
        "collection": os.getenv("CHROMA_COLLECTION", "bid_document_chunks"),
        "persist_dir": str(CHROMA_DIR),
        "embedding_provider": _embedding_provider(),
        "embedding_model": embedding_model,
        "reranker_model": _reranker_model() if reranker_enabled() else "",
    }


def search_project_chunks(
    query: str,
    *,
    project_id: str | None = None,
    module: str | None = None,
    item_type: str | None = None,
    top_k: int = 8,
) -> dict[str, Any]:
    """Hybrid search over SQLite lexical matches and Chroma vector matches."""
    lexical_results = _search_project_chunks_sqlite_candidates(
        query,
        project_id=project_id,
        module=module,
        item_type=item_type,
        top_k=_initial_retrieval_count(top_k),
    )
    vector_results: list[dict[str, Any]] = []
    vector_reason = ""
    if not vector_store_enabled():
        vector_reason = "vector store disabled"
        return _hybrid_search_response(
            query=query,
            project_id=project_id,
            module=module,
            item_type=item_type,
            top_k=top_k,
            lexical_results=lexical_results,
            vector_results=[],
            vector_reason=vector_reason,
        )
    try:
        import chromadb
    except Exception as exc:
        return _hybrid_search_response(
            query,
            project_id=project_id,
            module=module,
            item_type=item_type,
            top_k=top_k,
            lexical_results=lexical_results,
            vector_results=[],
            vector_reason=f"chromadb not installed: {exc}",
        )

    try:
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        collection = client.get_or_create_collection(
            name=os.getenv("CHROMA_COLLECTION", "bid_document_chunks"),
            metadata={"hnsw:space": "cosine"},
        )
        where = _build_where(project_id=project_id, module=module, item_type=item_type)
        initial_top_k = _initial_retrieval_count(top_k)
        result = collection.query(
            query_embeddings=embed_texts([query]),
            n_results=initial_top_k,
            where=where or None,
            include=["documents", "metadatas", "distances"],
        )
        vector_results = _format_query_results(result)
        vector_results = rerank_results(query, vector_results, top_k=_initial_retrieval_count(top_k))
    except Exception as exc:
        vector_reason = f"chroma or embedding unavailable: {exc}"

    return _hybrid_search_response(
        query=query,
        project_id=project_id,
        module=module,
        item_type=item_type,
        top_k=top_k,
        lexical_results=lexical_results,
        vector_results=vector_results,
        vector_reason=vector_reason,
    )


def delete_project_vectors(project_id: str) -> dict[str, Any]:
    if not vector_store_enabled():
        return {"enabled": False, "deleted": False, "reason": "disabled"}
    try:
        import chromadb
    except Exception as exc:
        return {"enabled": False, "deleted": False, "reason": f"chromadb not installed: {exc}"}
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = client.get_or_create_collection(
        name=os.getenv("CHROMA_COLLECTION", "bid_document_chunks"),
        metadata={"hnsw:space": "cosine"},
    )
    collection.delete(where={"project_id": project_id})
    return {"enabled": True, "deleted": True, "project_id": project_id}


def embed_texts(texts: list[str]) -> list[list[float]]:
    if _embedding_provider() == "sentence_transformers":
        return _embed_texts_local(texts)
    model = _embedding_model()
    client = OpenAI(
        api_key=os.getenv("EMBEDDING_API_KEY") or os.getenv("LLM_API_KEY"),
        base_url=os.getenv("EMBEDDING_BASE_URL") or os.getenv("LLM_BASE_URL"),
        timeout=int(os.getenv("EMBEDDING_TIMEOUT", os.getenv("LLM_TIMEOUT", "120"))),
    )
    response = client.embeddings.create(model=model, input=texts)
    return [item.embedding for item in response.data]


def _embedding_model() -> str:
    model = (
        os.getenv("EMBEDDING_MODEL_ID")
        or os.getenv("LLM_EMBEDDING_MODEL_ID")
        or "BAAI/bge-large-zh-v1.5"
    )
    if not model:
        raise ValueError("请配置 EMBEDDING_MODEL_ID 后再启用 Chroma 向量索引。")
    return model


def _embedding_provider() -> str:
    return os.getenv("EMBEDDING_PROVIDER", "sentence_transformers").strip().lower()


def _embed_texts_local(texts: list[str]) -> list[list[float]]:
    global _LOCAL_EMBEDDING_MODEL
    if _LOCAL_EMBEDDING_MODEL is None:
        from sentence_transformers import SentenceTransformer

        device = os.getenv("EMBEDDING_DEVICE") or None
        _LOCAL_EMBEDDING_MODEL = SentenceTransformer(_embedding_model(), device=device)
    embeddings = _LOCAL_EMBEDDING_MODEL.encode(
        texts,
        batch_size=int(os.getenv("EMBEDDING_BATCH_SIZE", "32")),
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return embeddings.tolist()


def reranker_enabled() -> bool:
    return os.getenv("RERANKER_ENABLED", "false").lower() not in {"0", "false", "no", "off"}


def _reranker_model() -> str:
    return os.getenv("RERANKER_MODEL_ID") or "BAAI/bge-reranker-v2-m3"


def _initial_retrieval_count(top_k: int) -> int:
    multiplier = int(os.getenv("RERANKER_TOP_K_MULTIPLIER", "4"))
    return max(1, top_k * max(1, multiplier)) if reranker_enabled() else max(1, top_k)


def rerank_results(query: str, results: list[dict[str, Any]], *, top_k: int) -> list[dict[str, Any]]:
    if not reranker_enabled() or not results:
        return results[:top_k]
    try:
        scores = _rerank_scores(query, [str(item.get("document") or "") for item in results])
    except Exception:
        return results[:top_k]
    ranked = []
    for item, score in zip(results, scores):
        enriched = dict(item)
        enriched["rerank_score"] = float(score)
        ranked.append(enriched)
    ranked.sort(key=lambda item: item.get("rerank_score", 0.0), reverse=True)
    for index, item in enumerate(ranked[:top_k], start=1):
        item["rank"] = index
    return ranked[:top_k]


def _rerank_scores(query: str, documents: list[str]) -> list[float]:
    global _LOCAL_RERANKER_MODEL
    if _LOCAL_RERANKER_MODEL is None:
        from sentence_transformers import CrossEncoder

        device = os.getenv("RERANKER_DEVICE") or None
        _LOCAL_RERANKER_MODEL = CrossEncoder(_reranker_model(), device=device)
    pairs = [[query, document] for document in documents]
    scores = _LOCAL_RERANKER_MODEL.predict(
        pairs,
        batch_size=int(os.getenv("RERANKER_BATCH_SIZE", "16")),
        show_progress_bar=False,
    )
    return [float(score) for score in scores]


def _load_project_chunks(project_id: str, db_path: Path) -> list[dict[str, Any]]:
    init_database(db_path)
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            select *
            from document_chunks
            where project_id = ?
            order by chunk_index asc
            """,
            (project_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _load_chunks_for_search(
    *,
    project_id: str | None,
    db_path: Path,
) -> list[dict[str, Any]]:
    init_database(db_path)
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if project_id:
            rows = conn.execute(
                """
                select *
                from document_chunks
                where project_id = ?
                order by chunk_index asc
                """,
                (project_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                select *
                from document_chunks
                order by created_at desc, chunk_index asc
                limit 2000
                """
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _search_project_chunks_sqlite_fallback(
    query: str,
    *,
    project_id: str | None,
    module: str | None,
    item_type: str | None,
    top_k: int,
    reason: str,
) -> dict[str, Any]:
    results = _search_project_chunks_fts(
        query,
        project_id=project_id,
        module=module,
        item_type=item_type,
        top_k=top_k,
    )
    if not results:
        results = _search_project_chunks_count_candidates(
            query,
            project_id=project_id,
            module=module,
            item_type=item_type,
            top_k=top_k,
        )
    for item in results:
        item["rerank_score"] = item.get("lexical_score", item.get("rerank_score", 0.0))
    for index, item in enumerate(results, start=1):
        item["rank"] = index
    return {
        "enabled": True,
        "query": query,
        "filters": {"project_id": project_id, "module": module, "item_type": item_type},
        "search_type": "sqlite_fallback",
        "reason": reason,
        "embedding_model": "",
        "reranker_model": "",
        "results": results,
    }


def _search_project_chunks_sqlite_candidates(
    query: str,
    *,
    project_id: str | None,
    module: str | None,
    item_type: str | None,
    top_k: int,
) -> list[dict[str, Any]]:
    fts_results = _search_project_chunks_fts(
        query,
        project_id=project_id,
        module=module,
        item_type=item_type,
        top_k=top_k,
    )
    if fts_results:
        return fts_results
    return _search_project_chunks_count_candidates(
        query,
        project_id=project_id,
        module=module,
        item_type=item_type,
        top_k=top_k,
    )


def _search_project_chunks_fts(
    query: str,
    *,
    project_id: str | None,
    module: str | None,
    item_type: str | None,
    top_k: int,
) -> list[dict[str, Any]]:
    match_query = _fts_match_query(query)
    if not match_query:
        return []
    init_database(DB_PATH)
    import sqlite3

    where = ["document_chunks_fts match ?"]
    params: list[Any] = [match_query]
    if project_id:
        where.append("document_chunks_fts.project_id = ?")
        params.append(project_id)
    if module:
        where.append("document_chunks_fts.module = ?")
        params.append(module)
    if item_type:
        where.append("document_chunks_fts.item_type = ?")
        params.append(item_type)
    params.append(max(1, top_k))

    sql = f"""
        select c.*, bm25(document_chunks_fts) as bm25_score
        from document_chunks_fts
        join document_chunks c on c.id = document_chunks_fts.chunk_id
        where {' and '.join(where)}
        order by bm25_score asc
        limit ?
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()

    output: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        chunk = dict(row)
        metadata = _chroma_metadata(chunk)
        document = _chunk_document(chunk)
        rank_score = 1.0 / index
        rank_score *= float(metadata.get("importance_score") or 1.0)
        output.append(
            {
                "rank": 0,
                "vector_id": "",
                "chunk_id": metadata.get("chunk_id"),
                "distance": None,
                "lexical_score": rank_score,
                "bm25_score": float(chunk.get("bm25_score") or 0.0),
                "document": document,
                "metadata": metadata,
                "source": "sqlite_fts5",
            }
        )
    return output


def _fts_match_query(query: str) -> str:
    terms = _query_terms(query)
    if not terms:
        return ""
    return " OR ".join(f'"{_escape_fts_term(term)}"' for term in terms if _escape_fts_term(term))


def _escape_fts_term(term: str) -> str:
    return str(term or "").replace('"', '""').strip()


def _search_project_chunks_count_candidates(
    query: str,
    *,
    project_id: str | None,
    module: str | None,
    item_type: str | None,
    top_k: int,
) -> list[dict[str, Any]]:
    chunks = _load_chunks_for_search(project_id=project_id, db_path=DB_PATH)
    terms = _query_terms(query)
    scored: list[dict[str, Any]] = []
    for chunk in chunks:
        metadata = _chroma_metadata(chunk)
        if module and metadata.get("module") != module:
            continue
        if item_type and metadata.get("item_type") != item_type:
            continue
        document = _chunk_document(chunk)
        score = _lexical_score(query=query, terms=terms, document=document, metadata=metadata)
        if score <= 0:
            continue
        scored.append(
            {
                "rank": 0,
                "vector_id": "",
                "chunk_id": metadata.get("chunk_id"),
                "distance": None,
                "lexical_score": score,
                "document": document,
                "metadata": metadata,
                "source": "sqlite",
            }
        )
    scored.sort(key=lambda item: item.get("lexical_score", 0.0), reverse=True)
    return scored[: max(1, top_k)]


def _hybrid_search_response(
    query: str,
    *,
    project_id: str | None,
    module: str | None,
    item_type: str | None,
    top_k: int,
    lexical_results: list[dict[str, Any]],
    vector_results: list[dict[str, Any]],
    vector_reason: str = "",
) -> dict[str, Any]:
    results = _merge_hybrid_results(
        lexical_results=lexical_results,
        vector_results=vector_results,
        top_k=top_k,
    )
    search_type = "hybrid" if vector_results else "hybrid_lexical_only"
    return {
        "enabled": True,
        "query": query,
        "filters": {"project_id": project_id, "module": module, "item_type": item_type},
        "search_type": search_type,
        "reason": vector_reason,
        "embedding_model": _embedding_model() if vector_results else "",
        "reranker_model": _reranker_model() if vector_results and reranker_enabled() else "",
        "results": results,
    }


def _merge_hybrid_results(
    *,
    lexical_results: list[dict[str, Any]],
    vector_results: list[dict[str, Any]],
    top_k: int,
) -> list[dict[str, Any]]:
    routed_section_ids = _routed_section_ids([*lexical_results, *vector_results])
    lexical_max = max([float(item.get("lexical_score") or 0.0) for item in lexical_results] or [1.0])
    vector_scores = [_vector_relevance_score(item) for item in vector_results]
    vector_max = max(vector_scores or [1.0])
    merged: dict[str, dict[str, Any]] = {}

    for item in lexical_results:
        key = str(item.get("chunk_id") or item.get("vector_id") or item.get("document") or "")
        enriched = dict(item)
        enriched["hybrid_score"] = 0.45 * (float(item.get("lexical_score") or 0.0) / lexical_max)
        enriched["match_sources"] = ["关键词"]
        merged[key] = enriched

    for item, vector_score in zip(vector_results, vector_scores):
        key = str(item.get("chunk_id") or item.get("vector_id") or item.get("document") or "")
        normalized = vector_score / vector_max if vector_max else 0.0
        if key in merged:
            merged[key]["hybrid_score"] = float(merged[key].get("hybrid_score") or 0.0) + 0.55 * normalized
            merged[key]["vector_id"] = item.get("vector_id") or merged[key].get("vector_id")
            merged[key]["distance"] = item.get("distance")
            merged[key]["rerank_score"] = item.get("rerank_score")
            merged[key]["match_sources"] = ["关键词", "向量"]
        else:
            enriched = dict(item)
            enriched["hybrid_score"] = 0.55 * normalized
            enriched["match_sources"] = ["向量"]
            merged[key] = enriched

    ranked = sorted(
        (_apply_summary_route_boost(item, routed_section_ids) for item in merged.values()),
        key=lambda item: float(item.get("hybrid_score") or 0.0),
        reverse=True,
    )
    filtered = [
        item
        for item in ranked
        if str((item.get("metadata") or {}).get("vector_role") or "") != "section_summary"
    ]
    if not filtered:
        filtered = ranked
    ranked = filtered[: max(1, top_k)]
    for index, item in enumerate(ranked, start=1):
        item["rank"] = index
    return ranked


def _routed_section_ids(results: list[dict[str, Any]]) -> set[str]:
    section_ids: set[str] = set()
    for item in results:
        metadata = item.get("metadata") or {}
        if str(metadata.get("vector_role") or "") != "section_summary":
            continue
        summary_of = str(metadata.get("summary_of") or metadata.get("section_id") or "").strip()
        if summary_of:
            section_ids.add(summary_of)
    return section_ids


def _apply_summary_route_boost(item: dict[str, Any], routed_section_ids: set[str]) -> dict[str, Any]:
    if not routed_section_ids:
        return item
    metadata = item.get("metadata") or {}
    if str(metadata.get("vector_role") or "") == "section_summary":
        item["summary_route_only"] = True
        return item
    section_id = str(metadata.get("section_id") or "").strip()
    if section_id and section_id in routed_section_ids:
        item["hybrid_score"] = float(item.get("hybrid_score") or 0.0) + 0.18
        sources = list(item.get("match_sources") or [])
        if "章节摘要路由" not in sources:
            sources.append("章节摘要路由")
        item["match_sources"] = sources
        item["routed_by_summary"] = True
    return item


def _vector_relevance_score(item: dict[str, Any]) -> float:
    if item.get("rerank_score") is not None:
        return max(float(item.get("rerank_score") or 0.0), 0.0)
    if item.get("distance") is not None:
        return 1.0 / (1.0 + max(float(item.get("distance") or 0.0), 0.0))
    return 0.0


def _query_terms(query: str) -> list[str]:
    import re

    text = str(query or "").lower()
    terms = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9_]{2,}", text)
    if not terms and text.strip():
        terms = [text.strip()]
    return list(dict.fromkeys(terms))


def _lexical_score(
    *,
    query: str,
    terms: list[str],
    document: str,
    metadata: dict[str, Any],
) -> float:
    searchable = "\n".join(
        [
            document,
            str(metadata.get("hierarchy_path") or ""),
            str(metadata.get("parent_table_header") or ""),
            str(metadata.get("module") or ""),
            str(metadata.get("item_type") or ""),
        ]
    ).lower()
    score = 0.0
    for term in terms:
        count = searchable.count(term.lower())
        if count:
            score += min(count, 8) * (2.0 if len(term) >= 4 else 1.0)
    if str(query or "").lower() in searchable:
        score += 6.0
    score *= float(metadata.get("importance_score") or 1.0)
    return score


def _record_chunk_embeddings(
    *,
    vector_ids: list[tuple[str, str, int]],
    embedding_model: str,
    vector_store: str,
    db_path: Path,
) -> None:
    import sqlite3

    now = datetime.now().replace(microsecond=0).isoformat()
    conn = sqlite3.connect(db_path)
    try:
        for chunk_id, vector_id, dim in vector_ids:
            conn.execute("delete from chunk_embeddings where chunk_id = ? and vector_store = ?", (chunk_id, vector_store))
            conn.execute(
                """
                insert into chunk_embeddings
                    (id, chunk_id, embedding_model, embedding_dim, vector_store, vector_id, indexed_at)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (f"emb_{uuid4().hex}", chunk_id, embedding_model, dim, vector_store, vector_id, now),
            )
        conn.commit()
    finally:
        conn.close()


def _chunk_document(chunk: dict[str, Any]) -> str:
    title_path = chunk.get("title_path") or ""
    content = chunk.get("content_markdown") or chunk.get("content") or ""
    metadata = _json_loads(chunk.get("metadata_json"))
    header = metadata.get("parent_table_header") or ""
    return "\n".join(part for part in [str(title_path), str(header), str(content)] if part).strip()


def _vector_id(chunk: dict[str, Any]) -> str:
    return f"chunk::{chunk.get('id')}"


def _chroma_metadata(chunk: dict[str, Any]) -> dict[str, Any]:
    metadata = _json_loads(chunk.get("metadata_json"))
    return {
        "chunk_id": str(chunk.get("id") or ""),
        "project_id": str(chunk.get("project_id") or ""),
        "document_id": str(chunk.get("document_id") or ""),
        "section_id": str(chunk.get("section_id") or ""),
        "module": str(chunk.get("module") or metadata.get("module") or ""),
        "item_type": str(metadata.get("item_type") or chunk.get("chunk_type") or ""),
        "chunk_type": str(chunk.get("chunk_type") or ""),
        "hierarchy_path": str(metadata.get("hierarchy_path") or chunk.get("title_path") or ""),
        "title_path": str(chunk.get("title_path") or ""),
        "parent_table_header": str(metadata.get("parent_table_header") or ""),
        "importance_score": float(metadata.get("importance_score") or 1.0),
        "vector_role": str(metadata.get("vector_role") or ""),
        "summary_of": str(metadata.get("summary_of") or ""),
        "summary_scope": str(metadata.get("summary_scope") or ""),
        "page_start": int(chunk.get("page_start") or 0),
        "page_end": int(chunk.get("page_end") or 0),
    }


def _build_where(
    *,
    project_id: str | None,
    module: str | None,
    item_type: str | None,
) -> dict[str, Any]:
    clauses = []
    if project_id:
        clauses.append({"project_id": project_id})
    if module:
        clauses.append({"module": module})
    if item_type:
        clauses.append({"item_type": item_type})
    if not clauses:
        return {}
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _format_query_results(result: dict[str, Any]) -> list[dict[str, Any]]:
    ids = (result.get("ids") or [[]])[0]
    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    output = []
    for index, vector_id in enumerate(ids):
        metadata = metadatas[index] if index < len(metadatas) else {}
        output.append(
            {
                "rank": index + 1,
                "vector_id": vector_id,
                "chunk_id": metadata.get("chunk_id"),
                "distance": distances[index] if index < len(distances) else None,
                "document": documents[index] if index < len(documents) else "",
                "metadata": metadata,
            }
        )
    return output


def _json_loads(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}
