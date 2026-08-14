"""Neon Postgres 읽기 쿼리 레이어 — 기관/재고/알림 (핵심 범위).

REST(routers/wep_stock.py)·GraphQL(routers/graphql_schema.py) 이 공유한다.
반환 딕셔너리 키는 기존 REST/GraphQL 계약과 동일한 camelCase 를 유지한다
(SS/ROP 는 기존 관례대로 대문자 유지).

예측(B)/공급위험(C)/외부지표/인테이크/표준화검수/재배치는 이번 범위 밖 —
routers/wep_data.py 의 시드 데이터를 그대로 쓴다.
"""
from .connection import get_conn


def _inst_row(r: dict) -> dict:
    return {
        "id": r["id"], "name": r["name"], "type": r["type"], "category": r["category"],
        "sido": r["sido"], "sigungu": r["sigungu"], "island": r["island"],
    }


# 리드타임 산정 근거 (2026-08-14 교체).
#
# 종전에는 `stockout_duration_p25`(재고소진기간 p25)를 조달 소요일의 대용으로
# 썼다. 그 값은 검증된 적이 없다 — "재고가 0 이던 기간" 에는 발주를 안 한 기간도
# 섞이고, 실제 발주-입고 기록이 아니다.
#
# 지금은 **조달청 납품요구 실측** 을 쓴다. 24개월 전수 30,815건의 계약 납기다.
#
#     p50 30   p60 30   p70 30   p75 30   p80 31   p90 60   p95 94
#
# 위험등급으로 분위수를 고른다. 절대 점수가 아니라 등급을 쓰는 이유는 점수의
# 절대 척도가 신호 결합 방식에 따라 임의로 정해지기 때문이다(ai#20 결함 O).
LEAD_TIME_METHOD = "contract_lead_time_quantile"
LEAD_TIME_BASIS_SAMPLES = 30815
LEAD_TIME_BASIS_MONTHS = 24
# 등급 → (분위수, 일수). apply_contract_lead_time.py 와 같은 값이어야 한다.
LEAD_TIME_BY_LEVEL = {
    "NORMAL": (50, 30.0),
    "CAUTION": (75, 30.0),
    "WARNING": (90, 60.0),
    "CRITICAL": (95, 94.0),
}
# 정기검토 주기 (ai#54). 보호기간은 R + L 이다.
REVIEW_PERIOD_DAYS = 30.0


def _lead_time_provenance(r: dict) -> dict:
    """리드타임이 어디서 나온 값인지 화면이 설명할 수 있게 만든다.

    숫자만 주면 "왜 30일인가 / 왜 60일인가" 를 알 수 없다. 어느 분위수를 썼고
    그 분위수가 무슨 표본에서 나왔는지까지 같이 내린다.
    """
    level = r.get("supply_risk_level") or "NORMAL"
    quantile, expected = LEAD_TIME_BY_LEVEL.get(level, LEAD_TIME_BY_LEVEL["NORMAL"])
    value = r.get("lead_time_used")
    # DB 값이 정책과 어긋나면 화면 설명이 거짓이 된다. 그 사실을 숨기지 않는다.
    consistent = value is not None and abs(float(value) - expected) < 1e-9
    return {
        "leadTimeSource": "contract_quantile" if consistent else "stale",
        "leadTimeMethod": LEAD_TIME_METHOD,
        "leadTimeQuantile": quantile,
        "leadTimeBasisSamples": LEAD_TIME_BASIS_SAMPLES,
        "leadTimeBasisMonths": LEAD_TIME_BASIS_MONTHS,
        "reviewPeriodDays": REVIEW_PERIOD_DAYS,
        "protectionPeriodDays": (
            REVIEW_PERIOD_DAYS + float(value) if value is not None else None
        ),
    }


def _inv_row(r: dict) -> dict:
    return {
        "standardCode": r["standard_code"], "standardName": r["standard_name"],
        "itemGroupId": r["item_group_id"], "criticality": r["criticality"], "uom": r["uom"],
        "onHand": r["on_hand"], "available": r["available"], "mu": r["mu"], "sigma": r["sigma"],
        "leadTimeUsed": r["lead_time_used"], "zUsed": r["z_used"], "SS": r["ss"], "ROP": r["rop"],
        # 리드타임이 **어디서 나온 값인지**. 숫자만 주면 화면이 "왜 30일인가 /
        # 왜 60일인가" 를 설명할 수 없다.
        #
        #   방법   조달청 납품요구 계약 납기 분위수 (24개월 전수 30,815건)
        #   선택   위험등급 → 분위수   NORMAL p50 / CAUTION p75
        #                             WARNING p90 / CRITICAL p95
        **_lead_time_provenance(r),
        "target": r["target"], "orderRecommendation": r["order_recommendation"],
        # NULL = 권고량 산출 불가(사유는 orderSuppressReason). 0 = 발주 대상 아님. 둘을 구분해야 한다.
        "orderSuppressReason": r.get("order_suppress_reason"),
        "rawOrderRecommendation": r.get("raw_order_recommendation"),
        "muIsFloored": r.get("mu_is_floored"),
        "sigmaIsFloored": r.get("sigma_is_floored"),
        "supplyRiskLevel": r["supply_risk_level"], "status": r["status"],
        # AI 예측 산출물 (ai#24/#25, v5 정본). NULL 가능 — 미적재 기관/품목.
        "muForecast": r.get("mu_forecast"),        # 소진예측용 일수요율(직전3개월 roll3). 백테스트 WAPE 42.6% (static 49.9%보다 우위). 최근무활동이면 NULL→muCorrected 폴백
        "muCorrected": r.get("mu_corrected"),      # 절단보정 일평균 수요(재고없어 못판 수요 복원). SS/ROP 안전버퍼용
        "demandClass": r.get("demand_class"),      # 재고상태: DORMANT/CENSORED/ACTIVE
        "demandPattern": r.get("demand_pattern"),  # 수요패턴(Syntetos-Boylan): smooth/intermittent/erratic/lumpy
        # family(동일 품목군) 집계 — 물품코드 분산 오탐 제거용 (ai#33). 개별 status 는 그대로 두고 병기.
        "itemFamilyId": r.get("item_family_id"),      # 기관 내 동일 품목군 식별자
        "familyAvailable": r.get("family_available"),  # 기관 내 같은 family 합계 가용재고
        "familyCodes": r.get("family_codes"),          # 그 family 가 쪼개진 물품코드 수(혈당스틱 최대 52)
        "familyStatus": r.get("family_status"),        # family 집계 기준 상태. CRITICAL 은 family 합계도 0일 때만
        # 재고0 원인 (ai#32): NOT_OPERATED 미운영 / DATA_MISSING 재고기록누락 / TRUE_STOCKOUT 실결품
        "zeroStockReason": r.get("zero_stock_reason"),
        "isMedical": r.get("is_medical"),          # 의료물품 여부(false=판촉·홍보물, 예측대상 아님)
    }


