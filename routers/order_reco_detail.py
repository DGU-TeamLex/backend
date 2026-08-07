"""세부품목(규격) 단위 발주권고 API — AI 발주권고(SS/ROP) 소비 (이슈 #43).

SS/ROP·발주권고 수치 계산의 소유권은 ai(모듈 D)로 이관됐다. backend 는 그 결과를
**소비**해 세부품목(규격) 단위 발주권고를 서빙한다. ai 서빙 API 가 아직 배포되지
않았으므로, 폴백 정책으로 backend 자체 SS/ROP 실데이터(Neon Postgres, SSIS 기반)를
소비한다 — 응답의 `source` 필드로 어느 경로인지 표시한다(`ai-serving` | `backend-ssrop`).

"세부품목 단위"는 표준품명에서 규격 토큰(3cc/5cc, 1L/2L, 10mL 등)을 추출해 `spec`
필드로 노출한다. 로트/규격 정규화 컬럼이 DB 에 생기면 그 값으로 대체한다.
"""
import re

from fastapi import APIRouter, Depends, Query

from auth.deps import require_role
from db import queries as DB

router = APIRouter(prefix="/api/v1")

T_D = ["모듈 D · 적정재고·발주·재배치"]
# CENTRAL 은 전국, INSTITUTION 은 자기 기관 발주권고만.
_scoped = Depends(require_role("CENTRAL", "INSTITUTION"))

# 규격 토큰: 3cc/5cc, 1mL/10mL, 1L/2L, 5g 등. 대소문자·한글 단위 혼용 대비.
_SPEC_RE = re.compile(r"(\d+(?:\.\d+)?\s*(?:cc|mL|ml|L|g|mg|호|G|Fr))", re.IGNORECASE)

# ai 서빙 미배포 상태 — 폴백으로 backend SS/ROP 실데이터를 소비한다.
_AI_SERVING_AVAILABLE = False


def _spec_of(standard_name: str) -> str | None:
    if not standard_name:
        return None
    m = _SPEC_RE.search(standard_name)
    return m.group(1).replace(" ", "") if m else None


@router.get("/order-recommendations/detailed", tags=T_D,
            summary="세부품목(규격) 단위 발주권고 — AI 소비/폴백")
def order_recommendations_detailed(
    institution: str | None = None,
    spec: str | None = Query(None, description="규격 필터(예: 3cc, 1L)"),
    current_user: dict = _scoped,
):
    # INSTITUTION 은 자기 기관으로 스코프 고정.
    if current_user["role"] == "INSTITUTION":
        institution = current_user["institutionId"]

    rows = DB.order_recommendations(institution=institution)
    source = "ai-serving" if _AI_SERVING_AVAILABLE else "backend-ssrop"

    enriched = []
    for r in rows:
        item_spec = _spec_of(r.get("standardName", ""))
        if spec and item_spec != spec:
            continue
        enriched.append({**r, "spec": item_spec, "source": source})

    # 규격별 집계(세부품목 단위 뷰 지원).
    by_spec: dict = {}
    for r in enriched:
        key = r["spec"] or "규격미상"
        b = by_spec.setdefault(key, {"spec": key, "lines": 0, "totalRecommendedQty": 0})
        b["lines"] += 1
        b["totalRecommendedQty"] += r.get("recommendedQty", 0) or 0

    return {
        "items": enriched,
        "totalElements": len(enriched),
        "bySpec": sorted(by_spec.values(), key=lambda x: x["totalRecommendedQty"], reverse=True),
        "source": source,
        "aiServingAvailable": _AI_SERVING_AVAILABLE,
        "fallbackPolicy": "ai 서빙 미배포 시 backend SS/ROP 실데이터로 폴백",
    }
