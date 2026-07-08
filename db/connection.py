"""Neon Postgres 연결 헬퍼 (Vercel 마켓플레이스로 프로비저닝).

서버리스 함수 환경이라 요청마다 짧게 연결한다(Neon 의 pooled DATABASE_URL 은
PgBouncer 를 앞단에 두고 있어 매 요청 connect 비용이 낮다). 전역 커넥션 풀을
유지하지 않는다 — 콜드스타트마다 프로세스가 새로 뜨는 서버리스 특성상 오히려
불필요한 복잡도만 늘어난다.
"""
import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row


@contextmanager
def get_conn():
    dsn = os.environ["DATABASE_URL"]
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        yield conn
