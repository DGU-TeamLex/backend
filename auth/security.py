"""비밀번호 해시 · JWT 발급/검증.

SECRET_KEY 는 반드시 환경변수(JWT_SECRET)로 주입한다 — 코드에 하드코딩하지 않는다.
로컬/CI 등 미설정 환경에서만 개발용 기본값으로 폴백한다(프로덕션 배포 시 Vercel
환경변수에 JWT_SECRET 을 반드시 설정해야 실제로 안전하다).
"""
import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_SECONDS = 60 * 60 * 8  # 8시간


def _secret_key() -> str:
    return os.environ.get("JWT_SECRET", "dev-only-insecure-secret-change-me")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(user: dict) -> str:
    """user 는 db.queries._user_row() 형태(camelCase, passwordHash 제외 가능)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user["id"],
        "email": user["email"],
        "name": user["name"],
        "role": user["role"],
        "institutionId": user.get("institutionId"),
        "iat": now,
        "exp": now + timedelta(seconds=ACCESS_TOKEN_EXPIRE_SECONDS),
    }
    return jwt.encode(payload, _secret_key(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """만료/서명 오류 시 jwt.PyJWTError 를 그대로 전파한다 — 호출부에서 401 처리."""
    payload = jwt.decode(token, _secret_key(), algorithms=[ALGORITHM])
    return {
        "id": payload["sub"],
        "email": payload["email"],
        "name": payload["name"],
        "role": payload["role"],
        "institutionId": payload.get("institutionId"),
    }
