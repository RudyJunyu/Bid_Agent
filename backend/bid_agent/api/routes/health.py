"""Liveness and database readiness probes; never call external models."""
import sqlite3
from contextlib import closing
from fastapi import APIRouter, HTTPException
from bid_agent.core.settings import BUILD_VERSION, DB_PATH, env_bool

router = APIRouter(tags=['health'])


@router.get('/health')
def health() -> dict:
    return {'status': 'ok', 'build': BUILD_VERSION, 'features': {
        'project_library': True, 'project_delete': True,
        'request_scoped_model_selection': True,
        'chroma_vector_store': env_bool('BID_VECTOR_STORE_ENABLED'),
    }}


@router.get('/ready')
def ready() -> dict:
    try:
        with closing(sqlite3.connect(DB_PATH.as_uri() + '?mode=ro', uri=True, timeout=2)) as conn:
            conn.execute('SELECT id FROM projects LIMIT 1').fetchall()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail='Database is not ready') from exc
    return {'status': 'ready'}
