#!/usr/bin/env python3
"""한국사회보장정보원(SSIS) 실제 물품 입출고 데이터셋을 표준품목/재고로 적재.

2026-07-10 메일로 수신한 원본 데이터(부서별 물품 일별 입출고 내역, pipe-구분
DAT 파일 10개, 총 1,626만행, 2024-01-01~2025-12-31)를 다음과 같이 가공한다:

  1. (물품코드, 물품명) → 표준품목(standard_items) 카탈로그로 치환
     (기존 10개 가짜 품목 → 실제 17,148개 품목). 품목군(item_groups)은
     데이터 정의서를 아직 확보하지 못해(Gmail 첨부라 자동 다운로드 불가)
     품목명 키워드 휴리스틱으로 추정 분류했다 — 정확한 표준 분류 체계가
     오면 재작업 필요.
  2. (물품코드, 익명화기관코드) 쌍별로 정상출고량(정상 출고, 실제 소모량)의
     일별 평균/표준편차를 계산해 mu/sigma 로 사용 — 기존엔 해시 기반 가짜
     값이었다. 최근 마감재고량을 on_hand/available 로 사용(기존엔 fake).
  3. 익명화 기관코드는 실제 기관명과 매핑할 방법이 없어(가명처리),
     기존 실제 기관 목록(routers/institutions_data.py, 보건복지부 3,598곳)에
     정렬 순서로 1:1 임의 매핑했다 — 실제 신원 대응이 아님을 명시.
  4. [2026-07-17 정정] 이 스크립트의 mu/sigma 와 리드타임은 결함이 있다.
     scripts/fix_inventory_stats.py 로 교정하므로 이 스크립트 단독 실행 후에는
     반드시 그 스크립트를 이어 실행할 것.
       - mu/sigma: 아래 Welford 누적이 '파일에 존재하는 행'만 세어 결측일(수요 0)을
         복원하지 않는다. 원본은 거래일만 행이 있는 희소 패널이라(관측 중앙값
         11일/731일) 실측상 mu 가 7.9배 과대해진다(12.77 vs 1.95).
       - 리드타임: '원본에 없다'는 종전 서술은 틀렸다. `이전최종재고량` 으로
         품절 상태 입고를 판정해 품절→입고 시차를 실측할 수 있다
         (P10=15일/P50=36일/P90=77일, 표본 92,493). 상수 1일은 근거가 없다.

실행 전: SSIS_DATA_DIR 환경변수로 원본 .dat 10개 파일이 있는 디렉토리를
지정한다(part_0.dat ~ part_9.dat, pipe-구분, UTF-8). DATABASE_URL 도 필요.

  SSIS_DATA_DIR=/path/to/extracted DATABASE_URL=... python3 scripts/import_ssis_dataset.py
"""
import hashlib
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg

from routers.institutions_data import INSTITUTIONS

DATA_DIR = os.environ.get("SSIS_DATA_DIR", "extracted")
NUM_FILES = 10

# ===== 1. 원본 10개 파일 파싱 + 집계 (한 번의 스트리밍 패스) =====

MEDICAL_HINTS = ["mg", "정)", "캡슐", "시럽", "현탁", "점안", "연고", "패치", "좌제", "분말", "주)"]

GROUP_RULES = [
    ("주사기_니들", ["주사기", "니들", "바늘"]),
    ("장갑_보호구", ["장갑", "가운", "마스크", "보안경"]),
    ("소독_멸균", ["소독", "멸균", "알콜", "거즈", "밴드"]),
    ("검사_진단키트", ["키트", "시약", "스트립", "스틱", "혈당"]),
    ("주사_수액", ["수액", "세트", "IV"]),
    ("내복약", ["정", "캡슐", "시럽", "산제"]),
    ("외용제", ["연고", "크림", "패치", "점안", "좌제"]),
]


def item_group_for(name: str) -> str:
    for gid, keywords in GROUP_RULES:
        if any(k in name for k in keywords):
            return gid
    return "기타의료소모품"


def criticality_for(name: str) -> str:
    return "MEDICAL" if any(h in name for h in MEDICAL_HINTS) else "CONSUMABLE"


def uom_for(name: str) -> str:
    if "mL" in name or "ml" in name:
        return "mL"
    if "정" in name:
        return "정"
    if "캡슐" in name:
        return "캡슐"
    return "개"