def _badge(critical: int, below_rop: int, watch: int) -> dict:
    if critical:
        return {"level": "CRITICAL", "label": "긴급", "count": critical}
    if below_rop:
        return {"level": "WARN", "label": "주의", "count": below_rop}
    if watch:
        return {"level": "WATCH", "label": "관찰", "count": watch}
    return {"level": "OK", "label": "정상", "count": 0}


def categories() -> list:
    order = ["보건소", "보건지소", "보건진료소"]
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT category, count(*) AS n FROM institutions GROUP BY category")
        cnt = {r["category"]: r["n"] for r in cur.fetchall()}
    return [{"category": c, "count": cnt.get(c, 0)} for c in order if cnt.get(c)]


def _where(category=None, sido=None, sigungu=None, q=None):
    clauses, params = [], []
    if category:
        clauses.append("category = %s"); params.append(category)
    if sido:
        clauses.append("sido = %s"); params.append(sido)
    if sigungu:
        clauses.append("sigungu = %s"); params.append(sigungu)
    if q:
        clauses.append("name ILIKE %s"); params.append(f"%{q}%")
    sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return sql, params


def list_institutions(category=None, sido=None, sigungu=None, q=None) -> list:
    where, params = _where(category, sido, sigungu, q)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT * FROM institutions{where} ORDER BY name", params)
        return [_inst_row(r) for r in cur.fetchall()]


def get_institution(institution_id: str):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM institutions WHERE id = %s", (institution_id,))
        r = cur.fetchone()
        return _inst_row(r) if r else None


def _user_row(r: dict) -> dict:
    return {
        "id": r["id"], "email": r["email"], "passwordHash": r["password_hash"],
        "name": r["name"], "role": r["role"], "institutionId": r["institution_id"],
        # 미이행(ALTER 안 된) DB 도 로그인 가능하도록 컬럼 부재 시 활성으로 간주.
        "isActive": r.get("is_active", True),
    }


def get_user_by_email(email: str):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        r = cur.fetchone()
        return _user_row(r) if r else None


# ===== 사용자 관리 (관리자 콘솔용, CENTRAL 전용, 이슈 #25) =====
# 아래 함수들의 반환값은 비밀번호 해시(password_hash)를 절대 포함하지 않는다.
def _user_public_row(r: dict) -> dict:
    """계정의 공개 표현(목록/상세용) — passwordHash 제외, 소속기관명·생성시각 포함."""
    return {
        "id": r["id"], "email": r["email"], "name": r["name"], "role": r["role"],
        "institutionId": r["institution_id"], "institutionName": r.get("institution_name"),
        "isActive": r.get("is_active", True),
        "createdAt": r["created_at"].isoformat() if r.get("created_at") else None,
    }


_USER_PUBLIC_SELECT = """
    SELECT u.id, u.email, u.name, u.role, u.institution_id,
           i.name AS institution_name, u.is_active, u.created_at
    FROM users u LEFT JOIN institutions i ON i.id = u.institution_id
"""


def list_users() -> list:
    """계정 목록(비밀번호 해시 제외). CENTRAL 전용 관리자 콘솔용."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(_USER_PUBLIC_SELECT + " ORDER BY u.created_at, u.id")
        return [_user_public_row(r) for r in cur.fetchall()]


def get_user_public(user_id: str):
    """단일 계정(비밀번호 해시 제외). 없으면 None."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(_USER_PUBLIC_SELECT + " WHERE u.id = %s", (user_id,))
        r = cur.fetchone()
        return _user_public_row(r) if r else None


def create_user(user_id, email, password_hash, name, role, institution_id=None) -> dict:
    """신규 계정 생성. password_hash 는 이미 해싱된 값을 받는다(auth.security.hash_password)."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (id, email, password_hash, name, role, institution_id) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (user_id, email, password_hash, name, role, institution_id),
        )
    return get_user_public(user_id)


def count_active_central_users() -> int:
    """활성 CENTRAL 계정 수.

    마지막 관리자의 역할을 내리거나 비활성화하면 관리자 콘솔에 아무도 못 들어가고
    되돌릴 방법이 없다. 그걸 막기 위한 확인용이다.
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS n FROM users "
            "WHERE role = 'CENTRAL' AND coalesce(is_active, true)"
        )
        return int(cur.fetchone()["n"])


def update_user(user_id: str, fields: dict):
    """계정 부분 수정(이름·역할·소속기관). fields 에 담긴 허용 키만 반영한다.
    대상 계정이 없으면 None 을 반환한다(호출부에서 404 처리)."""
    allowed = {"name": "name", "role": "role", "institutionId": "institution_id",
               "isActive": "is_active"}
    sets, params = [], []
    for key, col in allowed.items():
        if key in fields:
            sets.append(f"{col} = %s")
            params.append(fields[key])
    if not sets:
        return get_user_public(user_id)
    params.append(user_id)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = %s", params)
        if cur.rowcount == 0:
            return None
    return get_user_public(user_id)


