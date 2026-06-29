"""
TeamLex API — Vercel(Python 서버리스) 배포 진입점.

기능별 라우터(routers/<slug>.py 의 `router`)를 정적 import 하여 등록한다.
정적 import 라서 Vercel 이 routers/ 파일을 자동으로 번들한다.

새 기능 추가 방법 (spec-bot 루틴 / 사람 공통):
  1) routers/<slug>.py 에 `router = APIRouter(prefix="/api/v1", ...)` 정의
  2) 아래 "라우터 등록" 구역에 두 줄 추가:
       from routers import <slug>
       app.include_router(<slug>.router)

vercel.json 의 rewrite 로 모든 경로가 이 함수(/api/index)로 라우팅되고,
FastAPI 가 원본 경로(/api/v1/... 등)로 다시 라우팅한다.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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


# ===== 라우터 등록 (기능 추가 시 여기에 두 줄씩) =====
from routers import wep_stock  # noqa: E402

app.include_router(wep_stock.router)
# ===================================================