def to_float(s: str) -> float:
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_and_aggregate():
    item_name_count = {}
    item_price_sum = {}
    item_price_n = {}

    pair_n = {}
    pair_mean = {}
    pair_M2 = {}
    pair_last_date = {}
    pair_last_closing = {}

    all_institutions = set()
    total_rows = 0
    bad_rows = 0
    min_date = None
    max_date = None
    t0 = time.time()

    for i in range(NUM_FILES):
        fp = os.path.join(DATA_DIR, f"part_{i}.dat")
        n_this = 0
        with open(fp, encoding="utf-8") as f:
            f.readline()
            for line in f:
                parts = line.rstrip("\r\n").split("|")
                if len(parts) < 18:
                    bad_rows += 1
                    continue
                item_code = parts[1]
                tail = parts[-15:]
                name = "|".join(parts[2:-15])

                date = tail[0]
                closing_qty = to_float(tail[2])
                unit_price = to_float(tail[6])
                qty_out_normal = to_float(tail[9])
                inst_code = tail[14]

                if not item_code or not inst_code:
                    bad_rows += 1
                    continue

                nc = item_name_count.setdefault(item_code, {})
                nc[name] = nc.get(name, 0) + 1
                if unit_price > 0:
                    item_price_sum[item_code] = item_price_sum.get(item_code, 0.0) + unit_price
                    item_price_n[item_code] = item_price_n.get(item_code, 0) + 1

                all_institutions.add(inst_code)
                if min_date is None or date < min_date:
                    min_date = date
                if max_date is None or date > max_date:
                    max_date = date

                key = (item_code, inst_code)
                n = pair_n.get(key, 0) + 1
                pair_n[key] = n
                mean = pair_mean.get(key, 0.0)
                delta = qty_out_normal - mean
                mean += delta / n
                pair_mean[key] = mean
                delta2 = qty_out_normal - mean
                pair_M2[key] = pair_M2.get(key, 0.0) + delta * delta2

                ld = pair_last_date.get(key)
                if ld is None or date >= ld:
                    pair_last_date[key] = date
                    pair_last_closing[key] = closing_qty

                n_this += 1
        total_rows += n_this
        print(f"  {fp}: {n_this} rows", flush=True)

    print(f"parsed {total_rows} rows ({bad_rows} malformed skipped) in {round(time.time()-t0,1)}s", flush=True)
    print(f"items={len(item_name_count)} institutions={len(all_institutions)} pairs={len(pair_n)}", flush=True)

    final_item_name = {code: max(counts.items(), key=lambda kv: kv[1])[0] for code, counts in item_name_count.items()}
    item_avg_price = {code: item_price_sum[code] / item_price_n[code] for code in item_price_sum}

    return {
        "item_name": final_item_name,
        "item_avg_price": item_avg_price,
        "total_rows": total_rows,
        "bad_rows": bad_rows,
        "min_date": min_date,
        "max_date": max_date,
        "pair_n": pair_n,
        "pair_mean": pair_mean,
        "pair_M2": pair_M2,
        "pair_last_closing": pair_last_closing,
        "all_institutions": sorted(all_institutions),
    }


# ===== 2. SS/ROP 공식 (기존 scripts/seed_db.py 와 동일 — mu/sigma/on_hand 만 실데이터로 교체) =====

Z_NORMAL = 1.28  # 실제 기관/품목별 공급위험 레벨이 없어 NORMAL 고정


def inventory_row(mu, sigma, on_hand, criticality):
    mu = max(0.5, mu)
    sigma = max(0.1, sigma)
    L = 1.0 if criticality == "CONSUMABLE" else 1.2
    z = Z_NORMAL
    ss = round(z * sigma * (L ** 0.5), 1)
    rop = round(mu * L + ss, 1)
    available = max(0, int(round(on_hand)))
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
    return {
        "onHand": available, "available": available, "mu": round(mu, 2), "sigma": round(sigma, 2),
        "leadTimeUsed": L, "zUsed": z, "SS": ss, "ROP": rop, "target": target,
        "orderRecommendation": rec, "supplyRiskLevel": "NORMAL", "status": status,
    }


