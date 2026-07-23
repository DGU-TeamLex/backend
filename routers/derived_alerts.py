"""재고미달 알림 온디맨드 파생 (backend#53).

`alerts` 테이블은 2026-07-10 CRITICAL 일부만 품목당 상한을 걸어 1회성 시드된
낡은 스냅샷(30건)이라, 2026-07-17 재적재된 `inventory`(실재고)와 단절돼 있다.
그래서 대시보드 openAlerts=30 이 실제 부족 상황(재주문점 미달 약 22만 건)을
전혀 대표하지 못했다.

이 라우터는 이슈 #53 의 제안(온디맨드 파생)을 따른다:
  - 재고미달 알림은 저장 테이블에 의존하지 않고 조회 시점에 `inventory` 에서 파생한다.
  - 22만 건을 전부 알림화할 수 없으므로 기관당 시급도 상위 N건으로 제한(중복 억제).
  - `alerts` 저장 테이블(routers/wep_stock.py 의 /alerts)은 사람이 처리상태
    (승인·해소 이력)를 관리해야 하는 알림 용도로 그대로 남긴다 — 이 라우터는 병행 추가다.

INSTITUTION 은 자기 기관 알림으로만 스코프되고, CENTRAL 은 전국을 본다
(routers/wep_stock.py 의 /alerts 와 동일한 소유권 규칙).
"""
from fastapi import APIRouter, Depends, Query

from auth.deps import require_role
from db import queries as DB

router = APIRouter(prefix="/api/v1")

T_ALERT = ["알림"]

_ALLOWED_STATUSES = ("CRITICAL", "BELOW_ROP")


def _scoped_institution(current_user: dict, institution: str | None) -> str | None:
    """INSTITUTION 은 자기 기관으로 강제 스코프, CENTRAL 은 요청값(또는 전체)."""
    if current_user["role"] == "INSTITUTION":
        return current_user["institutionId"]
    return institution


@router.get("/alerts/derived", tags=T_ALERT, summary="재고미달 알림(실재고 온디맨드 파생)")
def alerts_derived(
    institution: str | None = None,
    status: str | None = Query(default=None, description="CRITICAL | BELOW_ROP (미지정 시 둘 다)"),
    per_institution: int = Query(default=5, ge=1, le=100, description="기관당 시급도 상위 N건"),
    limit: int = Query(default=200, ge=1, le=2000),
    current_user: dict = Depends(require_role("CENTRAL", "INSTITUTION")),
):
    """`inventory` 실재고에서 재고미달 알림을 조회 시점에 파생한다(낡은 시드 미사용)."""
    institution = _scoped_institution(current_user, institution)
    statuses = (status,) if status in _ALLOWED_STATUSES else None
    items = DB.shortage_alerts_derived(
        institution=institution, statuses=statuses,
        per_institution=per_institution, limit=limit,
    )
    return {
        "items": items,
        "totalElements": len(items),
        "source": "derived-from-inventory",
        "note": (
            "실재고(inventory)에서 조회 시점에 파생한 재고미달 알림입니다. "
            "낡은 시드 alerts 테이블이 아니며, 기관당 시급도 상위 "
            f"{per_institution}건으로 제한됩니다. 전체 규모는 /alerts/derived/summary 참고."
        ),
    }


@router.get("/alerts/derived/summary", tags=T_ALERT, summary="재고미달 실제 규모 집계")
def alerts_derived_summary(
    institution: str | None = None,
    current_user: dict = Depends(require_role("CENTRAL", "INSTITUTION")),
):
    """상태별 재고미달 건수·기관수·품목수 — 대시보드 openAlerts 대체 지표."""
    institution = _scoped_institution(current_user, institution)
    summary = DB.shortage_alerts_summary(institution=institution)
    return {**summary, "source": "derived-from-inventory"}
