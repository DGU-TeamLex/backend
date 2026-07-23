"""사용자 관리 API — 관리자 콘솔(frontend#18)에서 계정 조회/생성/역할변경 (이슈 #25).

공개 가입 플로우는 없다(정부 발주 특성상 유지). 계정은 지금까지 CLI 스크립트
(scripts/seed_users.py)로만 만들 수 있었는데, 웹 관리자 콘솔에서 계정을 관리하려면
API 가 필요하다. 모든 엔드포인트는 CENTRAL(중앙관리자) 전용이며 auth/deps.py 의
require_role("CENTRAL") 을 재사용한다. 응답에는 비밀번호 해시를 절대 포함하지 않는다.
"""
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth.deps import require_role
from auth.security import hash_password
from db import queries as DB

router = APIRouter(prefix="/api/v1")

T_AUTH = ["인증·사용자"]

# 계정 관리는 전부 CENTRAL 전용 — INSTITUTION 담당자는 타 계정을 조회/수정할 수 없다.
_central_only = Depends(require_role("CENTRAL"))

_ROLES = {"CENTRAL", "INSTITUTION"}


class CreateUserBody(BaseModel):
    email: str
    name: str
    role: str
    institutionId: str | None = None


class UpdateUserBody(BaseModel):
    name: str | None = None
    role: str | None = None
    institutionId: str | None = None


def _validate_role(role: str) -> None:
    if role not in _ROLES:
        raise HTTPException(status_code=422, detail=f"role 은 {sorted(_ROLES)} 중 하나여야 합니다.")


@router.get("/users", tags=T_AUTH, summary="계정 목록(CENTRAL 전용, 비밀번호 해시 제외)")
def list_users(current_user: dict = _central_only):
    return DB.list_users()


@router.post("/users", tags=T_AUTH, status_code=201,
             summary="계정 생성(CENTRAL 전용, 초기 비밀번호 1회 노출)")
def create_user(body: CreateUserBody, current_user: dict = _central_only):
    _validate_role(body.role)
    if body.role == "INSTITUTION" and not body.institutionId:
        raise HTTPException(status_code=422, detail="INSTITUTION 역할은 institutionId 가 필요합니다.")
    if DB.get_user_by_email(body.email):
        raise HTTPException(status_code=409, detail="이미 존재하는 이메일입니다.")
    # 공개 가입이 없으므로 초기 비밀번호는 서버가 랜덤 생성해 이 응답에서만 1회 노출한다
    # (저장/재조회 불가 — 이후 분실 시 PATCH 대신 재발급 플로우가 필요하나 이번 범위 밖).
    initial_password = secrets.token_urlsafe(12)
    user_id = "u_" + secrets.token_hex(8)
    created = DB.create_user(
        user_id, body.email, hash_password(initial_password),
        body.name, body.role, body.institutionId,
    )
    return {**created, "initialPassword": initial_password}


@router.patch("/users/{user_id}", tags=T_AUTH,
              summary="계정 수정(CENTRAL 전용, 이름·역할·소속기관)")
def update_user(user_id: str, body: UpdateUserBody, current_user: dict = _central_only):
    fields = body.model_dump(exclude_unset=True)
    if "role" in fields:
        _validate_role(fields["role"])
    updated = DB.update_user(user_id, fields)
    if updated is None:
        raise HTTPException(status_code=404, detail="해당 계정을 찾을 수 없습니다.")
    return updated
