"""재배치 제안 실데이터 파생 (이슈 #26).

`/relocations`(routers/wep_stock.py)는 여전히 고정 MOCK 3건이다. 이 라우터는 실재고
(Neon Postgres `inventory`)에서 부족(CRITICAL/BELOW_ROP) 기관과 여유(OK) 기관을 같은
표준품목 기준으로 매칭해 재배치 제안을 조회 시점에 파생한다 — routers/derived_alerts.py
가 `/alerts`에 붙인 것과 같은 병행 추가 패턴이다. 기존 `/relocations`(대시보드가 참조)는
그대로 두고, 이 라우터는 `/relocations/derived`로 신규 추가한다.

⚠️ 한계:
  - 원본 데이터에 로트·유효기간 컬럼이 없어 FEFO(유효기간 임박 우선) 기준은 적용하지 못한다.
  - (2026-08-17, #75) 이전엔 "같은 시도" 를 우선 매칭했으나, 기관코드↔실명 매핑이
    정렬순서 임의매핑이라(#16) 시도 정보 자체에 근거가 없어 그 우선순위를 제거했다
    (`sameSido`/`sameSidoTentative` 필드도 함께 제거). 이제는 여유분 큰 순으로만 매칭한다.
"""
from fastapi import APIRouter, Depends, Query

from auth.deps import require_role
from db import queries as DB

router = APIRouter(prefix="/api/v1")

T_D = ["모듈 D · 적정재고·발주·재배치"]

_central_only = Depends(require_role("CENTRAL"))


@router.get("/relocations/derived", tags=T_D, summary="재배치 제안(실재고 온디맨드 파생)")
def relocations_derived(
    limit: int = Query(default=100, ge=1, le=1000),
    _admin: dict = _central_only,
):
    """부족 기관과 여유 기관을 실재고 기준으로 매칭한 재배치 제안(고정 MOCK 미사용)."""
    items = DB.relocation_candidates(limit=limit)
    return {
        "items": items,
        "totalElements": len(items),
        "source": "derived-from-inventory",
        "note": (
            "실재고(inventory)에서 부족↔여유 기관을 같은 표준품목 기준으로 매칭한 제안입니다. "
            "지역(시도) 우선 매칭은 기관코드 매핑이 임의매핑이라(backend#16, #75) 제거했으며, "
            "유효기간(FEFO) 데이터는 원본에 없어 반영하지 못했습니다."
        ),
    }
