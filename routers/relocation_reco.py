"""재배치 제안 실데이터 파생 (이슈 #26).

`/relocations`(routers/wep_stock.py)는 여전히 고정 MOCK 3건이다. 이 라우터는 실재고
(Neon Postgres `inventory`)에서 부족(CRITICAL/BELOW_ROP) 기관과 여유(OK) 기관을 같은
표준품목 기준으로 매칭해 재배치 제안을 조회 시점에 파생한다 — routers/derived_alerts.py
가 `/alerts`에 붙인 것과 같은 병행 추가 패턴이다. 기존 `/relocations`(대시보드가 참조)는
그대로 두고, 이 라우터는 `/relocations/derived`로 신규 추가한다.

⚠️ 두 가지 한계가 있다:
  - 기관코드↔실명 매핑이 아직 정렬순서 임의매핑이라(#16) "같은 시도" 매칭도 그 부정확성을
    물려받는다 — 응답의 `sameSidoTentative`로 명시한다.
  - 원본 데이터에 로트·유효기간 컬럼이 없어 FEFO(유효기간 임박 우선) 기준은 적용하지 못한다.
#16 이 해결되면 시도 매칭 신뢰도가, 유효기간 데이터가 추가되면 FEFO 기준이 개선될 수 있다.
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
            "같은 시도 매칭은 기관코드 매핑이 잠정이라(backend#16) 참고용이며, "
            "유효기간(FEFO) 데이터는 원본에 없어 반영하지 못했습니다."
        ),
    }
