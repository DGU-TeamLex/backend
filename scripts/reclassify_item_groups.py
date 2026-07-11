#!/usr/bin/env python3
"""사용자가 제공한 SSIS 정식 물품분류표(물품명 물품분류별 물품리스트.xlsx, 28만행)
기준으로 item_groups/standard_items 를 재분류한다.

기존 8개 품목군(주사기_니들, 기타의료소모품 등)은 데이터 정의서가 없던 상태에서
품목명 키워드로 임시 추정한 것이었고, 실제로는 카탈로그의 90% 이상이 "기타의료소모품"
하나에 몰려 있었다(사실상 분류 실패). 이번엔 SSIS가 실제 운영에 쓰는 25개 공식
분류(소모품/진료약(약)/진료약(주사)/치료재료/검사시약/홍보물품 등)로 교체한다.

매칭 방법: 표준품목명(standard_name)을 분류표의 물품명과 정확히(실패 시 공백
제거 후) 대조. 한 물품명이 여러 분류로 나타나는 경우(부서/사업 예산 라인에 따라
같은 품목이 다르게 잡힌 것으로 보임, 약 8%)는 최빈 분류로 해소했다. 이 매칭을
scripts/data/item_group_reclassify.json (standard_code -> 분류명, 17,148건,
매칭률 99.5%, 미매칭 85건은 "미분류")에 미리 계산해 커밋해뒀다 — 이 스크립트는
그 매핑을 DB에 반영만 한다.

criticality(MEDICAL/CONSUMABLE)는 분류표에 없는 값이라 카테고리 성격으로 판단한
임의 매핑이다(MEDICAL_CATEGORIES 참고) — 실제 위험도 분류 기준이 오면 재조정 필요.

inventory/alerts 는 standard_code 를 참조하므로 영향 없음 — item_groups 재시딩 +
standard_items.item_group_id/criticality UPDATE만 수행한다(TRUNCATE 없음, 기존
재고/알림 데이터 보존).

실행: DATABASE_URL=... python3 scripts/reclassify_item_groups.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "item_group_reclassify.json")

# 분류표엔 위험도/중요도 구분이 없어 카테고리 성격으로 판단한 임의 매핑.
# 진료약·치료재료·검사시약 계열은 MEDICAL(리드타임 버퍼 L=1.2), 나머지는 CONSUMABLE(L=1.0).
MEDICAL_CATEGORIES = {
    "진료약(약)", "진료약(주사)", "사업약주사", "치료재료", "검사시약",
    "검사컨트롤(물질)", "소독약품", "한방보험엑스제", "한방약초", "영양제",
    "구강물품(불소)",
}


def main():
    dsn = os.environ["DATABASE_URL"]
    code_to_cat = json.load(open(DATA_FILE, encoding="utf-8"))
    categories = sorted(set(code_to_cat.values()))
    print(f"mapping: {len(code_to_cat)} items -> {len(categories)} categories", flush=True)

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT standard_code FROM standard_items")
            db_codes = {r["standard_code"] for r in cur.fetchall()}
            unmapped = db_codes - set(code_to_cat.keys())
            if unmapped:
                print(f"WARNING: {len(unmapped)} DB codes not covered by mapping — '미분류'로 처리", flush=True)

            print("1) 신규 25개 분류(+미분류) 추가...", flush=True)
            for cat in categories:
                cur.execute(
                    "INSERT INTO item_groups (item_group_id, name) VALUES (%s, %s) "
                    "ON CONFLICT (item_group_id) DO NOTHING",
                    (cat, cat),
                )

            print("2) standard_items 재분류(item_group_id/criticality UPDATE)...", flush=True)
            cur.execute(
                "CREATE TEMP TABLE _reclass (standard_code TEXT, item_group_id TEXT, criticality TEXT) "
                "ON COMMIT DROP"
            )
            with cur.copy("COPY _reclass (standard_code, item_group_id, criticality) FROM STDIN") as cp:
                for code, cat in code_to_cat.items():
                    crit = "MEDICAL" if cat in MEDICAL_CATEGORIES else "CONSUMABLE"
                    cp.write_row((code, cat, crit))
                for code in unmapped:
                    cp.write_row((code, "미분류", "CONSUMABLE"))
            cur.execute(
                "UPDATE standard_items si SET item_group_id = r.item_group_id, criticality = r.criticality "
                "FROM _reclass r WHERE si.standard_code = r.standard_code"
            )
            print(f"   updated rows: {cur.rowcount}", flush=True)

            print("3) 이제 아무 표준품목도 참조하지 않는 옛 8개 품목군 정리...", flush=True)
            cur.execute(
                "DELETE FROM item_groups ig WHERE NOT EXISTS "
                "(SELECT 1 FROM standard_items si WHERE si.item_group_id = ig.item_group_id)"
            )
            print(f"   removed old groups: {cur.rowcount}", flush=True)

        conn.commit()
    print("done.", flush=True)


if __name__ == "__main__":
    main()
