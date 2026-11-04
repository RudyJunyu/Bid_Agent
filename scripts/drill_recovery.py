#!/usr/bin/env python3
"""B16 draft: verify a cold backup manifest without mutating production data.

Usage:
  python scripts/drill_recovery.py --backup-dir backups/<stamp>
  python scripts/drill_recovery.py --backup-dir backups/<stamp> --expect-db
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def file_sha256(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup-dir', type=Path, required=True)
    parser.add_argument('--expect-db', action='store_true', help='Require SQLite DB file present')
    args = parser.parse_args()
    backup = args.backup_dir.resolve()
    manifest_path = backup / 'manifest.json'
    storage = backup / 'storage'
    report = {
        'backup_dir': str(backup),
        'ok': True,
        'checks': [],
        'failures': [],
    }
    if not backup.is_dir():
        report['ok'] = False
        report['failures'].append('backup_dir missing')
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1
    if not manifest_path.is_file():
        report['ok'] = False
        report['failures'].append('manifest.json missing')
    else:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        hashes = manifest.get('files_sha256') or {}
        report['checks'].append({'name': 'manifest_loaded', 'file_count': len(hashes)})
        mismatched = []
        missing = []
        for relative, expected in hashes.items():
            path = backup / relative
            if not path.is_file():
                missing.append(relative)
                continue
            actual = file_sha256(path)
            if actual != expected:
                mismatched.append(relative)
        report['checks'].append({
            'name': 'hash_verify',
            'checked': len(hashes),
            'missing': len(missing),
            'mismatched': len(mismatched),
        })
        if missing or mismatched:
            report['ok'] = False
            report['failures'].append({
                'missing_sample': missing[:10],
                'mismatched_sample': mismatched[:10],
            })
    if not storage.is_dir():
        report['ok'] = False
        report['failures'].append('storage/ missing')
    else:
        report['checks'].append({
            'name': 'storage_present',
            'files': sum(1 for _ in storage.rglob('*') if _.is_file()),
        })
    if args.expect_db:
        db_candidates = list(storage.rglob('*.db')) + list(storage.rglob('*.sqlite'))
        report['checks'].append({'name': 'db_candidates', 'count': len(db_candidates)})
        if not db_candidates:
            report['ok'] = False
            report['failures'].append('expected SQLite DB not found under storage/')
    report['notes'] = (
        'This drill only verifies backup integrity. Full cutover restore still needs a '
        'dedicated environment and compose volume restore rehearsal.'
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 2


if __name__ == '__main__':
    sys.exit(main())
