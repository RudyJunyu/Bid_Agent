"""Rebuild vector indexes from authoritative SQLite chunks; opt-in full image required."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def main():
    from bid_agent.infrastructure.database import list_projects
    from bid_agent.rag.vector_store import index_project_chunks, vector_store_enabled
    parser = argparse.ArgumentParser()
    parser.add_argument('--project-id')
    args = parser.parse_args()
    if not vector_store_enabled():
        raise SystemExit('Set BID_VECTOR_STORE_ENABLED=true and use the full image first.')
    project_ids = [args.project_id] if args.project_id else [p['id'] for p in list_projects()]
    failed = False
    for project_id in project_ids:
        result = index_project_chunks(project_id)
        print(json.dumps({'project_id': project_id, **result}, ensure_ascii=False))
        failed = failed or not result.get('enabled', False)
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
