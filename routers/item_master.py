"""품목 마스터(canonical) 조회 + 품목별 재고 실엔드포인트 (이슈 #42).

기존 품목/재고 조회는 `wep_stock.py` 에 흩어져 있고 표준품목은 17,148종 카탈로그를
쓴다. 이 라우터는 "품목 마스터 = data canonical" 노출을 위한 단일 진입점을 제공하며,
품목 상세에서 전국 기관 재고를 실데이터(Neon Postgres)로 함께 반환한다.

범위(초안): 조회(READ) 실엔드포인트 전환에 한정한다. 쓰기(POST/PATCH/DELETE)와
카탈로그 17,148 → data canonical(101,546) 실제 교체는 공용 스키마 확정(DB #38)과
data 적재가 선행돼야 하므로 이번 자동 초안 범위 밖 — PR 본문에 명시한다.
"""
from fastapi import APIRouter, Depends, HTTPException, Query

from auth.deps import require_role
from db import queries as DB

router = APIRouter(prefix="/api/v1")

T_MASTER = ["마스터"]
_central_only = Depends(require_role("CENTRAL"))

# data canonical 목표 규모(대표품목). 실제 적재 전까지는 현재 카탈로그를 노출하며,
# 응답 메타에 목표/현재 규모를 함께 실어 소비자(FE)가 전환 상태를 인지하게 한다.
_CANONICAL_TARGET = 101546


@router.get("/item-master", tags=T_MASTER, summary="품목 마스터(canonical) 조회 — 검색·품목군·페이지")
def item_master(q: str | None = None, group: str | None = None,
                limit: int = Query(500, le=1000), offset: int = 0,
                _admin: dict = _central_only):
    result = DB.standard_items(q=q, group=group, limit=min(limit, 1000), offset=offset)
    return {
        **result,
        "canonical": {
            "source": "data-canonical(대표품목)",
            "targetCatalogSize": _CANONICAL_TARGET,
            "currentCatalogSize": result.get("totalElements", 0),
            "swapPending": True,  # DB #38 스키마 확정·data 적재 후 실제 교체
        },
        "limit": limit,
        "offset": offset,
    }


@router.get("/item-master/{standard_code}", tags=T_MASTER, summary="품목 마스터 상세")
def item_master_detail(standard_code: str, _admin: dict = _central_only):
    found = DB.standard_items(q=standard_code, limit=1000)
    item = next((it for it in found["items"] if it["standardCode"] == standard_code), None)
    if not item:
        raise HTTPException(404, "standard item not found")
    return item


@router.get("/item-master/{standard_code}/stock", tags=T_MASTER,
            summary="품목별 전국 기관 재고(실데이터)")
def item_master_stock(standard_code: str, limit: int = Query(300, le=500),
                      _admin: dict = _central_only):
    """해당 표준품목의 전국 기관 재고 현황을 실데이터로 반환한다(mock 없음).
    기존 재고 뷰(inventory_policy_rows)를 표준코드로 필터링해 소비한다."""
    rows = [r for r in DB.inventory_policy_rows(limit=500) if r["standardCode"] == standard_code]
    rows = rows[:limit]
    return {"standardCode": standard_code, "items": rows, "totalElements": len(rows)}