def regions(category=None, sido=None) -> dict:
    where, params = _where(category=category, sido=sido)
    with get_conn() as conn, conn.cursor() as cur:
        if not sido:
            cur.execute(f"SELECT sido AS name, count(*) AS count FROM institutions{where} GROUP BY sido", params)
            return {"level": "sido", "items": [dict(r) for r in cur.fetchall()]}
        cur.execute(
            f"SELECT sigungu AS name, count(*) AS count FROM institutions{where} GROUP BY sigungu ORDER BY sigungu",
            params,
        )
        return {"level": "sigungu", "sido": sido, "items": [dict(r) for r in cur.fetchall()]}


def _summaries_for(institution_ids: list) -> dict:
    """institution_id -> summary(dict) 일괄 조회 (N+1 방지)."""
    if not institution_ids:
        return {}
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT institution_id,
                   count(*) AS tracked_items,
                   count(*) FILTER (WHERE status = 'CRITICAL') AS critical,
                   count(*) FILTER (WHERE status = 'BELOW_ROP') AS below_rop,
                   count(*) FILTER (WHERE status = 'WATCH') AS watch,
                   count(*) FILTER (WHERE order_recommendation > 0) AS order_needed
            FROM inventory
            WHERE institution_id = ANY(%s)
            GROUP BY institution_id
            """,
            (institution_ids,),
        )
        out = {}
        for r in cur.fetchall():
            out[r["institution_id"]] = {
                "trackedItems": r["tracked_items"], "critical": r["critical"], "belowRop": r["below_rop"],
                "watch": r["watch"], "orderNeeded": r["order_needed"],
                "badge": _badge(r["critical"], r["below_rop"], r["watch"]),
            }
        return out


def summary_for_institution(institution_id: str) -> dict:
    empty = {"trackedItems": 0, "critical": 0, "belowRop": 0, "watch": 0, "orderNeeded": 0, "badge": _badge(0, 0, 0)}
    return _summaries_for([institution_id]).get(institution_id, empty)


def summaries_for_many(institution_ids: list) -> dict:
    """institution_id -> summary(dict) 일괄 조회, 결과에 없는 id 는 빈 요약으로 채운다
    (GraphQL DataLoader 는 입력 키 개수만큼 결과가 필요하다)."""
    empty = {"trackedItems": 0, "critical": 0, "belowRop": 0, "watch": 0, "orderNeeded": 0, "badge": _badge(0, 0, 0)}
    found = _summaries_for(institution_ids)
    return {iid: found.get(iid, empty) for iid in institution_ids}


def facilities(category=None, sido=None, sigungu=None, q=None, limit=300) -> dict:
    all_items = list_institutions(category=category, sido=sido, sigungu=sigungu, q=q)
    total = len(all_items)
    items = all_items[:limit]
    summaries = _summaries_for([i["id"] for i in items])
    empty = {"trackedItems": 0, "critical": 0, "belowRop": 0, "watch": 0, "orderNeeded": 0, "badge": _badge(0, 0, 0)}
    out = [{**i, "summary": summaries.get(i["id"], empty)} for i in items]
    return {"items": out, "totalElements": total, "returned": len(out), "truncated": total > len(out)}


def inventory_for(institution_id: str) -> list:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT inv.standard_code, si.standard_name, si.item_group_id, si.criticality, si.uom,
                   inv.on_hand, inv.available, inv.mu, inv.sigma, inv.lead_time_used, inv.z_used,
                   inv.ss, inv.rop, inv.target, inv.order_recommendation, inv.supply_risk_level, inv.status,
                   inv.order_suppress_reason, inv.raw_order_recommendation,
                   inv.mu_is_floored, inv.sigma_is_floored, inv.lead_time_policy_capped,
                   inv.mu_corrected, inv.demand_class, inv.demand_pattern, inv.is_medical, inv.mu_forecast,
                   inv.item_family_id, inv.family_available, inv.family_codes, inv.family_status, inv.zero_stock_reason
            FROM inventory inv JOIN standard_items si ON si.standard_code = inv.standard_code
            WHERE inv.institution_id = %s
            ORDER BY si.standard_code
            """,
            (institution_id,),
        )
        return [_inv_row(r) for r in cur.fetchall()]


