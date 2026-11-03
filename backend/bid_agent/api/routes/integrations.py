"""External integration status APIs (MinerU). Does not write .env files."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from bid_agent.core.identity import Principal
from bid_agent.core.security import current_user
from bid_agent.services import mineru_config

router = APIRouter(prefix='/v1/integrations', tags=['integrations'])


class MinerUOverride(BaseModel):
    token: str | None = Field(default=None, max_length=512)
    timeout: int | None = Field(default=None, ge=5, le=600)


@router.get('/mineru')
def mineru_status(user: Principal = Depends(current_user)):
    _ = user
    return mineru_config.get_public_config()


@router.put('/mineru')
def mineru_override(body: MinerUOverride, user: Principal = Depends(current_user)):
    if not user.is_admin:
        from fastapi import HTTPException
        raise HTTPException(403, '仅管理员可设置进程内 MinerU 覆盖')
    return mineru_config.set_runtime_override(token=body.token, timeout=body.timeout)


@router.delete('/mineru')
def mineru_clear(user: Principal = Depends(current_user)):
    if not user.is_admin:
        from fastapi import HTTPException
        raise HTTPException(403, '仅管理员可清除进程内 MinerU 覆盖')
    return mineru_config.clear_runtime_override()


@router.post('/mineru/test')
def mineru_test(user: Principal = Depends(current_user)):
    _ = user
    return mineru_config.test_connection()
