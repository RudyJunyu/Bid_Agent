#!/usr/bin/env python3
"""Score B07 requirement extract drafts against sample golden annotations.

Usage:
  python scripts/eval_requirement_recall.py \\
    --golden docs/samples/golden/01-anyang-zhengwu-yunwei.json \\
    --requirements-json /tmp/req_anyang.json

  # or fetch from a running API:
  python scripts/eval_requirement_recall.py \\
    --golden docs/samples/golden/01-anyang-zhengwu-yunwei.json \\
    --base-url http://127.0.0.1:8080 \\
    --version-id dv_...
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def fetch_requirements(base_url: str, version_id: str) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/api/v1/document-versions/{version_id}/requirements"
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.loads(response.read().decode('utf-8'))


def item_text(item: dict[str, Any]) -> str:
    parts = [
        str(item.get('field_key') or ''),
        str(item.get('title') or ''),
        str(item.get('raw_text') or ''),
        str(item.get('normalized_value') or ''),
    ]
    return '\n'.join(parts)


def has_evidence(item: dict[str, Any]) -> bool:
    refs = item.get('source_refs') or []
    return any(
        (ref.get('block_id') or ref.get('section_index') is not None or ref.get('page'))
        for ref in refs
        if isinstance(ref, dict)
    )


def match_needles(text: str, needles: list[str]) -> bool:
    return any(needle and needle in text for needle in needles)


def score_overview(items: list[dict[str, Any]], specs: list[dict[str, Any]]) -> dict[str, Any]:
    overview = [item for item in items if item.get('category') == 'overview']
    rows = []
    for spec in specs:
        field_keys = set(spec.get('field_keys') or [])
        candidates = [
            item for item in overview
            if not field_keys or item.get('field_key') in field_keys
        ] or overview
        hit_item = None
        for item in candidates:
            if match_needles(item_text(item), list(spec.get('must_contain_any') or [])):
                hit_item = item
                break
        rows.append({
            'id': spec.get('id'),
            'optional': bool(spec.get('optional')),
            'hit': hit_item is not None,
            'evidence': has_evidence(hit_item) if hit_item else False,
            'value': (hit_item or {}).get('normalized_value') or (hit_item or {}).get('raw_text'),
        })
    required = [row for row in rows if not row['optional']]
    hits = [row for row in required if row['hit']]
    evid = [row for row in hits if row['evidence']]
    return {
        'total_required': len(required),
        'hits': len(hits),
        'recall': (len(hits) / len(required)) if required else 0.0,
        'evidence_on_hits': (len(evid) / len(hits)) if hits else 0.0,
        'rows': rows,
    }


def score_clauses(
    items: list[dict[str, Any]],
    default_category: str,
    specs: list[dict[str, Any]],
) -> dict[str, Any]:
    default_pool = [item for item in items if item.get('category') == default_category]
    rows = []
    for spec in specs:
        categories = list(spec.get('categories') or [default_category])
        pool = [item for item in items if item.get('category') in categories]
        hit_item = None
        for item in pool:
            if match_needles(item_text(item), list(spec.get('must_contain_any') or [])):
                hit_item = item
                break
        rows.append({
            'id': spec.get('id'),
            'hit': hit_item is not None,
            'evidence': has_evidence(hit_item) if hit_item else False,
            'title': (hit_item or {}).get('title'),
            'category': (hit_item or {}).get('category'),
            'search_categories': categories,
        })
    hits = [row for row in rows if row['hit']]
    evid = [row for row in hits if row['evidence']]
    return {
        'total': len(rows),
        'hits': len(hits),
        'recall': (len(hits) / len(rows)) if rows else 0.0,
        'evidence_on_hits': (len(evid) / len(hits)) if hits else 0.0,
        'pool_size': len(default_pool),
        'rows': rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--golden', required=True, type=Path)
    parser.add_argument('--requirements-json', type=Path)
    parser.add_argument('--base-url', default='http://127.0.0.1:8080')
    parser.add_argument('--version-id')
    parser.add_argument('--json-out', type=Path)
    args = parser.parse_args()

    if not args.requirements_json and not args.version_id:
        parser.error('provide --requirements-json or --version-id')

    golden = load_json(args.golden)
    payload = load_json(args.requirements_json) if args.requirements_json else fetch_requirements(
        args.base_url, args.version_id,
    )
    items = payload.get('items') or []
    # Prefer a single extractor generation when dumps mix historical drafts.
    preferred = payload.get('extractor_version')
    if preferred and preferred != 'all' and any(item.get('extractor_version') for item in items):
        filtered = [item for item in items if item.get('extractor_version') == preferred]
        if filtered:
            items = filtered
    by_cat: dict[str, int] = {}
    for item in items:
        cat = str(item.get('category') or 'unknown')
        by_cat[cat] = by_cat.get(cat, 0) + 1

    report = {
        'sample': golden.get('sample'),
        'extractor_version': preferred or (items[0].get('extractor_version') if items else None),
        'item_count': len(items),
        'counts': by_cat,
        'overview': score_overview(items, list(golden.get('overview') or [])),
        'qualification': score_clauses(items, 'qualification', list(golden.get('qualification_clauses') or [])),
        'rejection': score_clauses(items, 'rejection', list(golden.get('rejection_clauses') or [])),
    }

    if args.json_out:
        args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    ov = report['overview']
    qu = report['qualification']
    rj = report['rejection']
    print(f"sample={report['sample']} items={report['item_count']} extractor={report['extractor_version']}")
    print(f"counts={by_cat}")
    print(
        f"overview required recall={ov['hits']}/{ov['total_required']} "
        f"({ov['recall']:.0%}) evidence_on_hits={ov['evidence_on_hits']:.0%}"
    )
    for row in ov['rows']:
        flag = 'HIT' if row['hit'] else 'MISS'
        opt = ' (optional)' if row['optional'] else ''
        evid = 'evid' if row['evidence'] else 'no-evid'
        value = (row.get('value') or '')[:60]
        print(f"  [{flag}]{opt} {row['id']}: {evid} | {value}")
    print(
        f"qualification recall={qu['hits']}/{qu['total']} ({qu['recall']:.0%}) "
        f"pool={qu['pool_size']} evidence_on_hits={qu['evidence_on_hits']:.0%}"
    )
    for row in qu['rows']:
        print(f"  [{'HIT' if row['hit'] else 'MISS'}] {row['id']}: {row.get('title') or ''}")
    print(
        f"rejection recall={rj['hits']}/{rj['total']} ({rj['recall']:.0%}) "
        f"pool={rj['pool_size']} evidence_on_hits={rj['evidence_on_hits']:.0%}"
    )
    for row in rj['rows']:
        print(f"  [{'HIT' if row['hit'] else 'MISS'}] {row['id']}: {row.get('title') or ''}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
