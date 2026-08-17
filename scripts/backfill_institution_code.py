#!/usr/bin/env python3
"""institutions.institution_code 백필 — 정렬 역산 (이슈 #75, #16).

scripts/import_ssis_dataset.py 는 익명 기관코드(`보건기관코드_en`)를 실명목록
(routers/institutions_data.py)과 **정렬 순서로 1:1 임의 매핑**해왔다:

    real_ids   = sorted(inst["id"] for inst in INSTITUTIONS)
    anon_codes = sorted(all_institutions)          # 원본 파일에서 수집한 코드 집합
    code_to_real = dict(zip(anon_codes, real_ids))
    ...
    institution_id (=inst_XXXX) 를 inventory.institution_id 로 적재

이 매핑은 실제 신원 대응이 아니지만(#75), **결정론적**이라는 성질은 남는다 —
두 리스트를 "같은 방식으로" 정렬해 zip 했으므로, 원본 파일에서 다시 코드 목록을
모아 같은 정렬·zip 을 거꾸로 뒤집으면(real_id -> code) 이미 적재된 inst_XXXX 가
당시 어떤 코드에 대응했는지 정확히 재현할 수 있다. 이 스크립트는 그 "정렬 역산"만
수행한다 — 원장 재적재(옵션 1, #39)와 달리 mu/sigma/on_hand 등 기존 inventory
수치는 전혀 건드리지 않고, institutions.institution_code 컬럼만 채운다.

⚠️ 이 스크립트는 로컬/리뷰어 환경에서 원본 .DAT 파일에 접근 가능할 때 실행하는
   용도다. 이 자동 구현 세션은 원본 데이터(SSIS_DATA_DIR)에도 운영 DB
   (DATABASE_URL)에도 접근하지 않으며, 이 스크립트를 실행하지 않는다.

실행 전제 (import_ssis_dataset.py 와 동일):
  - SSIS_DATA_DIR: 원본 .dat 10개 파일이 있는 디렉토리(part_0.dat ~ part_9.dat,
    pipe-구분, UTF-8). 2024~2025 물품 입출고 데이터셋이어야 한다 — 다른 기간
    파일(예: 2018~2019 전용)을 넣으면 코드 집합이 달라져 결과가 틀어진다.
  - DATABASE_URL: 이미 import_ssis_dataset.py 로 적재된 Neon Postgres.

실행:
  SSIS_DATA_DIR=/path/to/extracted DATABASE_URL=... \\
      python3 scripts/backfill_institution_code.py

  --dry-run 이면 UPDATE 없이 매핑 통계만 출력한다.
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# import_ssis_dataset.py 와 동일한 컬럼 계약·파일 목록 로직을 그대로 재사용한다
# (기관코드 소스·정렬키를 별도로 재구현하면 두 스크립트가 조용히 어긋날 수 있다).
from scripts import import_ssis_dataset as ssis  # noqa: E402
from routers.institutions_data import INSTITUTIONS  # noqa: E402


def collect_anon_codes() -> list:
    """원본 .dat 파일에서 익명 기관코드(`보건기관코드_en`)만 가볍게 수집한다.

    import_ssis_dataset.parse_and_aggregate() 와 달리 mu/sigma·품목 집계는
    하지 않는다 — 이 스크립트가 필요한 것은 agg["all_institutions"](정렬된
    고유 코드 목록)뿐이고, 그 값은 원본 코드 컬럼만 훑으면 재현된다.
    """
    codes = set()
    csv.field_size_limit(10 ** 9)
    for fp in ssis.data_files():
        with open(fp, encoding="utf-8", newline="") as f:
            reader = csv.reader(f, delimiter="|", quotechar='"')
            try:
                header = next(reader)
            except StopIteration:
                print(f"  {fp}: 빈 파일, 건너뜀", flush=True)
                continue
            header = [h.strip() for h in header]
            idx = {name: i for i, name in enumerate(header)}
            missing = [c for c in ssis.REQUIRED_COLUMNS if c not in idx]
            if missing:
                raise SystemExit(f"[FATAL] {fp}: 필수 컬럼 누락 {missing}\n  실제 헤더: {header}")
            i_inst = idx[ssis.COL_INST]
            n_this = 0
            for parts in reader:
                if len(parts) <= i_inst:
                    continue
                code = parts[i_inst]
                if code:
                    codes.add(code)
                n_this += 1
            print(f"  {fp}: {n_this} rows scanned", flush=True)
    return sorted(codes)


def build_real_to_code() -> dict:
    """institution_id(inst_XXXX) -> 익명 기관코드. import_ssis_dataset.py 의
    code_to_real = dict(zip(anon_codes, real_ids)) 를 그대로 재현한 뒤 뒤집는다."""
    real_ids = sorted(inst["id"] for inst in INSTITUTIONS)
    anon_codes = collect_anon_codes()
    print(f"institutions(real)={len(real_ids)} anon_codes={len(anon_codes)}", flush=True)

    code_to_real = dict(zip(anon_codes, real_ids))
    real_to_code = {real: code for code, real in code_to_real.items()}
    print(f"reconstructed mapping: {len(real_to_code)} institution_id -> code pairs", flush=True)
    return real_to_code


def main():
    dry_run = "--dry-run" in sys.argv
    real_to_code = build_real_to_code()

    if dry_run:
        sample = list(real_to_code.items())[:5]
        print(f"[dry-run] sample: {sample}", flush=True)
        print(f"[dry-run] UPDATE 를 실행하지 않았습니다 (총 {len(real_to_code)}건 예정).", flush=True)
        return

    import psycopg

    dsn = os.environ["DATABASE_URL"]
    rows = list(real_to_code.items())
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "UPDATE institutions SET institution_code = %s WHERE id = %s",
                [(code, real_id) for real_id, code in rows],
            )
        conn.commit()
    print(f"backfilled institution_code for {len(rows)} institutions.", flush=True)


if __name__ == "__main__":
    main()