def inventory_for_many(institution_ids: list) -> dict:
    """institution_id -> [InventoryItem-dict, ...] 일괄 조회 (GraphQL DataLoader 배치용, N+1 방지).

    institutions { ... inventory { ... } } 처럼 목록 안에서 여러 기관에 대해
    동시에 요청되면, 기관마다 따로 조회하는 대신 이 함수로 한 번에 가져온다."""
    if not institution_ids:
        return {}
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT inv.institution_id, inv.standard_code, si.standard_name, si.item_group_id, si.criticality, si.uom,
                   inv.on_hand, inv.available, inv.mu, inv.sigma, inv.lead_time_used, inv.z_used,
                   inv.ss, inv.rop, inv.target, inv.order_recommendation, inv.supply_risk_level, inv.status,
                   inv.order_suppress_reason, inv.raw_order_recommendation,
                   inv.mu_is_floored, inv.sigma_is_floored, inv.lead_time_policy_capped,
                   inv.mu_corrected, inv.demand_class, inv.demand_pattern, inv.is_medical, inv.mu_forecast,
                   inv.item_family_id, inv.family_available, inv.family_codes, inv.family_status, inv.zero_stock_reason
            FROM inventory inv JOIN standard_items si ON si.standard_code = inv.standard_code
            WHERE inv.institution_id = ANY(%s)
            ORDER BY inv.institution_id, si.standard_code
            """,
            (institution_ids,),
        )
        rows = cur.fetchall()
    out = {iid: [] for iid in institution_ids}
    for r in rows:
        out.setdefault(r["institution_id"], []).append(_inv_row(r))
    return out


def facility_detail(institution_id: str):
    inst = get_institution(institution_id)
    if not inst:
        return None
    inv = inventory_for(institution_id)
    s = _summaries_for([institution_id]).get(
        institution_id, {"trackedItems": 0, "critical": 0, "belowRop": 0, "watch": 0, "orderNeeded": 0}
    )
    return {
        "institution": inst,
        "summary": {"trackedItems": s["trackedItems"], "belowRop": s["critical"] + s["belowRop"],
                    "critical": s["critical"], "orderNeeded": s["orderNeeded"]},
        "inventory": inv,
    }


def inventory_policy_rows(institution=None, status=None, limit=500) -> list:
    """전국 재고·SS/ROP 현황. 기관 미지정 시 가장 시급한(CRITICAL→BELOW_ROP→WATCH→OK) 상위
    `limit`건을 반환한다 — 이전엔 '보건소 14곳 샘플'로 고정돼 있던 것을 전국 실데이터
    기준 '가장 주의가 필요한 항목' 우선순위 뷰로 대체한 것."""
    clauses, params = [], []
    if institution:
        clauses.append("inv.institution_id = %s"); params.append(institution)
    if status:
        clauses.append("inv.status = %s"); params.append(status)
    where = (" AND " + " AND ".join(clauses)) if clauses else ""
    order_limit = "" if institution else " LIMIT %s"
    if not institution:
        params.append(limit)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT i.id AS institution_id, i.name AS institution_name, i.sido, i.sigungu,
                   inv.standard_code, si.standard_name, si.item_group_id, si.criticality, si.uom,
                   inv.on_hand, inv.available, inv.mu, inv.sigma, inv.lead_time_used, inv.z_used,
                   inv.ss, inv.rop, inv.target, inv.order_recommendation, inv.supply_risk_level, inv.status,
                   inv.order_suppress_reason, inv.raw_order_recommendation,
                   inv.mu_is_floored, inv.sigma_is_floored, inv.lead_time_policy_capped,
                   inv.mu_corrected, inv.demand_class, inv.demand_pattern, inv.is_medical, inv.mu_forecast,
                   inv.item_family_id, inv.family_available, inv.family_codes, inv.family_status, inv.zero_stock_reason
            FROM inventory inv
            JOIN institutions i ON i.id = inv.institution_id
            JOIN standard_items si ON si.standard_code = inv.standard_code
            WHERE 1=1{where}
            ORDER BY CASE inv.status WHEN 'CRITICAL' THEN 0 WHEN 'BELOW_ROP' THEN 1 WHEN 'WATCH' THEN 2 ELSE 3 END,
                     i.name, inv.standard_code
            {order_limit}
            """,
            params,
        )
        rows = cur.fetchall()
    return [{**_inv_row(r), "institutionId": r["institution_id"], "institutionName": r["institution_name"],
             "sido": r["sido"], "sigungu": r["sigungu"]} for r in rows]


def order_recommendations(institution=None, limit=200) -> list:
    clauses, params = ["inv.order_recommendation > 0"], []
    if institution:
        clauses.append("inv.institution_id = %s"); params.append(institution)
    where = " AND " + " AND ".join(clauses)
    params.append(limit)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT i.id AS institution_id, i.name AS institution_name,
                   inv.standard_code, si.standard_name, inv.available, inv.rop, inv.target,
                   inv.order_recommendation, si.uom, inv.supply_risk_level, inv.status,
                   -- 권고량의 근거를 같이 내린다. 숫자만 주면 화면이 "왜 이 수량인지"를
                   -- 설명할 수 없고, 담당자가 근거 없이 발주하게 된다(ai#52).
                   --   mu_is_floored          수요가 추정치인지 바닥값인지. 실측 72.42% 가 바닥값이다.
                   --   order_suppress_reason  억제 사유 (DORMANT/NOT_OPERATED/DATA_MISSING/STALE)
                   --   raw_order_recommendation 억제 전 원시 권고량
                   inv.mu_is_floored, inv.order_suppress_reason,
                   inv.raw_order_recommendation, inv.demand_class
            FROM inventory inv
            JOIN institutions i ON i.id = inv.institution_id
            JOIN standard_items si ON si.standard_code = inv.standard_code
            WHERE 1=1{where}
            ORDER BY inv.order_recommendation DESC
            LIMIT %s
            """,
            params,
        )
        rows = cur.fetchall()
    return [{
        "institutionId": r["institution_id"], "institutionName": r["institution_name"],
        "standardCode": r["standard_code"], "standardName": r["standard_name"], "available": r["available"],
        "ROP": r["rop"], "target": r["target"], "recommendedQty": r["order_recommendation"], "uom": r["uom"],
        "supplyRiskLevel": r["supply_risk_level"], "status": r["status"],
        "muIsFloored": r.get("mu_is_floored"),
        "orderSuppressReason": r.get("order_suppress_reason"),
        "rawOrderRecommendation": r.get("raw_order_recommendation"),
        "demandClass": r.get("demand_class"),
    } for r in rows]


# backend#35: ai 레포 수요예측 서빙 API(/api/v1/ai/forecasts)가 아직 배포되지 않아,
# 이미 inventory 에 적재된 AI 산출물(mu_forecast/mu_corrected, ai#24/#25)을 폴백으로 소비한다.
# ai 서빙이 배포되면 이 함수 대신 프록시 호출로 교체하면 된다.
def forecasts_from_inventory(institution=None, limit=200) -> list:
    clauses, params = ["inv.mu_forecast IS NOT NULL"], []
    if institution:
        clauses.append("inv.institution_id = %s"); params.append(institution)
    where = " AND " + " AND ".join(clauses)
    params.append(limit)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT inv.institution_id, inv.standard_code, si.standard_name,
                   inv.mu, inv.sigma, inv.mu_forecast, inv.mu_corrected,
                   inv.demand_class, inv.demand_pattern
            FROM inventory inv
            JOIN standard_items si ON si.standard_code = inv.standard_code
            WHERE 1=1{where}
            ORDER BY inv.mu_forecast DESC
            LIMIT %s
            """,
            params,
        )
        rows = cur.fetchall()
    return [_forecast_row(r) for r in rows]


