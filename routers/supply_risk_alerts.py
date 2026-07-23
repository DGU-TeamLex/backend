"""공급위험 경보 API — ai/data 점수 소비 → 기관별 경보 서빙 (이슈 #44).

공급위험 점수·레벨 계산은 ai/data 소유. backend 는 그 점수를 **소비**해 임계/레벨
기준으로 기관별 경보를 생성하고, 2-뷰(기관/중앙)로 서빙한다.

- 점수원(초안): 품목군 공급위험(routers/wep_data.py 의 SUPPLY_RISK, ai/data 산출물의
  스탠드인). ai 서빙 배포 시 이 소비원만 교체하면 된다.
- 경보 생성: 위험 품목군(level ≥ 임계)을 그 품목군 재고를 보유한 기관과 교차해
  기관별 경보로 만든다. 재고는 Neon Postgres 실데이터(inventory_policy_rows)를 쓴다.
- 소유권 스코프: INSTITUTION 은 자기 기관 경보만, CENTRAL 은 전국.

GraphQL 병행(REST+GraphQL): 기존 `alerts` 리졸버 패턴을 그대로 따르며, 큰 스키마
파일(graphql_schema.py) 변경 리스크를 피하려 이번 자동 초안에서는 REST 를 우선
구현한다 — GraphQL 병행은 후속으로 PR 본문에 명시한다.
"""
from fastapi import APIRouter, Depends, HTTPException, Query

from . import wep_data as D
from auth.deps import require_role
from db import queries as DB

router = APIRouter(prefix="/api/v1")

T_C = ["모듈 C · 공급위험 경보"]
_scoped = Depends(require_role("CENTRAL", "INSTITUTION"))

# 경보 임계: 위험 레벨을 심각도 순위로 정규화(ai/data 레벨 명칭 혼용 대비).
_LEVEL_RANK = {"CRITICAL": 3, "WARNING": 2, "WARN": 2, "CAUTION": 1, "NORMAL": 0}
_DEFAULT_MIN_RANK = 1  # CAUTION 이상만 경보


def _risk_by_group() -> dict:
    """품목군ID -> 공급위험 점수/레벨 (ai/data 점수 소비원)."""
    return {r["itemGroupId"]: r for r in D.SUPPLY_RISK}


def _severity_for(rank: int) -> str:
    return {3: "CRITICAL", 2: "WARNING", 1: "CAUTION"}.get(rank, "INFO")


def _build_alerts(min_rank: int, institution: str | None) -> list:
    """위험 품목군 × 보유 기관 재고 → 기관별 공급위험 경보."""
    risk = _risk_by_group()
    group_name = {g["itemGroupId"]: g["name"] for g in D.ITEM_GROUPS}
    rows = DB.inventory_policy_rows(institution=institution, limit=500)
    seen = set()
    alerts = []
    for r in rows:
        gid = r.get("itemGroupId")
        rk = risk.get(gid)
        if not rk:
            continue
        rank = _LEVEL_RANK.get(rk["level"], 0)
        if rank < min_rank:
            continue
        key = (r["institutionId"], gid)
        if key in seen:
            continue
        seen.add(key)
        alerts.append({
            "institutionId": r["institutionId"],
            "institutionName": r.get("institutionName"),
            "sido": r.get("sido"),
            "itemGroupId": gid,
            "itemGroupName": group_name.get(gid, gid),
            "riskScore": rk["riskScore"],
            "level": rk["level"],
            "severity": _severity_for(rank),
            "leadTimeEstimate": rk.get("leadTimeEstimate"),
            "confidence": rk.get("confidence"),
            "source": "ai/data-supply-risk(consumed)",
        })
    alerts.sort(key=lambda a: (_LEVEL_RANK.get(a["level"], 0), a["riskScore"]), reverse=True)
    return alerts


@router.get("/supply-risk-alerts", tags=T_C, summary="기관별 공급위험 경보(소유권 스코프)")
def supply_risk_alerts(
    level: str | None = None,
    institution: str | None = None,
    min_rank: int = Query(_DEFAULT_MIN_RANK, ge=0, le=3, description="경보 임계(0=NORMAL~3=CRITICAL)"),
    current_user: dict = _scoped,
):
    if current_user["role"] == "INSTITUTION":
        institution = current_user["institutionId"]
    items = _build_alerts(min_rank, institution)
    if level:
        items = [a for a in items if a["level"] == level]
    return {"items": items, "totalElements": len(items)}


@router.get("/supply-risk-alerts/central", tags=T_C, summary="중앙 뷰 — 공급위험 경보 집계")
def supply_risk_alerts_central(_admin: dict = Depends(require_role("CENTRAL"))):
    items = _build_alerts(_DEFAULT_MIN_RANK, None)
    by_level: dict = {}
    by_institution: dict = {}
    for a in items:
        by_level[a["level"]] = by_level.get(a["level"], 0) + 1
        bi = by_institution.setdefault(
            a["institutionId"],
            {"institutionId": a["institutionId"], "institutionName": a["institutionName"], "alerts": 0},
        )
        bi["alerts"] += 1
    top = sorted(by_institution.values(), key=lambda x: x["alerts"], reverse=True)[:20]
    return {
        "asOf": D.TODAY,
        "totalAlerts": len(items),
        "byLevel": by_level,
        "topInstitutions": top,
        "items": items[:50],
    }


@router.get("/supply-risk-alerts/institution/{institution_id}", tags=T_C,
            summary="기관 뷰 — 해당 기관 공급위험 경보")
def supply_risk_alerts_institution(institution_id: str, current_user: dict = _scoped):
    if current_user["role"] == "INSTITUTION" and institution_id != current_user["institutionId"]:
        raise HTTPException(403, "권한이 없습니다.")
    items = _build_alerts(_DEFAULT_MIN_RANK, institution_id)
    return {"institutionId": institution_id, "items": items, "totalElements": len(items)}
