"""Session authentication for the document workspace; local mode is explicitly single-user."""
import hashlib
import hmac
import os
import secrets
import time

from fastapi import HTTPException, Request

from bid_agent.core.settings import env_bool
from bid_agent.core.identity import Principal
from bid_agent.repositories.platform import new_id, now, transaction

COOKIE_NAME = 'bid_session'
SESSION_SECONDS = 12 * 60 * 60


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return f'scrypt${salt.hex()}${digest.hex()}'


def verify_password(password: str, encoded: str) -> bool:
    try:
        method, salt, expected = encoded.split('$')
        if method != 'scrypt':
            return False
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token(token: str) -> str:
    return hashlib.sha256(('bid-csrf:' + token).encode()).hexdigest()


def bootstrap_identity() -> None:
    with transaction() as conn:
        conn.execute('INSERT OR IGNORE INTO users VALUES(?,?,?,?,?)',
                     ('local', '__local__', 'disabled', 1, now()))
        if not env_bool('BID_AUTH_ENABLED'):
            return
        if conn.execute("SELECT 1 FROM users WHERE is_admin=1 AND id!='local'").fetchone():
            return
        username = os.getenv('BID_ADMIN_USERNAME', '').strip()
        password = os.getenv('BID_ADMIN_PASSWORD', '')
        if not username or username == '__local__' or not 12 <= len(password) <= 256:
            raise RuntimeError('First authenticated startup requires BID_ADMIN_USERNAME and a 12–256 character BID_ADMIN_PASSWORD.')
        conn.execute('INSERT INTO users VALUES(?,?,?,?,?)',
                     (new_id('usr'), username, hash_password(password), 1, now()))


def current_user(request: Request) -> Principal:
    if not env_bool('BID_AUTH_ENABLED'):
        return Principal('local', '__local__', True)
    token = request.cookies.get(COOKIE_NAME, '')
    with transaction() as conn:
        row = conn.execute('''SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id
            WHERE s.token_hash=? AND s.expires_at>? AND u.id!='local' ''',
                           (token_hash(token), time.time())).fetchone()
    if not row:
        raise HTTPException(401, '请先登录')
    if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
        if not hmac.compare_digest(request.headers.get('X-CSRF-Token', ''), csrf_token(token)):
            raise HTTPException(403, 'CSRF 校验失败，请刷新后重试')
    return Principal(row['id'], row['username'], bool(row['is_admin']))


def legacy_admin(request: Request) -> Principal:
    user = current_user(request)
    if not user.is_admin:
        raise HTTPException(403, '旧版接口仅供管理员使用，请使用文档工作台')
    return user
