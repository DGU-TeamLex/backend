"""WeP-Stock — 전국 보건기관 의료물품 통합 재고관리 API (데모 구현).

명세(기능/데이터모델/API)의 핵심 엔드포인트를 시드 데이터로 제공한다.
실제 운영의 인테이크/표준화(A)/예측(B)/공급위험(C)/적정재고(D) 파이프라인 산출물을
현실적인 값으로 표현한 시연용 백엔드. 엔드포인트는 명세 모듈별 태그로 그룹화된다.
"""
from fastapi import APIRouter, HTTPException

from . import wep_data as D

router = APIRouter(prefix="/api/v1")

T_AUTH = ["인증·사용자"]
T_MASTER = ["마스터"]
T_INTAKE = ["데이터 인테이크"]
T_A = ["모듈 A · 물품 표준화"]
T_B = ["모듈 B · 수요 예측"]
T_C = ["모듈 C · 공급위험 경보"]
T_D = ["모듈 D · 적정재고·발주·재배치"]
T_ALERT = ["알림"]
T_EXT = ["외부지표"]
T_DASH = ["대시보드"]


# ===== 인증 / 사용자 (데모: 목업) =====
@router.post("/auth/login", tags=T_AUTH, summary="로그인(목업)")
def login(body: dict):
    role = (body or {}).get("role", "CENTRAL")
    inst = (body or {}).get("institutionId")
    return {
        "accessToken": "demo.jwt.token",
        "refreshToken": "demo.refresh.token",
        "expiresIn": 3600,
        "user": {"id": "u_demo", "role": role, "institutionId": inst},
    }


@router.get("/users/me", tags=T_AUTH, summary="내 프로필·역할·소속")
def me(role: str = "CENTRAL", institutionId: str | None = None):
    return {"id": "u_demo", "role": role, "institutionId": institutionId}


# ===== 마스터 =====
@router.get("/institutions", tags=T_MASTER, summary="기관 목록")
def institutions():
    return {"items": D.INSTITUTIONS, "totalElements": len(D.INSTITUTIONS)}


@router.get("/item-groups", tags=T_MASTER, summary="품목군 목록(+위험레벨)")
def item_groups():
    risk = {r["itemGroupId"]: r for r in D.SUPPLY_RISK}
    out = []
    for g in D.ITEM_GROUPS:
        r = risk.get(g["itemGroupId"], {})
        out.append({**g, "riskLevel": r.get("level", "NORMAL"), "riskScore": r.get("riskScore", 0)})
    return {"items": out, "totalElements": len(out)}


@router.get("/standard-items", tags=T_MASTER, summary="표준품목 마스터 검색")
def standard_items(q: str | None = None, group: str | None = None):
    items = D.STANDARD_ITEMS
    if q:
        items = [i for i in items if q.lower() in i["standardName"].lower() or q.upper() in i["standardCode"]]
    if group:
        items = [i for i in items if i["itemGroupId"] == group]
    return {"items": items, "totalElements": len(items)}


# ===== 데이터 인테이크 =====
@router.get("/imports", tags=T_INTAKE, summary="적재 배치 목록")
def imports(status: str | None = None):
    items = D.IMPORTS
    if status:
        items = [b for b in items if b["status"] == status]
    return {"items": items, "totalElements": len(items)}


# ===== 모듈 A — 물품 표준화 =====
@router.get("/standardization/queue", tags=T_A, summary="표준화 검수 대기 큐")
def std_queue(status: str | None = None):
    items = D.STD_QUEUE
    if status:
        items = [x for x in items if x["status"] == status]
    return {"items": items, "totalElements": len(items)}


# ===== 모듈 B — 수요 예측 =====
@router.get("/forecasts", tags=T_B, summary="수요 예측 목록")
def forecasts(institution: str | None = None):
    items = list(D.FORECASTS.values())
    if institution:
        items = [f for f in items if f["institutionId"] == institution]
    return {"items": items, "totalElements": len(items)}


