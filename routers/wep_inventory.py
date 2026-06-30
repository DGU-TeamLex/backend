"""실제 기관(institutions_data) 기반 결정론적 재고 생성 + 탐색 헬퍼.

기관×품목 재고를 해시 기반으로 결정론적으로 생성한다(저장 없이 매번 동일).
지역(시도/시군구) · 기관유형(category) 필터, 기관별 재고/상태 요약을 제공한다.
"""
import hashlib
from . import wep_data as D
from .institutions_data import INSTITUTIONS

INST_BY_ID = {i["id"]: i for i in INSTITUTIONS}

# 품목별 월 기준 수요(베이스라인)
_BASE_DEMAND = {
    "KD0192": 120, "KD0451": 45, "KD2570": 30, "KD2031": 25, "KD0820": 20,
    "KD1133": 70, "KD1490": 400, "KD2244": 15, "KD2899": 8, "KD3120": 60,
}
_ITEM_BY_CODE = {it["standardCode"]: it for it in D.STANDARD_ITEMS}


def _hash(s: str) -> int:
    return int(hashlib.md5(s.encode("utf-8")).hexdigest(), 16)


def _z(level: str) -> float:
    return {"NORMAL": 1.28, "CAUTION": 1.65, "WARNING": 2.05, "CRITICAL": 2.33}.get(level, 1.28)


def _l_mult(level: str) -> float:
    return {"NORMAL": 1.0, "CAUTION": 1.1, "WARNING": 1.25, "CRITICAL": 1.5}.get(level, 1.0)


def _scale(inst: dict) -> float:
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


def inventory_for(inst: dict) -> list:
    """기관의 품목별 재고/적정재고/상태를 결정론적으로 생성."""
    iid = inst["id"]
    scale = _scale(inst)
    rows = []
    for item in D.STANDARD_ITEMS:
        code = item["standardCode"]
        h = _hash(iid + code)
        # 기관은 품목의 약 70%만 취급 (결정론적)
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
        # 가용재고: ROP 대비 0.2~2.2배 분포 → 다양한 상태
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
            "standardCode": code, "standardName": item["standardName"],
            "itemGroupId": item["itemGroupId"], "criticality": item["criticality"], "uom": item["uom"],
            "onHand": on_hand, "available": available, "mu": mu, "sigma": sigma,
            "leadTimeUsed": L, "zUsed": z, "SS": ss, "ROP": rop, "target": target,
            "orderRecommendation": rec, "supplyRiskLevel": level, "status": status,
        })
    return rows


def summarize(inst: dict) -> dict:
    inv = inventory_for(inst)
    crit = sum(1 for r in inv if r["status"] == "CRITICAL")
    below = sum(1 for r in inv if r["status"] == "BELOW_ROP")
    watch = sum(1 for r in inv if r["status"] == "WATCH")
    order = sum(1 for r in inv if r["orderRecommendation"] > 0)
    if crit:
        badge = {"level": "CRITICAL", "label": "긴급", "count": crit}
    elif below:
        badge = {"level": "WARN", "label": "주의", "count": below}
    elif watch:
        badge = {"level": "WATCH", "label": "관찰", "count": watch}
    else:
        badge = {"level": "OK", "label": "정상", "count": 0}
    return {"trackedItems": len(inv), "critical": crit, "belowRop": below, "watch": watch, "orderNeeded": order, "badge": badge}


# ---- 탐색 헬퍼 ----
def categories() -> list:
    order = ["보건소", "보건지소", "보건진료소"]
    cnt = {}
    for i in INSTITUTIONS:
        cnt[i["category"]] = cnt.get(i["category"], 0) + 1
    return [{"category": c, "count": cnt.get(c, 0)} for c in order if cnt.get(c)]


def _filtered(category=None, sido=None, sigungu=None, q=None):
    items = INSTITUTIONS
    if category:
        items = [i for i in items if i["category"] == category]
    if sido:
        items = [i for i in items if i["sido"] == sido]
    if sigungu:
        items = [i for i in items if i["sigungu"] == sigungu]
    if q:
        items = [i for i in items if q in i["name"]]
    return items


def regions(category=None, sido=None) -> dict:
    items = _filtered(category=category, sido=sido)
    if not sido:
        cnt = {}
        for i in items:
            cnt[i["sido"]] = cnt.get(i["sido"], 0) + 1
        return {"level": "sido", "items": [{"name": k, "count": v} for k, v in cnt.items()]}
    cnt = {}
    for i in items:
        cnt[i["sigungu"]] = cnt.get(i["sigungu"], 0) + 1
    return {"level": "sigungu", "sido": sido, "items": sorted([{"name": k, "count": v} for k, v in cnt.items()], key=lambda x: x["name"])}


def facilities(category=None, sido=None, sigungu=None, q=None, limit=300) -> dict:
    items = _filtered(category=category, sido=sido, sigungu=sigungu, q=q)
    total = len(items)
    items = items[:limit]
    out = []
    for i in items:
        out.append({
            "id": i["id"], "name": i["name"], "type": i["type"], "category": i["category"],
            "sido": i["sido"], "sigungu": i["sigungu"], "island": i["island"],
            "summary": summarize(i),
        })
    return {"items": out, "totalElements": total, "returned": len(out), "truncated": total > len(out)}


def facility_detail(inst_id: str):
    inst = INST_BY_ID.get(inst_id)
    if not inst:
        return None
    inv = inventory_for(inst)
    s = summarize(inst)
    return {
        "institution": inst,
        "summary": {"trackedItems": s["trackedItems"], "belowRop": s["critical"] + s["belowRop"],
                    "critical": s["critical"], "orderNeeded": s["orderNeeded"]},
        "inventory": inv,
    }


# ---- 적정재고/발주/중앙대시보드용 샘플(주요 보건소 일부) ----
def _sample_institutions(n=14):
    seen, out = set(), []
    for i in INSTITUTIONS:
        if i["category"] == "보건소" and i["sido"] not in seen:
            seen.add(i["sido"])
            out.append(i)
        if len(out) >= n:
            break
    return out


SAMPLE_INSTITUTIONS = _sample_institutions()


def sample_inventory_rows() -> list:
    rows = []
    for inst in SAMPLE_INSTITUTIONS:
        for r in inventory_for(inst):
            rows.append({**r, "institutionId": inst["id"], "institutionName": inst["name"],
                         "sido": inst["sido"], "sigungu": inst["sigungu"]})
    return rows
