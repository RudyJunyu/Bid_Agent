"""MinerU integration status: read/mask/test; runtime override without writing .env."""
from __future__ import annotations

import os
from typing import Any

import requests

_runtime_overrides: dict[str, str] = {}


def _token() -> str:
    return (_runtime_overrides.get('token') or os.getenv('MINERU_API_TOKEN') or '').strip()


def _timeout() -> int:
    raw = _runtime_overrides.get('timeout') or os.getenv('MINERU_REQUEST_TIMEOUT') or '120'
    try:
        return int(raw)
    except ValueError:
        return 120


def get_public_config() -> dict[str, Any]:
    token = _token()
    masked = ''
    if token:
        masked = token[:4] + '…' + token[-4:] if len(token) > 8 else '****'
    return {
        'configured': bool(token),
        'token_masked': masked,
        'timeout': _timeout(),
        'base_url': 'https://mineru.net/api/v4',
        'runtime_override': bool(_runtime_overrides),
        'note': '密钥请写在部署环境的 .env；PUT 仅写入进程内覆盖，重启后丢失，不会改仓库文件。',
    }


def set_runtime_override(*, token: str | None = None, timeout: int | None = None) -> dict[str, Any]:
    if token is not None:
        cleaned = token.strip()
        if cleaned:
            _runtime_overrides['token'] = cleaned
        else:
            _runtime_overrides.pop('token', None)
    if timeout is not None:
        _runtime_overrides['timeout'] = str(int(timeout))
    return get_public_config()


def clear_runtime_override() -> dict[str, Any]:
    _runtime_overrides.clear()
    return get_public_config()


def test_connection() -> dict[str, Any]:
    token = _token()
    if not token:
        return {'ok': False, 'detail': '未配置 MINERU_API_TOKEN'}
    try:
        response = requests.get(
            'https://mineru.net/api/v4/extract/task/healthcheck',
            headers={'Authorization': f'Bearer {token}'},
            timeout=min(30, _timeout()),
        )
        return {
            'ok': response.status_code < 500,
            'status_code': response.status_code,
            'detail': (response.text or '')[:300],
        }
    except requests.RequestException as exc:
        return {'ok': False, 'detail': str(exc)}
