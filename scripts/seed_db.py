#!/usr/bin/env python3
"""Neon Postgres 최초 시드. db/schema.sql 실행 후 institutions/standard_items/
item_groups/inventory/alerts 를 채운다.

재고 생성 공식은 기존 routers/wep_inventory.py(이제 삭제됨, DB 이전 완료) 의
결정론적 로직과 완전히 동일하다(라이브에서 이미 보이던 값과 연속성 유지).
이 스크립트 실행 후부터는 재고가 DB 에 영속되므로, 매 요청 재계산하던 이전
방식과 달리 실제로 갱신 가능한 데이터가 된다.

실행: DATABASE_URL 환경변수가 설정된 상태에서 `python3 scripts/seed_db.py`
(.env.local 을 쓰려면: `python3 -c "from dotenv import load_dotenv; load_dotenv('.env.local')" `
방식 대신, 아래처럼 셸에서 export 하거나 env 를 직접 주입해서 실행한다.)
"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg

from routers import wep_data as D
from routers.institutions_data import INSTITUTIONS

_BASE_DEMAND = {
    "KD0192": 120, "KD0451": 45, "KD2570": 30, "KD2031": 25, "KD0820": 20,
    "KD1133": 70, "KD1490": 400, "KD2244": 15, "KD2899": 8, "KD3120": 60,
}


def _hash(s: str) -> int:
    return int(hashlib.md5(s.encode("utf-8")).hexdigest(), 16)


def _z(level):
    return {"NORMAL": 1.28, "CAUTION": 1.65, "WARNING": 2.05, "CRITICAL": 2.33}.get(level, 1.28)


def _l_mult(level):
    return {"NORMAL": 1.0, "CAUTION": 1.1, "WARNING": 1.25, "CRITICAL": 1.5}.get(level, 1.0)


def _scale(inst):
    t = inst.get("type", "")
    if t == "보건의료원":
        return 3.4
    if t == "보건소":
        return 3.0
    if inst.get("category") == "보건지소":
        return 1.2
    if inst.get("category") == "보건진료소":
        return 0.55
    return 1.0


def inventory_for(inst):
    iid = inst["id"]
    scale = _scale(inst)
    rows = []
    for item in D.STANDARD_ITEMS:
        code = item["standardCode"]
        h = _hash(iid + code)
        if h % 10 < 3:
            continue
        base = _BASE_DEMAND.get(code, 30)
        mu = max(2.0, round(base * scale * (0.7 + (h % 70) / 100.0), 1))
        sigma = round(mu * 0.35, 1)
        level = D.RISK_BY_GROUP.get(item["itemGroupId"], {}).get("level", "NORMAL")
        z = _z(level)
        L = round((1.0 if item["criticality"] == "CONSUMABLE" else 1.2) * _l_mult(level), 2)
        ss = round(z * sigma * (L ** 0.5), 1)
        rop = round(mu * L + ss, 1)
        avail_ratio = 0.2 + ((_hash(code + iid) % 200) / 100.0)
        available = max(0, round(rop * avail_ratio))
        on_hand = available + (h % 5)
        target = round(mu * (L + 1.0) + ss, 1)
        rec = max(0, round(target - available))
        rec = int((rec + 9) // 10 * 10) if rec > 0 else 0
        if available < rop * 0.5:
            status = "CRITICAL"
        elif available < rop:
            status = "BELOW_ROP"
        elif available < rop * 1.3:
            status = "WATCH"
        else:
            status = "OK"
        rows.append({
            "standardCode": code, "standardName": item["standardName"], "itemGroupId": item["itemGroupId"],
            "criticality": item["criticality"], "uom": item["uom"], "onHand": on_hand, "available": available,
            "mu": mu, "sigma": sigma, "leadTimeUsed": L, "zUsed": z, "SS": ss, "ROP": rop, "target": target,
            "orderRecommendation": rec, "supplyRiskLevel": level, "status": status,
        })
    return rows


def main():
    dsn = os.environ["DATABASE_URL"]
    schema_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db", "schema.sql")
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            print("applying schema...", flush=True)
            cur.execute(open(schema_path, encoding="utf-8").read())

            print("seeding item_groups...", flush=True)
            for g in D.ITEM_GROUPS:
                cur.execute(
                    "INSERT INTO item_groups (item_group_id, name) VALUES (%s, %s) "
                    "ON CONFLICT (item_group_id) DO UPDATE SET name = EXCLUDED.name",
                    (g["itemGroupId"], g["name"]),
                )

            print("seeding standard_items...", flush=True)
            for it in D.STANDARD_ITEMS:
                cur.execute(
                    "INSERT INTO standard_items (standard_item_id, standard_code, standard_name, item_group_id, uom, shelf_life_days, criticality) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (standard_item_id) DO UPDATE SET "
                    "standard_name=EXCLUDED.standard_name, item_group_id=EXCLUDED.item_group_id, uom=EXCLUDED.uom, "
                    "shelf_life_days=EXCLUDED.shelf_life_days, criticality=EXCLUDED.criticality",
                    (it["standardItemId"], it["standardCode"], it["standardName"], it["itemGroupId"],
                     it["uom"], it["shelfLifeDays"], it["criticality"]),
                )

            print("clearing previous seed (institutions/inventory/alerts)...", flush=True)
            cur.execute("TRUNCATE alerts, inventory, institutions RESTART IDENTITY CASCADE")

            print(f"seeding {len(INSTITUTIONS)} institutions...", flush=True)
            with cur.copy(
                "COPY institutions (id, name, type, category, sido, sigungu, island, parent, address, eupmyeondong, phone) "
                "FROM STDIN"
            ) as cp:
                for i in INSTITUTIONS:
                    cp.write_row((
                        i["id"], i["name"], i["type"], i["category"], i["sido"], i["sigungu"],
                        i["island"], i.get("parent") or None, i.get("address") or None,
                        i.get("eupmyeondong") or None, i.get("phone") or None,
                    ))

            print("generating + seeding inventory (this covers all institutions, may take a bit)...", flush=True)
            inv_rows = []
            critical_candidates = []
            for inst in INSTITUTIONS:
                for r in inventory_for(inst):
                    inv_rows.append((
                        inst["id"], r["standardCode"], r["onHand"], r["available"], r["mu"], r["sigma"],
                        r["leadTimeUsed"], r["zUsed"], r["SS"], r["ROP"], r["target"],
                        r["orderRecommendation"], r["supplyRiskLevel"], r["status"],
                    ))
                    if r["status"] == "CRITICAL":
                        severity_ratio = r["available"] / r["ROP"] if r["ROP"] else 0
                        critical_candidates.append((severity_ratio, inst, r))

            with cur.copy(
                "COPY inventory (institution_id, standard_code, on_hand, available, mu, sigma, lead_time_used, "
                "z_used, ss, rop, target, order_recommendation, supply_risk_level, status) FROM STDIN"
            ) as cp:
                for row in inv_rows:
                    cp.write_row(row)
            print(f"  inventory rows: {len(inv_rows)}", flush=True)

            print("seeding alerts (most severe CRITICAL rows, capped per item for variety)...", flush=True)
            critical_candidates.sort(key=lambda x: x[0])
            per_item_count = {}
            picked = []
            for cand in critical_candidates:
                _ratio, inst, r = cand
                code = r["standardCode"]
                if per_item_count.get(code, 0) >= 3:
                    continue
                per_item_count[code] = per_item_count.get(code, 0) + 1
                picked.append(cand)
                if len(picked) >= 20:
                    break
            n = 1
            for _ratio, inst, r in picked:
                alert_id = f"al_{n:04d}"
                title = f"{r['standardName']} 재고 미달(가용 {r['available']} < ROP {r['ROP']})"
                message = f"{inst['name']} {r['standardName']} 가용재고가 재주문점 아래입니다."
                cur.execute(
                    "INSERT INTO alerts (alert_id, alert_type, severity, institution_id, standard_code, title, message, evidence) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (alert_id) DO NOTHING",
                    (alert_id, "STOCK_BELOW_ROP", "CRITICAL", inst["id"], r["standardCode"], title, message,
                     psycopg.types.json.Jsonb({"available": r["available"], "ROP": r["ROP"]})),
                )
                n += 1

        conn.commit()
    print("done.", flush=True)


if __name__ == "__main__":
    main()
