"""WeP-Stock — 전국 보건기관 의료물품 통합 재고관리 API (데모 구현).

기관(전국 실데이터)·재고·알림은 Neon Postgres(db/queries.py)에서 조회한다.
예측(B)/공급위험(C)/외부지표/인테이크/표준화검수/재배치는 아직 실 파이프라인이
없어 시드 데이터(wep_data.py)를 그대로 쓴다. 엔드포인트는 명세 모듈별 태그로
그룹화된다.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from . import wep_data as D
from auth.deps import get_current_user, require_role
from auth.security import ACCESS_TOKEN_EXPIRE_SECONDS, create_access_token, verify_password
from db import queries as DB

# 중앙(CENTRAL) 전용 — 전국 집계/마스터/모듈 A·B·C 데이터. INSTITUTION 계정은 자기
# 기관 범위(아래 알림/기관 뷰 대시보드) 밖의 전국 데이터를 볼 권한이 없다.
_central_only = Depends(require_role("CENTRAL"))

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


# ===== 인증 / 사용자 (JWT, RBAC) =====
class LoginBody(BaseModel):
    email: str
    password: str


@router.post("/auth/login", tags=T_AUTH, summary="로그인")
def login(body: LoginBody):
    user = DB.get_user_by_email(body.email)
    if not user or not verify_password(body.password, user["passwordHash"]):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")
    token = create_access_token(user)
    return {
        "accessToken": token,
        "tokenType": "bearer",
        "expiresIn": ACCESS_TOKEN_EXPIRE_SECONDS,
        "user": {k: v for k, v in user.items() if k != "passwordHash"},
    }


@router.get("/users/me", tags=T_AUTH, summary="내 프로필·역할·소속")
def me(current_user: dict = Depends(get_current_user)):
    return current_user


# ===== 마스터 (기관: Postgres, 실데이터 3,598곳) =====
@router.get("/institutions", tags=T_MASTER, summary="기관 목록(전국, 필터·페이지)")
def institutions(sido: str | None = None, sigungu: str | None = None, category: str | None = None,
                 q: str | None = None, page: int = 1, size: int = 50, _admin: dict = _central_only):
    items = DB.list_institutions(category=category, sido=sido, sigungu=sigungu, q=q)
    total = len(items)
    start = (page - 1) * size
    return {"items": items[start:start + size], "page": page, "size": size,
            "totalElements": total, "totalPages": (total + size - 1) // size}


# ===== 지역·유형 탐색 (이슈 #8: 지역별·기관유형별 재고 조회) =====
@router.get("/facility-categories", tags=T_MASTER, summary="기관유형 분류(보건소/보건지소/보건진료소)+개수")
def facility_categories(_admin: dict = _central_only):
    return {"items": DB.categories()}


@router.get("/facility-regions", tags=T_MASTER, summary="시도(또는 시군구) 목록+개수")
def facility_regions(category: str | None = None, sido: str | None = None, _admin: dict = _central_only):
    return DB.regions(category=category, sido=sido)


@router.get("/facilities", tags=T_MASTER, summary="기관 목록+상태요약(지역·유형 필터)")
def facilities(category: str | None = None, sido: str | None = None, sigungu: str | None = None,
               q: str | None = None, limit: int = Query(300, le=500), _admin: dict = _central_only):
    return DB.facilities(category=category, sido=sido, sigungu=sigungu, q=q, limit=limit)


@router.get("/facilities/{institution_id}", tags=["대시보드"], summary="기관 상세+재고 현황")
def facility_detail(institution_id: str, _admin: dict = _central_only):
    d = DB.facility_detail(institution_id)
    if not d:
        raise HTTPException(404, "institution not found")
    return d


@router.get("/item-groups", tags=T_MASTER, summary="품목군 목록(실데이터, SSIS 물품 입출고 이력 기반)")
def item_groups(_admin: dict = _central_only):
    # riskLevel/riskScore 는 실제 품목군별 공급위험 데이터가 없어 NORMAL/0 고정
    # (모듈 C 공급위험은 별도 시드(D.SUPPLY_RISK)로 독립 운영 — routers/wep_data.py 참고)
    out = [{**g, "riskLevel": "NORMAL", "riskScore": 0} for g in DB.item_groups()]
    return {"items": out, "totalElements": len(out)}


@router.get("/standard-items", tags=T_MASTER, summary="표준품목 마스터 검색(실데이터, 17,148종)")
def standard_items(q: str | None = None, group: str | None = None, _admin: dict = _central_only):
    items = DB.standard_items(q=q, group=group)
    return {"items": items, "totalElements": len(items)}


# ===== 데이터 인테이크 =====
@router.get("/imports", tags=T_INTAKE, summary="적재 배치 목록")
def imports(status: str | None = None, _admin: dict = _central_only):
    items = D.IMPORTS
    if status:
        items = [b for b in items if b["status"] == status]
    return {"items": items, "totalElements": len(items)}


# ===== 모듈 A — 물품 표준화 =====
@router.get("/standardization/queue", tags=T_A, summary="표준화 검수 대기 큐")
def std_queue(status: str | None = None, _admin: dict = _central_only):
    items = D.STD_QUEUE
    if status:
        items = [x for x in items if x["status"] == status]
    return {"items": items, "totalElements": len(items)}


# ===== 모듈 B — 수요 예측 =====
@router.get("/forecasts", tags=T_B, summary="수요 예측 목록")
def forecasts(institution: str | None = None, _admin: dict = _central_only):
    items = list(D.FORECASTS.values())
    if institution:
        items = [f for f in items if f["institutionId"] == institution]
    return {"items": items, "totalElements": len(items)}


@router.get("/forecasts/{institution_id}/{standard_code}", tags=T_B, summary="단일 수요 분포(mean+분위수)")
def forecast_one(institution_id: str, standard_code: str, _admin: dict = _central_only):
    f = D.FORECASTS.get((institution_id, standard_code))
    if not f:
        raise HTTPException(404, "forecast not found")
    return f


# ===== 모듈 C — 공급위험 경보 =====
@router.get("/supply-risk", tags=T_C, summary="품목군 공급위험 현황")
def supply_risk(level: str | None = None, _admin: dict = _central_only):
    items = D.SUPPLY_RISK
    if level:
        items = [r for r in items if r["level"] == level]
    name = {g["itemGroupId"]: g["name"] for g in D.ITEM_GROUPS}
    items = [{**r, "itemGroupName": name.get(r["itemGroupId"], r["itemGroupId"])} for r in items]
    return {"items": items, "totalElements": len(items)}


@router.get("/supply-risk/{item_group_id}", tags=T_C, summary="품목군 위험 상세(근거 포함)")
def supply_risk_one(item_group_id: str, _admin: dict = _central_only):
    r = D.RISK_BY_GROUP.get(item_group_id)
    if not r:
        raise HTTPException(404, "item group risk not found")
    return r


# ===== 모듈 D — 적정재고 / 발주 / 재배치 (Postgres) =====
@router.get("/inventory-policy", tags=T_D, summary="SS/ROP·재고 현황 목록(전국, 시급도순)")
def inventory_policy(institution: str | None = None, status: str | None = None, _admin: dict = _central_only):
    rows = DB.inventory_policy_rows(institution=institution, status=status)
    return {"items": rows, "totalElements": len(rows)}


@router.get("/inventory-policy/{institution_id}/{standard_code}", tags=T_D, summary="단일 SS/ROP·근거")
def inventory_policy_one(institution_id: str, standard_code: str, _admin: dict = _central_only):
    rows = DB.inventory_policy_rows(institution=institution_id)
    for r in rows:
        if r["standardCode"] == standard_code:
            return {**r, "assumedLeadTime": True}
    raise HTTPException(404, "policy not found")


@router.get("/order-recommendations", tags=T_D, summary="발주 권고(수량·시점)")
def order_recommendations(institution: str | None = None, _admin: dict = _central_only):
    rows = DB.order_recommendations(institution=institution)
    return {"items": rows, "totalElements": len(rows)}


@router.get("/relocations", tags=T_D, summary="재배치 제안 목록")
def relocations(_admin: dict = _central_only):
    nm = {i["institutionId"]: i["institutionName"] for i in D.INSTITUTIONS}
    out = [{**r, "fromName": nm.get(r["fromInstitution"]), "toName": nm.get(r["toInstitution"]),
            "standardName": D.ITEM_BY_CODE.get(r["standardCode"], {}).get("standardName", r["standardCode"])}
           for r in D.RELOCATIONS]
    return {"items": out, "totalElements": len(out)}


# ===== 알림 (Postgres) — INSTITUTION 은 자기 기관 알림만 =====
@router.get("/alerts", tags=T_ALERT, summary="알림 목록")
def alerts(severity: str | None = None, type: str | None = None, resolved: bool | None = None,
           institution: str | None = None, current_user: dict = Depends(require_role("CENTRAL", "INSTITUTION"))):
    if current_user["role"] == "INSTITUTION":
        institution = current_user["institutionId"]
    rows = DB.alerts_list(severity=severity, alert_type=type, resolved=resolved, institution=institution)
    return {"items": rows, "totalElements": len(rows)}


@router.get("/alerts/{alert_id}", tags=T_ALERT, summary="알림 상세(근거 포함)")
def alert_one(alert_id: str, current_user: dict = Depends(require_role("CENTRAL", "INSTITUTION"))):
    a = DB.alert_one(alert_id)
    if not a:
        raise HTTPException(404, "alert not found")
    if current_user["role"] == "INSTITUTION" and a.get("institutionId") != current_user["institutionId"]:
        raise HTTPException(403, "권한이 없습니다.")
    return a


# ===== 외부지표 =====
@router.get("/external-indicators", tags=T_EXT, summary="외부지표 시계열")
def external_indicators(_admin: dict = _central_only):
    return {"items": D.EXTERNAL_INDICATORS, "totalElements": len(D.EXTERNAL_INDICATORS)}


# ===== 대시보드 (Postgres 집계) =====
@router.get("/dashboard/central", tags=T_DASH, summary="중앙 뷰 대시보드")
def dashboard_central(_admin: dict = _central_only):
    open_alerts = DB.alerts_list(resolved=False)
    sev = {}
    for a in open_alerts:
        sev[a["severity"]] = sev.get(a["severity"], 0) + 1
    core = DB.dashboard_central_summary()
    top_shortage = DB.top_shortage_institutions(8)
    name = {g["itemGroupId"]: g["name"] for g in D.ITEM_GROUPS}
    risk_rank = sorted(
        [{"itemGroupId": r["itemGroupId"], "itemGroupName": name.get(r["itemGroupId"]), "riskScore": r["riskScore"], "level": r["level"]}
         for r in D.SUPPLY_RISK], key=lambda x: x["riskScore"], reverse=True)
    return {
        "asOf": D.TODAY,
        "summary": {
            "institutions": core["institutions"],
            "standardItems": core["standardItems"],
            "itemGroups": core["itemGroups"],
            "openAlerts": len(open_alerts),
            "totalOnHand": core["totalOnHand"],
            "belowRopItems": core["belowRopItems"],
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
def dashboard_institution(institution_id: str, current_user: dict = Depends(require_role("CENTRAL", "INSTITUTION"))):
    if current_user["role"] == "INSTITUTION" and institution_id != current_user["institutionId"]:
        raise HTTPException(403, "권한이 없습니다.")
    d = DB.dashboard_institution(institution_id)
    if not d:
        raise HTTPException(404, "institution not found")
    return {"asOf": D.TODAY, **d}