def forecast_one_from_inventory(institution_id: str, standard_code: str):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT inv.institution_id, inv.standard_code, si.standard_name,
                   inv.mu, inv.sigma, inv.mu_forecast, inv.mu_corrected,
                   inv.demand_class, inv.demand_pattern
            FROM inventory inv
            JOIN standard_items si ON si.standard_code = inv.standard_code
            WHERE inv.institution_id = %s AND inv.standard_code = %s
            """,
            (institution_id, standard_code),
        )
        r = cur.fetchone()
    return _forecast_row(r) if r else None


def _forecast_row(r: dict) -> dict:
    return {
        "institutionId": r["institution_id"], "standardCode": r["standard_code"],
        "standardName": r["standard_name"], "muDaily": r["mu"], "sigmaDaily": r["sigma"],
        "muForecast": r["mu_forecast"], "muCorrected": r["mu_corrected"],
        "demandClass": r["demand_class"], "demandPattern": r["demand_pattern"],
        "source": "backend-mu-forecast",
    }


# backend#35: ai 공급위험 점수 서빙 API가 아직 배포되지 않아, 이미 inventory 에 적재된
# 실제 supply_risk_level(메타코드 기반, scripts/fix_inventory_stats.py)을 품목군 단위로
# 집계해 폴백으로 제공한다. ai 서빙이 배포되면 이 함수 대신 프록시 호출로 교체하면 된다.
_RISK_RANK = {"NORMAL": 0, "CAUTION": 1, "WARNING": 2, "CRITICAL": 3}


def supply_risk_by_group() -> list:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT si.item_group_id, inv.supply_risk_level, count(*) AS n
            FROM inventory inv
            JOIN standard_items si ON si.standard_code = inv.standard_code
            GROUP BY si.item_group_id, inv.supply_risk_level
            """
        )
        rows = cur.fetchall()
    return _aggregate_group_risk(rows)


def supply_risk_group_detail(item_group_id: str):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT si.item_group_id, inv.supply_risk_level, count(*) AS n
            FROM inventory inv
            JOIN standard_items si ON si.standard_code = inv.standard_code
            WHERE si.item_group_id = %s
            GROUP BY si.item_group_id, inv.supply_risk_level
            """,
            (item_group_id,),
        )
        rows = cur.fetchall()
        if not rows:
            return None
        [group] = _aggregate_group_risk(rows)
        cur.execute(
            """
            SELECT i.id AS institution_id, i.name AS institution_name, count(*) AS n
            FROM inventory inv
            JOIN standard_items si ON si.standard_code = inv.standard_code
            JOIN institutions i ON i.id = inv.institution_id
            WHERE si.item_group_id = %s AND inv.supply_risk_level IN ('CRITICAL', 'WARNING')
            GROUP BY i.id, i.name
            ORDER BY n DESC
            LIMIT 10
            """,
            (item_group_id,),
        )
        group["topInstitutions"] = [
            {"institutionId": r["institution_id"], "institutionName": r["institution_name"], "highRiskItems": r["n"]}
            for r in cur.fetchall()
        ]
    return group


def _aggregate_group_risk(rows) -> list:
    by_group: dict = {}
    for r in rows:
        g = by_group.setdefault(r["item_group_id"], {"itemGroupId": r["item_group_id"], "levelCounts": {}, "total": 0})
        g["levelCounts"][r["supply_risk_level"]] = r["n"]
        g["total"] += r["n"]
    out = []
    for g in by_group.values():
        counts = g["levelCounts"]
        level = "NORMAL"
        for lv in ("CRITICAL", "WARNING", "CAUTION"):
            if counts.get(lv):
                level = lv
                break
        weighted = sum(_RISK_RANK[lv] * n for lv, n in counts.items())
        g["level"] = level
        g["riskScore"] = round(100 * weighted / (g["total"] * 3), 1) if g["total"] else 0
        g["source"] = "backend-supply-risk-level"
        out.append(g)
    return out


def relocation_candidates(limit=100) -> list:
    """부족(CRITICAL/BELOW_ROP) 기관과 여유(OK, available > target) 기관을 같은 표준품목
    기준으로 매칭한 재배치 제안 — 실재고(Neon Postgres) 기반. 부족분(target-available)과
    여유분(available-target) 중 작은 쪽을 제안 수량으로 삼는다.

    같은 시도(sido)를 우선 매칭하지만, 기관코드↔실명 매핑이 아직 정렬순서 임의매핑이라
    (#16) 시도 정보 자체의 신뢰도가 낮다 — 응답의 sameSidoTentative 로 명시한다.
    유효기간(로트) 데이터가 원본에 없어 FEFO(유효기간 임박 우선) 기준은 적용하지 못했다."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            WITH need AS (
                SELECT institution_id, standard_code, available, target,
                       (target - available) AS shortfall
                FROM inventory
                WHERE status IN ('CRITICAL', 'BELOW_ROP') AND target > available
            ),
            surplus AS (
                SELECT institution_id, standard_code, available, target,
                       (available - target) AS surplus_qty
                FROM inventory
                WHERE status = 'OK' AND available > target
            ),
            matched AS (
                SELECT DISTINCT ON (n.institution_id, n.standard_code)
                       n.institution_id AS to_institution, s.institution_id AS from_institution,
                       n.standard_code, n.shortfall, s.surplus_qty,
                       ni.sido AS to_sido, si2.sido AS from_sido
                FROM need n
                JOIN surplus s ON s.standard_code = n.standard_code AND s.institution_id <> n.institution_id
                JOIN institutions ni ON ni.id = n.institution_id
                JOIN institutions si2 ON si2.id = s.institution_id
                ORDER BY n.institution_id, n.standard_code,
                         (ni.sido = si2.sido) DESC, s.surplus_qty DESC
            )
            SELECT m.*, st.standard_name, st.uom
            FROM matched m
            JOIN standard_items st ON st.standard_code = m.standard_code
            ORDER BY m.shortfall DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    out = []
    for i, r in enumerate(rows, start=1):
        qty = min(r["shortfall"], r["surplus_qty"])
        same_sido = r["from_sido"] is not None and r["from_sido"] == r["to_sido"]
        out.append({
            "id": f"rl_derived_{i}",
            "fromInstitution": r["from_institution"], "toInstitution": r["to_institution"],
            "standardCode": r["standard_code"], "standardName": r["standard_name"], "uom": r["uom"],
            "suggestedQty": qty, "sameSido": same_sido, "sameSidoTentative": True,
            "reason": "같은 시도 여유 재고 매칭" if same_sido else "전국 여유 재고 매칭(권역 정보 잠정)",
            "status": "제안",
        })
    return out