@router.get("/forecasts/{institution_id}/{standard_code}", tags=T_B, summary="단일 수요 분포(mean+분위수)")
def forecast_one(institution_id: str, standard_code: str):
    f = D.FORECASTS.get((institution_id, standard_code))
    if not f:
        raise HTTPException(404, "forecast not found")
    return f


# ===== 모듈 C — 공급위험 경보 =====
@router.get("/supply-risk", tags=T_C, summary="품목군 공급위험 현황")
def supply_risk(level: str | None = None):
    items = D.SUPPLY_RISK
    if level:
        items = [r for r in items if r["level"] == level]
    name = {g["itemGroupId"]: g["name"] for g in D.ITEM_GROUPS}
    items = [{**r, "itemGroupName": name.get(r["itemGroupId"], r["itemGroupId"])} for r in items]
    return {"items": items, "totalElements": len(items)}


@router.get("/supply-risk/{item_group_id}", tags=T_C, summary="품목군 위험 상세(근거 포함)")
def supply_risk_one(item_group_id: str):
    r = D.RISK_BY_GROUP.get(item_group_id)
    if not r:
        raise HTTPException(404, "item group risk not found")
    return r


# ===== 모듈 D — 적정재고 / 발주 / 재배치 =====
@router.get("/inventory-policy", tags=T_D, summary="SS/ROP·재고 현황 목록")
def inventory_policy(institution: str | None = None, status: str | None = None):
    rows = D.INVENTORY
    if institution:
        rows = [r for r in rows if r["institutionId"] == institution]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return {"items": rows, "totalElements": len(rows)}


@router.get("/inventory-policy/{institution_id}/{standard_code}", tags=T_D, summary="단일 SS/ROP·근거·민감도")
def inventory_policy_one(institution_id: str, standard_code: str):
    for r in D.INVENTORY:
        if r["institutionId"] == institution_id and r["standardCode"] == standard_code:
            return r
    raise HTTPException(404, "policy not found")


@router.get("/order-recommendations", tags=T_D, summary="발주 권고(수량·시점)")
def order_recommendations(institution: str | None = None):
    rows = [r for r in D.INVENTORY if r["orderRecommendation"] > 0]
    if institution:
        rows = [r for r in rows if r["institutionId"] == institution]
    rows = sorted(rows, key=lambda r: r["orderRecommendation"], reverse=True)
    out = [{"institutionId": r["institutionId"], "institutionName": r["institutionName"], "standardCode": r["standardCode"],
            "standardName": r["standardName"], "available": r["available"], "ROP": r["ROP"], "target": r["target"],
            "recommendedQty": r["orderRecommendation"], "uom": r["uom"], "supplyRiskLevel": r["supplyRiskLevel"],
            "status": r["status"]} for r in rows]
    return {"items": out, "totalElements": len(out)}


@router.get("/relocations", tags=T_D, summary="재배치 제안 목록")
def relocations():
    nm = {i["institutionId"]: i["institutionName"] for i in D.INSTITUTIONS}
    out = [{**r, "fromName": nm.get(r["fromInstitution"]), "toName": nm.get(r["toInstitution"]),
            "standardName": D.ITEM_BY_CODE.get(r["standardCode"], {}).get("standardName", r["standardCode"])}
           for r in D.RELOCATIONS]
    return {"items": out, "totalElements": len(out)}


# ===== 알림 =====
@router.get("/alerts", tags=T_ALERT, summary="알림 목록")
def alerts(severity: str | None = None, type: str | None = None, resolved: bool | None = None, institution: str | None = None):
    rows = D.ALERTS
    if severity:
        rows = [a for a in rows if a["severity"] == severity]
    if type:
        rows = [a for a in rows if a["alertType"] == type]
    if resolved is not None:
        rows = [a for a in rows if (a["resolvedAt"] is not None) == resolved]
    if institution:
        rows = [a for a in rows if a.get("institutionId") == institution]
    nm = {i["institutionId"]: i["institutionName"] for i in D.INSTITUTIONS}
    rows = [{**a, "institutionName": nm.get(a.get("institutionId")) if a.get("institutionId") else None} for a in rows]
    return {"items": rows, "totalElements": len(rows)}


