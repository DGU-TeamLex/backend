#!/usr/bin/env python3
"""표준품목 25개 SSIS 분류(scripts/reclassify_item_groups.py 결과)를 14개 메타코드로
추가 통합한다 — 2026-07-12 프로덕션 DB에 스크립트 밖에서(git 미추적) 직접 반영됐던
변경을 이 저장소에 다시 캡처해 추적 가능하게 만드는 스크립트.

배경: 팀에서 "20만 개 품목을 다 개별 예측/판단하기는 어렵다"는 문제의식으로 25개
행정분류를 다시 14개 영문 코드(MED_ORAL/MED_INJECT/MED_TOPICAL/MED_SUPPLY/
LAB_REAGENT/DISINFECT/SUPPLEMENT/PROMO/RENTAL/WASTE/FUEL/KM_HERB/KM_EXTRACT/
UNCLASSIFIED)로 묶었다. 프로덕션 DB에서 직접 역산해보니(2026-07-13) 이건 옛 25개
카테고리를 단순히 그룹핑한 게 아니라 물품명 기준으로 다시 분류한 결과다 — 예를 들어
옛 "진료약(약)"(8,111개) 중 87.2%만 새 MED_ORAL로 갔고 나머지는 MED_TOPICAL/
SUPPLEMENT/MED_INJECT/DISINFECT/MED_SUPPLY로 흩어졌다("소모품"은 8개 그룹으로
분산, purity 57%). 즉 카테고리 단위 함수가 아니라 품목 단위 재분류 결과이므로,
scripts/data/item_group_meta_codes.json 에 (표준코드 -> 메타코드) 매핑을 그대로
사전 계산해서 커밋해뒀다 — **어떤 방법(규칙/모델)으로 이 매핑을 만들었는지는 아직
문서화되지 않았다. 실행 전 이 매핑을 만든 사람에게 방법론을 확인해 이 주석을
갱신할 것.**

criticality(MEDICAL/CONSUMABLE)는 이 재분류로 변하지 않는다 — 프로덕션 DB 확인
결과 이전 scripts/reclassify_item_groups.py 실행 결과(MEDICAL 10,773 / CONSUMABLE
6,375)와 정확히 일치해서, 이 스크립트는 item_group_id 만 건드리고 criticality 는
그대로 둔다.

standard_items.item_group_id 는 이미 25개 분류가 적용된 상태라고 가정한다
(scripts/reclassify_item_groups.py 선행 실행 필요 — 이미 프로덕션엔 반영돼 있음).

실행: DATABASE_URL=... python3 scripts/consolidate_item_meta_groups.py

주의: 이 스크립트가 실행되기 전에 이미 프로덕션 DB는 이 최종 상태로 되어 있다
(2026-07-12, git 밖에서 반영됨) — 실행해도 결과가 바뀌지 않는 멱등 스크립트다.
이 스크립트의 목적은 "이미 일어난 변경을 코드로 재현 가능하게 만드는 것"이지
새로운 마이그레이션이 아니다.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CODES_FILE = os.path.join(DATA_DIR, "item_group_meta_codes.json")
NAMES_FILE = os.path.join(DATA_DIR, "item_group_meta_names.json")


def main():
    dsn = os.environ["DATABASE_URL"]
    code_to_meta = json.load(open(CODES_FILE, encoding="utf-8"))
    meta_names = json.load(open(NAMES_FILE, encoding="utf-8"))
    print(f"mapping: {len(code_to_meta)} items -> {len(meta_names)} meta-groups", flush=True)

    with psycopg.connect(dsn, row_factory=psycopg.rows.dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT standard_code FROM standard_items")
            db_codes = {r["standard_code"] for r in cur.fetchall()}
            unmapped = db_codes - set(code_to_meta.keys())
            if unmapped:
                print(f"WARNING: {len(unmapped)} DB codes not covered by mapping — 'UNCLASSIFIED'로 처리", flush=True)

            print("1) 14개 메타그룹 추가...", flush=True)
            for gid, name in meta_names.items():
                cur.execute(
                    "INSERT INTO item_groups (item_group_id, name) VALUES (%s, %s) "
                    "ON CONFLICT (item_group_id) DO UPDATE SET name = EXCLUDED.name",
                    (gid, name),
                )

            print("2) standard_items.item_group_id 재매핑 (criticality 는 유지)...", flush=True)
            cur.execute(
                "CREATE TEMP TABLE _meta_reclass (standard_code TEXT, item_group_id TEXT) ON COMMIT DROP"
            )
            with cur.copy("COPY _meta_reclass (standard_code, item_group_id) FROM STDIN") as cp:
                for code, gid in code_to_meta.items():
                    cp.write_row((code, gid))
                for code in unmapped:
                    cp.write_row((code, "UNCLASSIFIED"))
            cur.execute(
                "UPDATE standard_items si SET item_group_id = r.item_group_id "
                "FROM _meta_reclass r WHERE si.standard_code = r.standard_code"
            )
            print(f"   updated rows: {cur.rowcount}", flush=True)

            print("3) 이제 아무 표준품목도 참조하지 않는 옛 25개 분류 정리...", flush=True)
            cur.execute(
                "DELETE FROM item_groups ig WHERE NOT EXISTS "
                "(SELECT 1 FROM standard_items si WHERE si.item_group_id = ig.item_group_id)"
            )
            print(f"   removed old groups: {cur.rowcount}", flush=True)

        conn.commit()
    print("done.", flush=True)


if __name__ == "__main__":
    main()