# on_hand 이상치 판정 임계값. 보건소 단일 품목 재고가 1만 단위를 넘는 경우는
# 대부분 단위(UoM) 오류로 의심된다(낱개 vs 박스). 실측 1,449행(전체의 0.35%).
ONHAND_OUTLIER_THRESHOLD = 10_000


def dashboard_central_summary() -> dict:
    """중앙 대시보드 집계.

    ⚠️ totalOnHand 주의 — 화면 대표지표로 쓰지 말 것:
      단위(UoM)가 다른 품목의 수량을 그대로 합산한 값이다(캔디 '개' + 산소 'L' +
      파스 '장'을 더한 셈). 이상치를 제외해도 의미가 생기지 않는 구조적 문제다.
      게다가 실측상 상위 2행이 전체 합의 51.5%를 차지한다
      ((금연)멘톨캔디 99,999,400 · 임신축하용품 99,997,569 — 단위 오류 의심).
      중앙값 9 vs 평균 948.6 으로 왜도가 극단적이다.
      → API 호환을 위해 필드는 유지하되, 대표지표로는 stockoutItems/belowRopItems 를 쓸 것.
      데이터 품질 검토는 outlierItems 로 규모를 파악한다.
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM institutions")
        institutions_n = cur.fetchone()["n"]
        cur.execute(
            """
            SELECT sum(on_hand) AS total_on_hand,
                   count(*) FILTER (WHERE status IN ('BELOW_ROP','CRITICAL')) AS below_rop_items,
                   -- 재고 0 이라도 '판정 제외'(EXCLUDED)는 결품이 아니다 — 해당 기관이
                   -- 취급하지 않거나(NOT_OPERATED) 데이터가 누락된(DATA_MISSING) 품목이며
                   -- DGU-TeamLex/ai#38 로 status 가 분리됐다. 제외하지 않으면 실측상
                   -- 128,250 중 63,930(약 절반)이 허수로 잡힌다.
                   count(*) FILTER (WHERE on_hand = 0 AND status <> 'EXCLUDED') AS stockout_items,
                   count(*) FILTER (WHERE on_hand = 0 AND status = 'EXCLUDED') AS not_operated_items,
                   count(*) FILTER (WHERE on_hand >= %s) AS outlier_items
            FROM inventory
            """,
            (ONHAND_OUTLIER_THRESHOLD,),
        )
        agg = cur.fetchone()
        cur.execute("SELECT count(*) AS n FROM standard_items")
        standard_items_n = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM item_groups")
        item_groups_n = cur.fetchone()["n"]
    return {"institutions": institutions_n,
            # ⚠️ 단위 혼재 합계 — 대표지표 사용 금지(위 docstring 참조)
            "totalOnHand": agg["total_on_hand"] or 0,
            "belowRopItems": agg["below_rop_items"] or 0,
            "stockoutItems": agg["stockout_items"] or 0,
            # 재고 0 이지만 결품이 아닌 건(미운영·데이터누락). 화면에서 결품과 구분해 표기한다.
            "notOperatedItems": agg["not_operated_items"] or 0,
            "outlierItems": agg["outlier_items"] or 0,
            "standardItems": standard_items_n, "itemGroups": item_groups_n}


def item_groups() -> list:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT item_group_id, name FROM item_groups ORDER BY name")
        return [{"itemGroupId": r["item_group_id"], "name": r["name"]} for r in cur.fetchall()]


def standard_items(q=None, group=None, limit=500, offset=0) -> list:
    where = []
    params = []
    if q:
        where.append("(standard_name ILIKE %s OR standard_code ILIKE %s)")
        params += [f"%{q}%", f"%{q}%"]
    if group:
        where.append("item_group_id = %s")
        params.append(group)
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT standard_item_id, standard_code, standard_name, item_group_id, uom, "
            f"shelf_life_days, criticality FROM standard_items{clause} ORDER BY standard_name LIMIT %s OFFSET %s",
            params + [limit, offset],
        )
        rows = cur.fetchall()
        cur.execute(f"SELECT count(*) AS n FROM standard_items{clause}", params)
        total = cur.fetchone()["n"]
        return {
            "items": [{
                "standardItemId": r["standard_item_id"], "standardCode": r["standard_code"],
                "standardName": r["standard_name"], "itemGroupId": r["item_group_id"], "uom": r["uom"],
                "shelfLifeDays": r["shelf_life_days"], "criticality": r["criticality"],
            } for r in rows],
            "totalElements": total,
        }


def standard_items_catalog() -> list:
    """표준화 매칭용 전체 카탈로그(코드·명·품목군만, 페이지네이션 없음).

    17,148 종 규모라 매 요청 전량 스캔이 가능하다(이슈 #20 매칭 엔진).
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT standard_code, standard_name, item_group_id FROM standard_items")
        return [{"standardCode": r["standard_code"], "standardName": r["standard_name"],
                  "itemGroupId": r["item_group_id"]} for r in cur.fetchall()]


def top_shortage_institutions(n=8) -> list:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT i.id AS institution_id, i.name AS institution_name,
                   count(*) AS shortage_items
            FROM inventory inv JOIN institutions i ON i.id = inv.institution_id
            WHERE inv.status IN ('BELOW_ROP','CRITICAL')
            GROUP BY i.id, i.name
            ORDER BY shortage_items DESC
            LIMIT %s
            """,
            (n,),
        )
        return [{"institutionId": r["institution_id"], "institutionName": r["institution_name"],
                  "shortageItems": r["shortage_items"]} for r in cur.fetchall()]


def alerts_list(severity=None, alert_type=None, resolved=None, institution=None) -> list:
    clauses, params = [], []
    if severity:
        clauses.append("a.severity = %s"); params.append(severity)
    if alert_type:
        clauses.append("a.alert_type = %s"); params.append(alert_type)
    if resolved is not None:
        clauses.append("(a.resolved_at IS NOT NULL) = %s"); params.append(resolved)
    if institution:
        clauses.append("a.institution_id = %s"); params.append(institution)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT a.alert_id, a.alert_type, a.severity, a.institution_id, i.name AS institution_name,
                   a.title, a.message, a.evidence, a.generated_at, a.resolved_at
            FROM alerts a LEFT JOIN institutions i ON i.id = a.institution_id
            {where}
            ORDER BY a.generated_at DESC
            """,
            params,
        )
        rows = cur.fetchall()
    return [_alert_row(r) for r in rows]


