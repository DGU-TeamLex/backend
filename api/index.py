"""
WeP-Stock API — Vercel(Python 서버리스) 배포 진입점.

기능별 라우터(routers/<slug>.py 의 `router`)를 정적 import 하여 등록한다.
정적 import 라서 Vercel 이 routers/ 파일을 자동으로 번들한다.

API 문서:
  - Swagger UI : /docs
  - ReDoc      : /redoc
  - OpenAPI    : /openapi.json
  - GraphQL    : /graphql (GraphiQL IDE 포함, 사업수행계획서 4.3.2 REST+GraphQL 대응)
루트(/) 접속 시 /docs 로 리다이렉트한다.

새 기능 추가 방법 (spec-bot 루틴 / 사람 공통):
  1) routers/<slug>.py 에 `router = APIRouter(prefix="/api/v1", ...)` 정의
  2) 아래 "라우터 등록" 구역에 두 줄 추가:
       from routers import <slug>
       app.include_router(<slug>.router)
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

DESCRIPTION = """
**전국 보건기관 의료물품 통합 재고관리 웹서비스 WeP-Stock** 의 REST API (데모).

명세서 v0.1 기반. 파일 기반(가명처리 XLSX) 인테이크 →
물품 표준화(A) → 수요 예측(B) · 공급위험 경보(C) → 적정재고·알림·재배치(D) → 2-뷰 대시보드.

> 데이터는 시연용 시드값이며 서버리스 인메모리라 영속되지 않습니다.
""".strip()

TAGS_METADATA = [
    {"name": "인증·사용자", "description": "로그인/토큰/내 프로필 (데모 목업)"},
    {"name": "마스터", "description": "기관 · 표준품목 · 품목군"},
    {"name": "데이터 인테이크", "description": "XLSX 업로드·검증·적재 배치 (R-EYKKES)"},
    {"name": "모듈 A · 물품 표준화", "description": "표준코드 매핑 · 검수 큐"},
    {"name": "모듈 B · 수요 예측", "description": "월 수요 분포(mean+분위수)·패턴분류"},
    {"name": "모듈 C · 공급위험 경보", "description": "원자재·뉴스 기반 위험 점수/레벨/근거"},
    {"name": "모듈 D · 적정재고·발주·재배치", "description": "SS/ROP · 발주권고 · 재배치 제안"},
    {"name": "알림", "description": "재고미달·공급위험·유효기간임박"},
    {"name": "외부지표", "description": "원자재 가격·뉴스리스크지수 등"},
    {"name": "대시보드", "description": "중앙 뷰 · 기관 뷰"},
]

app = FastAPI(
    title="WeP-Stock API",
    description=DESCRIPTION,
    version="0.1.0-draft",
    openapi_tags=TAGS_METADATA,
    contact={"name": "TeamLex"},
)

# 프론트엔드(다른 도메인)에서 호출 가능하도록 CORS 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/health", tags=["대시보드"])
def health():
    return {"status": "ok"}


# ===== 라우터 등록 (기능 추가 시 여기에 두 줄씩) =====
from routers import wep_stock  # noqa: E402

app.include_router(wep_stock.router)
# ===================================================

# ===== GraphQL (REST 병행, 사업수행계획서 4.3.2) =====
from strawberry.fastapi import GraphQLRouter  # noqa: E402
from routers.graphql_schema import schema, get_context  # noqa: E402

# context_getter: 요청마다 새 DataLoader 세트를 만들어 Institution.inventory/summary
# 같은 중첩 필드가 여러 기관에 대해 동시 요청될 때 배치 조회되게 한다(N+1 방지).
app.include_router(GraphQLRouter(schema, context_getter=get_context), prefix="/graphql")
# ===================================================
