"""
WeP/TeamLex API — Vercel(Python 서버리스) 배포 진입점.

routers/ 패키지의 모든 모듈을 스캔해 `router` (APIRouter) 를 자동 등록한다.
새 기능은 routers/<slug>.py 에 `router = APIRouter(...)` 만 추가하면 이 파일을 수정하지
않아도 자동으로 배포된다. (vercel.json 의 includeFiles 로 routers/** 가 함께 번들된다.)

vercel.json 의 rewrite 로 모든 경로가 이 함수(/api/index)로 라우팅되고,
FastAPI 가 원본 경로(/api/v1/... 등)로 다시 라우팅한다.
"""
import importlib
import pkgutil

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import routers

app = FastAPI(title="TeamLex API", version="0.1.0-draft")

# 프론트엔드(다른 도메인)에서 호출 가능하도록 CORS 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


# routers/ 패키지의 모든 라우터 자동 등록
_registered = []
for _finder, _name, _ispkg in pkgutil.iter_modules(routers.__path__):
    _module = importlib.import_module(f"routers.{_name}")
    _router = getattr(_module, "router", None)
    if _router is not None:
        app.include_router(_router)
        _registered.append(_name)


@app.get("/api/_registered")
def registered():
    """디버그: 자동 등록된 라우터 목록."""
    return {"routers": _registered}
