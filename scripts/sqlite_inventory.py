#!/usr/bin/env python3
"""B08 prep: export SQLite table inventory for PostgreSQL migration planning."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--db-path',
        type=Path,
        default=Path(os.environ.get('BID_DB_PATH') or ROOT / 'storage' / 'data' / 'bid_agent.db'),
    )
    parser.add_argument('--output', type=Path, default=None)
    args = parser.parse_args()
    db_path = args.db_path.resolve()
    if not db_path.is_file():
        print(json.dumps({'ok': False, 'error': f'db not found: {db_path}'}, ensure_ascii=False))
        return 1
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    tables = [
        row['name']
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    inventory = {'db_path': str(db_path), 'tables': []}
    for table in tables:
        columns = [dict(row) for row in conn.execute(f'PRAGMA table_info({table})')]
        count = conn.execute(f'SELECT COUNT(*) AS c FROM {table}').fetchone()['c']
        inventory['tables'].append({
            'name': table,
            'row_count': count,
            'columns': [
                {
                    'cid': col['cid'],
                    'name': col['name'],
                    'type': col['type'],
                    'notnull': bool(col['notnull']),
                    'pk': bool(col['pk']),
                }
                for col in columns
            ],
        })
    conn.close()
    inventory['table_count'] = len(tables)
    inventory['notes'] = (
        'Read-only inventory for B08. Do not treat this as a completed PostgreSQL migration; '
        'use docs/implementation/b08-postgres.md for the target sequence.'
    )
    text = json.dumps(inventory, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
        print(str(args.output.resolve()))
    else:
        print(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
