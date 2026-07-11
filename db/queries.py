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


def _inv_row(r: dict) -> dict:
    return {
        "standardCode": r["standard_code"], "standardName": r["standard_name"],
        "itemGroupId": r["item_group_id"], "criticality": r["criticality"], "uom": r["uom"],
        "onHand": r["on_hand"], "available": r["available"], "mu": r["mu"], "sigma": r["sigma"],
        "leadTimeUsed": r["lead_time_used"], "zUsed": r["z_used"], "SS": r["ss"], "ROP": r["rop"],
        "target": r["target"], "orderRecommendation": r["order_recommendation"],
        "supplyRiskLevel": r["supply_risk_level"], "status": r["status"],
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
    }


def get_user_by_email(email: str):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        r = cur.fetchone()
        return _user_row(r) if r else None


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
                   inv.ss, inv.rop, inv.target, inv.order_recommendation, inv.supply_risk_level, inv.status
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
                   inv.ss, inv.rop, inv.target, inv.order_recommendation, inv.supply_risk_level, inv.status
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
                   inv.ss, inv.rop, inv.target, inv.order_recommendation, inv.supply_risk_level, inv.status
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
                   inv.order_recommendation, si.uom, inv.supply_risk_level, inv.status
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
    } for r in rows]


def dashboard_central_summary() -> dict:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM institutions")
        institutions_n = cur.fetchone()["n"]
        cur.execute(
            """
            SELECT sum(on_hand) AS total_on_hand,
                   count(*) FILTER (WHERE status IN ('BELOW_ROP','CRITICAL')) AS below_rop_items
            FROM inventory
            """
        )
        agg = cur.fetchone()
        cur.execute("SELECT count(*) AS n FROM standard_items")
        standard_items_n = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM item_groups")
        item_groups_n = cur.fetchone()["n"]
    return {"institutions": institutions_n, "totalOnHand": agg["total_on_hand"] or 0,
            "belowRopItems": agg["below_rop_items"] or 0,
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
            "orderNeeded": sum(1 for r in inv if r["orderRecommendation"] > 0),
            "openAlerts": sum(1 for a in al if a["resolvedAt"] is None),
        },
        "inventory": inv,
        "alerts": al,
    }