def alert_one(alert_id: str):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.alert_id, a.alert_type, a.severity, a.institution_id, i.name AS institution_name,
                   a.title, a.message, a.evidence, a.generated_at, a.resolved_at
            FROM alerts a LEFT JOIN institutions i ON i.id = a.institution_id
            WHERE a.alert_id = %s
            """,
            (alert_id,),
        )
        r = cur.fetchone()
        return _alert_row(r) if r else None


def _alert_row(r: dict) -> dict:
    return {
        "alertId": r["alert_id"], "alertType": r["alert_type"], "severity": r["severity"],
        "institutionId": r["institution_id"], "institutionName": r["institution_name"],
        "title": r["title"], "message": r["message"], "evidence": r["evidence"],
        "generatedAt": r["generated_at"].isoformat(), "resolvedAt": r["resolved_at"].isoformat() if r["resolved_at"] else None,
    }


def import_batches(status=None) -> list:
    where = " WHERE status = %s" if status else ""
    params = [status] if status else []
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT * FROM import_batches{where} ORDER BY uploaded_at DESC",
            params,
        )
        rows = cur.fetchall()
    return [{
        "importBatchId": r["import_batch_id"], "fileName": r["file_name"], "sourceVendor": r["source_vendor"],
        "status": r["status"], "uploadedAt": r["uploaded_at"].isoformat(), "totalRows": r["total_rows"],
        "validRows": r["valid_rows"], "errorRows": r["error_rows"], "mappingRate": r["mapping_rate"],
        "periodStart": r["period_start"], "periodEnd": r["period_end"],
    } for r in rows]


def record_import_batch(import_batch_id, file_name, source_vendor=None,
                        status="RECEIVED") -> dict:
    """업로드 접수 배치를 기록한다(POST /imports, 이슈 #20).

    실제 행 파싱·표준화 매칭 전 단계라 total/valid/error 행수는 0, mapping_rate 는
    0.0 으로 남긴다. 후속 처리(매칭 엔진)가 같은 배치를 갱신하는 것을 전제로 한다.
    반환 딕셔너리는 import_batches() 와 동일한 camelCase 계약을 따른다.
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO import_batches
                (import_batch_id, file_name, source_vendor, status,
                 total_rows, valid_rows, error_rows, mapping_rate)
            VALUES (%s, %s, %s, %s, 0, 0, 0, 0.0)
            RETURNING import_batch_id, file_name, source_vendor, status,
                      uploaded_at, total_rows, valid_rows, error_rows,
                      mapping_rate, period_start, period_end
            """,
            [import_batch_id, file_name, source_vendor, status],
        )
        r = cur.fetchone()
    return {
        "importBatchId": r["import_batch_id"], "fileName": r["file_name"],
        "sourceVendor": r["source_vendor"], "status": r["status"],
        "uploadedAt": r["uploaded_at"].isoformat(), "totalRows": r["total_rows"],
        "validRows": r["valid_rows"], "errorRows": r["error_rows"],
        "mappingRate": r["mapping_rate"], "periodStart": r["period_start"],
        "periodEnd": r["period_end"],
    }


def dashboard_institution(institution_id: str):
    inst = get_institution(institution_id)
    if not inst:
        return None
    inv = inventory_for(institution_id)
    al = alerts_list(institution=institution_id)
    return {
        "institution": inst,
        "summary": {
            "trackedItems": len(inv),
            "belowRop": sum(1 for r in inv if r["status"] in ("BELOW_ROP", "CRITICAL")),
            "orderNeeded": sum(1 for r in inv if (r["orderRecommendation"] or 0) > 0),
            "openAlerts": sum(1 for a in al if a["resolvedAt"] is None),
        },
        "inventory": inv,
        "alerts": al,
    }


# ===== 재고미달 알림 온디맨드 파생 (backend#53) =====
# `alerts` 테이블은 2026-07-10 CRITICAL 일부만 1회성 시드된 낡은 스냅샷이라
# 재적재된 inventory(실재고)와 단절돼 있다. 재고미달 알림은 저장 테이블에
# 의존하지 않고 조회 시점에 inventory 에서 파생한다(정렬·기관당 상한 적용).
# alerts 테이블은 사람이 처리상태(승인/해소)를 관리하는 알림 용도로만 남긴다.
_DERIVED_SHORTAGE_STATUSES = ("CRITICAL", "BELOW_ROP")
_SEVERITY_BY_STATUS = {"CRITICAL": "CRITICAL", "BELOW_ROP": "WARNING"}

# 휴면 품목(DORMANT: 재고가 있었는데도 안 나감 = 진짜 무수요)은 재고미달 알림에서 제외한다.
# demand_class 는 ai#25 로 적재되며, 아직 NULL 이면(미적재) 모두 통과한다(IS DISTINCT FROM).
# → ai 가 demand_class 를 채우면 자동으로 사장재고 알림이 걸러진다. 미적재 상태에선 동작 불변.
_EXCLUDE_DORMANT = "inv.demand_class IS DISTINCT FROM 'DORMANT'"


def shortage_alerts_derived(institution=None, statuses=None,
                            per_institution=5, limit=200) -> list:
    """inventory 실재고에서 재고미달 알림을 조회 시점에 파생한다.

    전체 재주문점 미달은 20만 건 규모라 모두 알림화할 수 없으므로,
    기관당 시급도 상위 `per_institution` 건으로 제한한 뒤 전역 `limit` 을 적용한다.
    정렬: 상태 심각도(CRITICAL→BELOW_ROP) → 부족분(rop-available) 큰 순.
    """
    statuses = tuple(statuses) if statuses else _DERIVED_SHORTAGE_STATUSES
    clauses = ["inv.status = ANY(%s)", _EXCLUDE_DORMANT]
    params = [list(statuses)]
    if institution:
        clauses.append("inv.institution_id = %s"); params.append(institution)
    where = " AND ".join(clauses)
    params.extend([per_institution, limit])
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            WITH ranked AS (
                SELECT i.id AS institution_id, i.name AS institution_name, i.sido, i.sigungu,
                       inv.standard_code, si.standard_name, si.item_group_id, si.criticality, si.uom,
                       inv.on_hand, inv.available, inv.ss, inv.rop, inv.target,
                       inv.order_recommendation, inv.supply_risk_level, inv.status,
                       (inv.rop - inv.available) AS shortage_gap,
                       ROW_NUMBER() OVER (
                           PARTITION BY inv.institution_id
                           ORDER BY CASE inv.status WHEN 'CRITICAL' THEN 0 WHEN 'BELOW_ROP' THEN 1 ELSE 2 END,
                                    (inv.rop - inv.available) DESC, inv.standard_code
                       ) AS rn
                FROM inventory inv
                JOIN institutions i ON i.id = inv.institution_id
                JOIN standard_items si ON si.standard_code = inv.standard_code
                WHERE {where}
            )
            SELECT * FROM ranked
            WHERE rn <= %s
            ORDER BY CASE status WHEN 'CRITICAL' THEN 0 WHEN 'BELOW_ROP' THEN 1 ELSE 2 END,
                     shortage_gap DESC, institution_name, standard_code
            LIMIT %s
            """,
            params,
        )
        rows = cur.fetchall()
    return [_derived_alert_row(r) for r in rows]