@router.get("/alerts/{alert_id}", tags=T_ALERT, summary="알림 상세(근거 포함)")
def alert_one(alert_id: str):
    for a in D.ALERTS:
        if a["alertId"] == alert_id:
            return a
    raise HTTPException(404, "alert not found")


# ===== 외부지표 =====
@router.get("/external-indicators", tags=T_EXT, summary="외부지표 시계열")
def external_indicators():
    return {"items": D.EXTERNAL_INDICATORS, "totalElements": len(D.EXTERNAL_INDICATORS)}


# ===== 대시보드 =====
@router.get("/dashboard/central", tags=T_DASH, summary="중앙 뷰 대시보드")
def dashboard_central():
    open_alerts = [a for a in D.ALERTS if a["resolvedAt"] is None]
    sev = {}
    for a in open_alerts:
        sev[a["severity"]] = sev.get(a["severity"], 0) + 1
    shortage = {}
    for r in D.INVENTORY:
        if r["status"] in ("BELOW_ROP", "CRITICAL"):
            shortage[r["institutionId"]] = shortage.get(r["institutionId"], 0) + 1
    nm = {i["institutionId"]: i["institutionName"] for i in D.INSTITUTIONS}
    top_shortage = sorted(
        [{"institutionId": k, "institutionName": nm.get(k), "shortageItems": v} for k, v in shortage.items()],
        key=lambda x: x["shortageItems"], reverse=True)
    name = {g["itemGroupId"]: g["name"] for g in D.ITEM_GROUPS}
    risk_rank = sorted(
        [{"itemGroupId": r["itemGroupId"], "itemGroupName": name.get(r["itemGroupId"]), "riskScore": r["riskScore"], "level": r["level"]}
         for r in D.SUPPLY_RISK], key=lambda x: x["riskScore"], reverse=True)
    return {
        "asOf": D.TODAY,
        "summary": {
            "institutions": len(D.INSTITUTIONS),
            "standardItems": len(D.STANDARD_ITEMS),
            "itemGroups": len(D.ITEM_GROUPS),
            "openAlerts": len(open_alerts),
            "totalOnHand": sum(r["onHand"] for r in D.INVENTORY),
            "belowRopItems": sum(1 for r in D.INVENTORY if r["status"] in ("BELOW_ROP", "CRITICAL")),
            "criticalRiskGroups": sum(1 for r in D.SUPPLY_RISK if r["level"] == "CRITICAL"),
        },
        "alertsBySeverity": sev,
        "supplyRiskRanking": risk_rank,
        "topShortageInstitutions": top_shortage,
        "relocations": _relocations_enriched(),
    }


def _relocations_enriched():
    nm = {i["institutionId"]: i["institutionName"] for i in D.INSTITUTIONS}
    return [{**r, "fromName": nm.get(r["fromInstitution"]), "toName": nm.get(r["toInstitution"]),
             "standardName": D.ITEM_BY_CODE.get(r["standardCode"], {}).get("standardName", r["standardCode"])}
            for r in D.RELOCATIONS]


@router.get("/dashboard/institution/{institution_id}", tags=T_DASH, summary="기관 뷰 대시보드")
def dashboard_institution(institution_id: str):
    inst = D.INST_BY_ID.get(institution_id)
    if not inst:
        raise HTTPException(404, "institution not found")
    inv = [r for r in D.INVENTORY if r["institutionId"] == institution_id]
    al = [a for a in D.ALERTS if a.get("institutionId") == institution_id]
    return {
        "asOf": D.TODAY,
        "institution": inst,
        "summary": {
            "trackedItems": len(inv),
            "belowRop": sum(1 for r in inv if r["status"] in ("BELOW_ROP", "CRITICAL")),
            "orderNeeded": sum(1 for r in inv if r["orderRecommendation"] > 0),
            "openAlerts": sum(1 for a in al if a["resolvedAt"] is None),
        },
        "inventory": inv,
        "alerts": al,
    }
