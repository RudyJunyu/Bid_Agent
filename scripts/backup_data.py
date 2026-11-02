"""Stop this Compose application, copy its data, then restore its running state."""
import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def compose(*args, capture=False):
    return subprocess.run(['docker', 'compose', *args], cwd=ROOT, check=True,
                          text=True, capture_output=capture)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'backups')
    args = parser.parse_args()
    destination = args.output_dir.resolve() / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    running = compose('ps', '--status', 'running', '--services', capture=True).stdout.splitlines()
    owned_running = [service for service in ('web', 'dispatcher', 'worker', 'api') if service in running]
    destination.mkdir(parents=True, exist_ok=False)
    (destination / 'storage').mkdir()
    try:
        if owned_running:
            compose('stop', *owned_running)
        compose('cp', 'api:/app/storage/.', str(destination / 'storage'))
        hashes = {}
        for path in sorted((destination / 'storage').rglob('*')):
            if path.is_file():
                with path.open('rb') as stream:
                    hashes[path.relative_to(destination).as_posix()] = hashlib.file_digest(stream, 'sha256').hexdigest()
        (destination / 'manifest.json').write_text(json.dumps({
            'created_at': datetime.now(timezone.utc).isoformat(),
            'files_sha256': hashes,
            'notes': 'Cold backup. Environment secrets and model cache are excluded.',
        }, ensure_ascii=False, indent=2), encoding='utf-8')
    finally:
        if owned_running:
            compose('start', *reversed(owned_running))
    print(destination)


if __name__ == '__main__':
    main()
