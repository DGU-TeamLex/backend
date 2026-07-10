#!/usr/bin/env python3
"""데모 계정 시드 (idempotent upsert) — 인증/RBAC 스켈레톤 확인용.

공개 가입 플로우가 없으므로 계정은 이 스크립트로만 생성한다. 비밀번호는
코드에 하드코딩하지 않고 환경변수로 받는다(미설정 시 개발용 기본값 사용 —
프로덕션에서 실제로 쓸 계정이면 SEED_*_PASSWORD 를 지정해서 재실행할 것).

실행: DATABASE_URL 환경변수가 설정된 상태에서 `python3 scripts/seed_users.py`
(institutions 테이블이 먼저 채워져 있어야 한다 — scripts/seed_db.py 선행 실행)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg

from auth.security import hash_password

CENTRAL_PASSWORD = os.environ.get("SEED_CENTRAL_PASSWORD", "wepstock-central-demo!")
INSTITUTION_PASSWORD = os.environ.get("SEED_INSTITUTION_PASSWORD", "wepstock-institution-demo!")


def _upsert(cur, user_id, email, password, name, role, institution_id):
    cur.execute(
        "INSERT INTO users (id, email, password_hash, name, role, institution_id) "
        "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET "
        "password_hash=EXCLUDED.password_hash, name=EXCLUDED.name, role=EXCLUDED.role, "
        "institution_id=EXCLUDED.institution_id",
        (user_id, email, hash_password(password), name, role, institution_id),
    )


def main():
    dsn = os.environ["DATABASE_URL"]
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name FROM institutions ORDER BY id LIMIT 1")
            sample = cur.fetchone()
            if not sample:
                print("institutions 테이블이 비어 있습니다 — 먼저 scripts/seed_db.py 를 실행하세요.", flush=True)
                return
            sample_id, sample_name = sample

            print("upserting demo users...", flush=True)
            _upsert(cur, "u_central_demo", "admin@teamlex.local", CENTRAL_PASSWORD,
                    "중앙관리자(데모)", "CENTRAL", None)
            _upsert(cur, "u_institution_demo", "institution@teamlex.local", INSTITUTION_PASSWORD,
                    f"{sample_name} 담당자(데모)", "INSTITUTION", sample_id)
            conn.commit()

    print("done.", flush=True)
    print(f"  CENTRAL    : admin@teamlex.local / {CENTRAL_PASSWORD}")
    print(f"  INSTITUTION: institution@teamlex.local / {INSTITUTION_PASSWORD}  ({sample_name})")


if __name__ == "__main__":
    main()