def main():
    dsn = os.environ["DATABASE_URL"]
    agg = parse_and_aggregate()

    # 익명 기관코드 → 실제 기관(routers/institutions_data.py) 1:1 매핑 (정렬 순서, 임의)
    real_ids = sorted(inst["id"] for inst in INSTITUTIONS)
    anon_codes = agg["all_institutions"]
    code_to_real = dict(zip(anon_codes, real_ids))
    print(f"institution mapping: {len(code_to_real)} of {len(real_ids)} real institutions matched", flush=True)

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            print("clearing standard_items/item_groups/inventory/alerts...", flush=True)
            cur.execute("TRUNCATE alerts, inventory, standard_items, item_groups RESTART IDENTITY CASCADE")

            groups = sorted({gid for gid, _ in GROUP_RULES} | {"기타의료소모품"})
            for gid in groups:
                cur.execute(
                    "INSERT INTO item_groups (item_group_id, name) VALUES (%s, %s)",
                    (gid, gid.replace("_", "/")),
                )
            print(f"item_groups: {len(groups)}", flush=True)

            print("seeding standard_items (real catalog)...", flush=True)
            with cur.copy(
                "COPY standard_items (standard_item_id, standard_code, standard_name, item_group_id, uom, "
                "shelf_life_days, criticality) FROM STDIN"
            ) as cp:
                for code, name in agg["item_name"].items():
                    crit = criticality_for(name)
                    cp.write_row((code, code, name[:500], item_group_for(name), uom_for(name), None, crit))
            print(f"standard_items: {len(agg['item_name'])}", flush=True)

            print("seeding inventory (real mu/sigma/on_hand from transaction history)...", flush=True)
            item_crit = {code: criticality_for(name) for code, name in agg["item_name"].items()}
            inv_rows = []
            critical_candidates = []
            for (item_code, inst_code), n in agg["pair_n"].items():
                real_inst = code_to_real.get(inst_code)
                if not real_inst:
                    continue
                mean = agg["pair_mean"][(item_code, inst_code)]
                variance = agg["pair_M2"][(item_code, inst_code)] / n if n > 0 else 0.0
                sigma = variance ** 0.5
                on_hand = agg["pair_last_closing"][(item_code, inst_code)]
                r = inventory_row(mean, sigma, on_hand, item_crit.get(item_code, "CONSUMABLE"))
                inv_rows.append((
                    real_inst, item_code, r["onHand"], r["available"], r["mu"], r["sigma"],
                    r["leadTimeUsed"], r["zUsed"], r["SS"], r["ROP"], r["target"],
                    r["orderRecommendation"], r["supplyRiskLevel"], r["status"],
                ))
                if r["status"] == "CRITICAL":
                    ratio = r["available"] / r["ROP"] if r["ROP"] else 0
                    critical_candidates.append((ratio, real_inst, item_code, agg["item_name"].get(item_code, item_code), r))

            with cur.copy(
                "COPY inventory (institution_id, standard_code, on_hand, available, mu, sigma, lead_time_used, "
                "z_used, ss, rop, target, order_recommendation, supply_risk_level, status) FROM STDIN"
            ) as cp:
                for row in inv_rows:
                    cp.write_row(row)
            print(f"inventory rows: {len(inv_rows)}", flush=True)

            print("seeding alerts (most severe CRITICAL rows, capped per item)...", flush=True)
            critical_candidates.sort(key=lambda x: x[0])
            per_item_count = {}
            picked = []
            for cand in critical_candidates:
                _ratio, inst_id, code, name, r = cand
                if per_item_count.get(code, 0) >= 3:
                    continue
                per_item_count[code] = per_item_count.get(code, 0) + 1
                picked.append(cand)
                if len(picked) >= 30:
                    break
            n = 1
            for _ratio, inst_id, code, name, r in picked:
                alert_id = f"al_{n:04d}"
                title = f"{name} 재고 미달(가용 {r['available']} < ROP {r['ROP']})"
                message = f"{inst_id} {name} 가용재고가 재주문점 아래입니다."
                cur.execute(
                    "INSERT INTO alerts (alert_id, alert_type, severity, institution_id, standard_code, title, message, evidence) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (alert_id) DO NOTHING",
                    (alert_id, "STOCK_BELOW_ROP", "CRITICAL", inst_id, code, title, message,
                     psycopg.types.json.Jsonb({"available": r["available"], "ROP": r["ROP"]})),
                )
                n += 1
            print(f"alerts: {n-1}", flush=True)

            print("recording import_batches entry (실제 적재 이력)...", flush=True)
            valid_rows = agg["total_rows"] - agg["bad_rows"]
            mapping_rate = round(len(code_to_real) / len(real_ids), 4) if real_ids else 0.0
            batch_id = f"ib_ssis_{agg['min_date']}_{agg['max_date']}"
            cur.execute(
                "INSERT INTO import_batches (import_batch_id, file_name, source_vendor, status, total_rows, "
                "valid_rows, error_rows, mapping_rate, period_start, period_end) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (import_batch_id) DO UPDATE SET total_rows=EXCLUDED.total_rows, "
                "valid_rows=EXCLUDED.valid_rows, error_rows=EXCLUDED.error_rows, mapping_rate=EXCLUDED.mapping_rate",
                (batch_id, "(한국사회보장정보원)_의료재고예측모델 개발 관련 데이터셋(물품재고_0~9).zip",
                 "ssis.or.kr", "COMPLETED", agg["total_rows"], valid_rows, agg["bad_rows"], mapping_rate,
                 agg["min_date"], agg["max_date"]),
            )
            print(f"import_batches: 1 (mapping_rate={mapping_rate})", flush=True)

        conn.commit()
    print("done.", flush=True)


if __name__ == "__main__":
    main()