def _derived_alert_row(r: dict) -> dict:
    status = r["status"]
    return {
        # 저장 테이블 알림이 아니라 파생 알림임을 alertId 접두사로 구분한다.
        "alertId": f"derived:{r['institution_id']}:{r['standard_code']}",
        "alertType": "재고미달",
        "severity": _SEVERITY_BY_STATUS.get(status, "WARNING"),
        "institutionId": r["institution_id"], "institutionName": r["institution_name"],
        "sido": r["sido"], "sigungu": r["sigungu"],
        "standardCode": r["standard_code"], "standardName": r["standard_name"],
        "itemGroupId": r["item_group_id"], "criticality": r["criticality"], "uom": r["uom"],
        "title": f"{r['standard_name']} 재주문점 미달",
        "message": (
            f"가용재고 {r['available']} / 재주문점(ROP) {r['rop']} — "
            f"부족분 {r['shortage_gap']} (상태 {status})"
        ),
        "evidence": {
            "onHand": r["on_hand"], "available": r["available"], "SS": r["ss"],
            "ROP": r["rop"], "target": r["target"], "shortageGap": r["shortage_gap"],
            "orderRecommendation": r["order_recommendation"],
            "supplyRiskLevel": r["supply_risk_level"], "status": status,
        },
        # 파생 알림은 저장·해소 이력이 없다(사람이 관리하는 alerts 테이블과 구분).
        "derived": True, "resolvedAt": None,
    }


def shortage_alerts_summary(institution=None, statuses=None) -> dict:
    """재고미달 파생 알림의 실제 규모 집계(상태별 건수·기관수·품목수).

    대시보드 openAlerts 가 낡은 시드 30건을 대표값으로 쓰던 문제(backend#53)를
    바로잡기 위해, 실재고 기준 부족 규모를 그대로 노출한다.

    ※ 대시보드 대표 카운트(belowRopItems 등)는 이미 dashboard_central_summary(#51)가
      제공하므로, 이 엔드포인트는 그 값과 겹치는 총계용이 아니라 **상태별 기관수·품목수
      분해**가 필요할 때 쓴다. DORMANT(사장재고)는 위 _EXCLUDE_DORMANT 로 제외되므로,
      demand_class 적재 후에는 이 집계가 belowRopItems 보다 작아질 수 있다(그게 정상).
    """
    statuses = tuple(statuses) if statuses else _DERIVED_SHORTAGE_STATUSES
    clauses = ["inv.status = ANY(%s)", _EXCLUDE_DORMANT]
    params = [list(statuses)]
    if institution:
        clauses.append("inv.institution_id = %s"); params.append(institution)
    where = " AND ".join(clauses)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT inv.status,
                   count(*) AS n,
                   count(DISTINCT inv.institution_id) AS institutions,
                   count(DISTINCT inv.standard_code) AS items
            FROM inventory inv
            WHERE {where}
            GROUP BY inv.status
            """,
            params,
        )
        rows = cur.fetchall()
    by_status = {r["status"]: {"count": r["n"], "institutions": r["institutions"], "items": r["items"]} for r in rows}
    total = sum(v["count"] for v in by_status.values())
    return {"totalShortage": total, "byStatus": by_status}
