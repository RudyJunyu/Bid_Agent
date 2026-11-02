"""Minimal account/session administration, with cookies and CSRF protection."""
import secrets
import sqlite3
import time
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from bid_agent.core.identity import Principal
from bid_agent.core.security import (COOKIE_NAME, SESSION_SECONDS, csrf_token, current_user,
                                     hash_password, legacy_admin, token_hash, verify_password)
from bid_agent.core.settings import env_bool
from bid_agent.repositories.platform import new_id, now, transaction

router = APIRouter(prefix='/auth', tags=['identity'])
_failures = {}


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class NewUser(BaseModel):
    username: str = Field(pattern=r'^[A-Za-z0-9_.@-]{3,64}$')
    password: str = Field(min_length=12, max_length=256)
    is_admin: bool = False


@router.get('/status')
def auth_status():
    return {'enabled': env_bool('BID_AUTH_ENABLED')}


@router.post('/login')
def login(body: Credentials, request: Request, response: Response):
    if not env_bool('BID_AUTH_ENABLED'):
        raise HTTPException(409, '当前为本机单用户模式，无需登录')
    key = (request.client.host if request.client else '', body.username)
    count, until = _failures.get(key, (0, 0))
    if until < time.time():
        count = 0
    if count >= 10:
        raise HTTPException(429, '登录失败次数过多，请五分钟后重试')
    with transaction() as conn:
        row = conn.execute("SELECT * FROM users WHERE username=? AND id!='local'", (body.username,)).fetchone()
        if not row or not verify_password(body.password, row['password_hash']):
            if len(_failures) >= 1024:
                _failures.pop(next(iter(_failures)))
            _failures[key] = (count+1, time.time()+300)
            raise HTTPException(401, '用户名或密码错误')
        _failures.pop(key, None)
        token = secrets.token_urlsafe(32)
        conn.execute('DELETE FROM sessions WHERE expires_at<?', (time.time(),))
        conn.execute('INSERT INTO sessions VALUES(?,?,?,?)',
                     (token_hash(token), row['id'], time.time()+SESSION_SECONDS, now()))
    response.set_cookie(COOKIE_NAME, token, httponly=True, samesite='strict',
                        secure=env_bool('BID_COOKIE_SECURE'), max_age=SESSION_SECONDS, path='/')
    return {'user': {'id': row['id'], 'username': row['username'], 'is_admin': bool(row['is_admin'])},
            'csrf_token': csrf_token(token)}


@router.get('/me')
def me(request: Request, user: Principal = Depends(current_user)):
    return {'user': asdict(user), 'csrf_token': csrf_token(request.cookies[COOKIE_NAME])
            if env_bool('BID_AUTH_ENABLED') else ''}


@router.post('/logout')
def logout(request: Request, response: Response, user: Principal = Depends(current_user)):
    with transaction() as conn:
        conn.execute('DELETE FROM sessions WHERE token_hash=?', (token_hash(request.cookies.get(COOKIE_NAME, '')),))
    response.delete_cookie(COOKIE_NAME, path='/')
    return {'logged_out': True}


@router.post('/users', status_code=201)
def create_user(body: NewUser, actor: Principal = Depends(legacy_admin)):
    if body.username == '__local__':
        raise HTTPException(422, '保留用户名')
    user_id = new_id('usr')
    try:
        with transaction() as conn:
            conn.execute('INSERT INTO users VALUES(?,?,?,?,?)',
                         (user_id, body.username, hash_password(body.password), body.is_admin, now()))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, '用户名已存在') from exc
    return {'id': user_id, 'username': body.username, 'is_admin': body.is_admin}
