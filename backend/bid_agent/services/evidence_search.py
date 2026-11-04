"""Project-scoped keyword evidence search with index versioning (B10 draft)."""
from __future__ import annotations

import re
from typing import Any

from bid_agent.core.identity import Principal
from bid_agent.repositories import assets, bids, indexes, requirements as requirement_repo, workspace
from bid_agent.repositories.workspace import check_access
from bid_agent.repositories.platform import transaction


def rebuild_index(project_id: str, user: Principal, *, notes: str = '') -> dict:
    corpus = _build_corpus(project_id, user)
    version = indexes.create_version(
        project_id,
        user,
        kind='keyword',
        corpus_stats={
            'document_count': corpus['document_count'],
            'requirement_count': corpus['requirement_count'],
            'section_count': corpus['section_count'],
            'asset_count': corpus['asset_count'],
            'chunk_count': len(corpus['chunks']),
        },
        notes=notes or '工作台重建关键词索引',
        status='ready',
    )
    return {'index_version': version, 'chunk_count': len(corpus['chunks'])}


def search(
    project_id: str,
    user: Principal,
    *,
    query: str,
    limit: int = 10,
) -> dict:
    query = (query or '').strip()
    if not query:
        raise ValueError('检索词不能为空')
    limit = max(1, min(int(limit), 50))
    # Permission boundary: must have project access.
    with transaction() as conn:
        check_access(conn, project_id, user)
    corpus = _build_corpus(project_id, user)
    index = indexes.latest_ready(project_id, user) or rebuild_index(project_id, user)['index_version']
    tokens = _tokens(query)
    scored: list[dict[str, Any]] = []
    for chunk in corpus['chunks']:
        score = _score(tokens, chunk['text'], chunk.get('title') or '')
        if score <= 0:
            continue
        scored.append({
            **chunk,
            'score': round(score, 4),
            'project_id': project_id,
        })
    scored.sort(key=lambda item: (-item['score'], item.get('title') or ''))
    hits = scored[:limit]
    return {
        'project_id': project_id,
        'query': query,
        'index_version_id': index['id'],
        'total_candidates': len(scored),
        'hits': hits,
    }


def evaluate_recall(
    project_id: str,
    user: Principal,
    *,
    cases: list[dict],
    k: int = 10,
) -> dict:
    """Evaluate Recall@K against a list of {query, relevant_ids} cases."""
    if not cases:
        raise ValueError('评测集为空')
    results = []
    hit_count = 0
    for case in cases:
        query = case.get('query') or ''
        relevant = {str(item) for item in (case.get('relevant_ids') or [])}
        payload = search(project_id, user, query=query, limit=k)
        retrieved_ids = [str(item.get('id')) for item in payload['hits']]
        found = bool(relevant & set(retrieved_ids))
        hit_count += 1 if found else 0
        results.append({
            'query': query,
            'relevant_ids': sorted(relevant),
            'retrieved_ids': retrieved_ids,
            'hit_at_k': found,
        })
    total = len(cases)
    return {
        'project_id': project_id,
        'k': k,
        'case_count': total,
        'hits': hit_count,
        'recall_at_k': round(hit_count / total, 4) if total else 0.0,
        'cases': results,
    }


def _build_corpus(project_id: str, user: Principal) -> dict:
    documents = workspace.list_documents(project_id, user)
    chunks: list[dict] = []
    requirement_count = 0
    section_count = 0
    for document in documents:
        for version in document.get('versions') or []:
            version_id = version['id']
            extractor = requirement_repo.latest_extractor_version(version_id, user)
            items = requirement_repo.list_for_version(
                version_id, user, extractor_version=extractor,
            ) if extractor else []
            requirement_count += len(items)
            for item in items:
                text = ' '.join(
                    str(part or '')
                    for part in (
                        item.get('title'),
                        item.get('normalized_value'),
                        item.get('raw_text'),
                    )
                )
                quotes = [
                    str(ref.get('quote') or '')
                    for ref in (item.get('source_refs') or [])
                    if ref.get('quote')
                ]
                body = text + '\n' + '\n'.join(quotes)
                chunks.append({
                    'id': f"req:{item['id']}",
                    'source_type': 'requirement',
                    'source_id': item['id'],
                    'title': item.get('title') or item.get('field_key') or '要求',
                    'text': body,
                    'document_version_id': version_id,
                })

    bid_versions = bids.list_bid_versions(project_id, user)
    for summary in bid_versions[:5]:
        detail = bids.get_bid_version(summary['id'], user)
        for section in detail.get('sections') or []:
            section_count += 1
            body = str(section.get('body_markdown') or '')
            title = section.get('title') or '章节'
            chunks.append({
                'id': f"sec:{section['id']}",
                'source_type': 'bid_section',
                'source_id': section['id'],
                'title': title,
                'text': f'{title}\n{body}',
                'bid_version_id': summary['id'],
            })

    linked_assets = assets.list_for_project(project_id, user, usable_only=False)
    for asset in linked_assets:
        chunks.append({
            'id': f"asset:{asset['id']}",
            'source_type': 'enterprise_asset',
            'source_id': asset['id'],
            'title': asset.get('title') or '资产',
            'text': ' '.join(
                str(part or '')
                for part in (
                    asset.get('title'),
                    asset.get('subject_name'),
                    asset.get('certificate_no'),
                    asset.get('issuer'),
                    ' '.join(asset.get('tags') or []),
                )
            ),
            'usable': bool(asset.get('usable')),
        })

    return {
        'document_count': len(documents),
        'requirement_count': requirement_count,
        'section_count': section_count,
        'asset_count': len(linked_assets),
        'chunks': chunks,
    }


def _tokens(text: str) -> list[str]:
    parts = re.findall(r'[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}', text or '')
    # Prefer longer unique tokens first.
    unique = []
    seen = set()
    for part in sorted(parts, key=len, reverse=True):
        key = part.lower()
        if key not in seen:
            seen.add(key)
            unique.append(key)
    return unique[:24]


def _score(tokens: list[str], text: str, title: str) -> float:
    blob = f'{title}\n{text}'.lower()
    if not tokens or not blob.strip():
        return 0.0
    hits = 0.0
    for token in tokens:
        if token in blob:
            hits += 1.0
            if token in (title or '').lower():
                hits += 0.5
    return hits / max(len(tokens), 1)
