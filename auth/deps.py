"""FastAPI 인증/인가 의존성.

get_current_user: Authorization: Bearer <token> 필수, 실패 시 401.
require_role(*roles): get_current_user 를 감싸 role 이 허용 목록에 없으면 403.
INSTITUTION 역할은 institution_id 로 스코프되므로, 기관별 엔드포인트에서는
require_role("CENTRAL", "INSTITUTION") 로 통과시킨 뒤 개별 라우터에서
current_user["institutionId"] 와 요청 경로의 institution_id 가 일치하는지
(role == CENTRAL 이면 전체 허용) 추가로 검사한다.
"""
import jwt
from fastapi import Depends, Header, HTTPException, status

from .security import decode_access_token


def get_current_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="인증 토큰이 필요합니다.")
    token = authorization.split(" ", 1)[1]
    try:
        return decode_access_token(token)
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="유효하지 않거나 만료된 토큰입니다.")


def require_role(*roles: str):
    def _dep(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user["role"] not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="권한이 없습니다.")
        return current_user
    return _dep
