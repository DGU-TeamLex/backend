#!/usr/bin/env python3
"""AI 서빙(모듈 D) 재고정책 응답 → inventory 적재 어댑터.

ai#23 "[모듈D] SS/ROP·발주권고 수치 계산 (AI 소유, backend서 이관)" 의 backend 쪽 수용부.

배경
  README 의 저장소 책임 범위상 재고정책(safety stock)·발주권고 '알고리즘'은 ai 레포 소유다.
  그동안은 ai 서빙 API 가 배포 전이라 backend 의 scripts/fix_inventory_stats.py 가 임시로
  직접 계산해왔다(스톱갭). 이 어댑터는 그 계산을 **AI 응답 소비로 대체**하기 위한 자리다.

  fix_inventory_stats.py (임시·계산 주체=backend)  →  ai_policy_adapter.py (정식·계산 주체=ai)

  backend 가 계속 책임지는 것: 응답 검증 · inventory upsert · status 파생 · 권한/집계/서빙.
  backend 가 더는 하지 않는 것: mu/sigma 추정, 리드타임 추정, z 결정, SS/ROP/발주량 산출.

────────────────────────────────────────────────────────────────────────
기대하는 AI 서빙 응답 계약 (ai 레포가 구현)

  GET {AI_SERVING_URL}/api/v1/ai/order-recommendations
  →
  {
    "asOf": "2026-07-18",
    "model": {"name": "SBA", "version": "1.0"},     # 예측모델 식별 (감사·재현용)
    "items": [
      {
        "institutionId": "INST_0001",
        "standardCode": "STD_000123",
        "mu": 1.95,                 # 일평균 수요 — 결측일 0 복원 기준 (ai#17)
        "sigma": 4.72,              # 일 수요 표준편차
        "leadTimeDays": 25.5,       # 적용 리드타임(공급위험 배수 반영 후 최종값)
        "z": 2.33,                  # 서비스수준 z (공급위험 커플링 반영, ai#20)
        "SS": 87.5,                 # 안전재고
        "ROP": 156.6,               # 재주문점
        "target": 180.0,            # 목표재고
        "orderRecommendation": 42,  # 권고 발주량
        "supplyRiskLevel": "CRITICAL"   # NORMAL|CAUTION|WARNING|CRITICAL
      }
    ]
  }

  참고(이관 근거): 현재 backend 가 쓰던 식은 아래와 같다. ai 가 동일 의미의 값을 내면 된다.
      SS     = z * sigma * sqrt(L)
      ROP    = mu * L + SS
      target = mu * (L + 1) + SS
      발주량  = max(0, target - on_hand)
      z      = {NORMAL 1.28, CAUTION 1.65, WARNING 2.05, CRITICAL 2.33}
      L      = 실증 리드타임 * {NORMAL 1.0, CAUTION 1.15, WARNING 1.3, CRITICAL 1.5}
  단 ai 는 이 선형식에 묶이지 않는다 — Croston/SBA/TSB 등으로 mu·sigma 를 개선하거나
  SS 자체를 분포 기반으로 산출해도 된다. 계약은 '최종 수치'만 요구한다.

  ※ status(CRITICAL/BELOW_ROP/WATCH/OK)는 ai 가 보내지 않는다.
    현재 재고(on_hand) 대비 상태 판정은 서빙 시점 관심사라 backend 가 파생한다.

실행
  AI_SERVING_URL=https://ai.example.dev DATABASE_URL=... python3 scripts/ai_policy_adapter.py
  (DRY_RUN=1 이면 검증·집계만 하고 DB 를 건드리지 않는다)
"""
import io
import json
import os
import sys
import urllib.request

import psycopg

REQUIRED = ("institutionId", "standardCode", "mu", "sigma", "leadTimeDays",
            "z", "SS", "ROP", "target", "orderRecommendation", "supplyRiskLevel")
VALID_LEVELS = {"NORMAL", "CAUTION", "WARNING", "CRITICAL"}


def fetch_ai_policy(base_url: str, timeout: int = 60) -> dict:
    url = base_url.rstrip("/") + "/api/v1/ai/order-recommendations"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (신뢰된 내부 URL)
        if r.status != 200:
            raise RuntimeError(f"AI 서빙 응답 {r.status}: {url}")
        return json.loads(r.read().decode("utf-8"))


def validate(payload: dict) -> list[dict]:
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("응답에 items 배열이 없거나 비어 있음")
    bad = []
    for i, it in enumerate(items):
        missing = [k for k in REQUIRED if k not in it]
        if missing:
            bad.append(f"[{i}] 누락 필드 {missing}")
            continue
        if it["supplyRiskLevel"] not in VALID_LEVELS:
            bad.append(f"[{i}] supplyRiskLevel 값 오류: {it['supplyRiskLevel']}")
        for k in ("mu", "sigma", "leadTimeDays", "z", "SS", "ROP", "target", "orderRecommendation"):
            try:
                float(it[k])
            except (TypeError, ValueError):
                bad.append(f"[{i}] {k} 가 수치가 아님: {it[k]!r}")
        if len(bad) > 20:
            bad.append("... (이하 생략)")
            break
    if bad:
        raise ValueError("AI 응답 검증 실패:\n  " + "\n  ".join(bad))
    return items


def apply_to_db(dsn: str, items: list[dict]) -> int:
    """AI 수치를 inventory 에 반영. status 는 현재 on_hand 대비 backend 가 파생한다."""
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        # Neon pooled(PgBouncer)는 세션을 재사용하므로 선drop + ON COMMIT DROP 로 재실행 안전성 확보.
        cur.execute("DROP TABLE IF EXISTS _aipol")
        cur.execute("""CREATE TEMP TABLE _aipol (institution_id TEXT, standard_code TEXT,
            mu DOUBLE PRECISION, sigma DOUBLE PRECISION, z_used DOUBLE PRECISION,
            lead_time_used DOUBLE PRECISION, ss DOUBLE PRECISION, rop DOUBLE PRECISION,
            target DOUBLE PRECISION, order_recommendation INT, supply_risk_level TEXT)
            ON COMMIT DROP""")
        buf = io.StringIO()
        for it in items:
            buf.write(",".join(str(v) for v in (
                it["institutionId"], it["standardCode"], float(it["mu"]), float(it["sigma"]),
                float(it["z"]), float(it["leadTimeDays"]), float(it["SS"]), float(it["ROP"]),
                float(it["target"]), int(round(float(it["orderRecommendation"]))),
                it["supplyRiskLevel"])) + "\n")
        buf.seek(0)
        with cur.copy("COPY _aipol FROM STDIN WITH (FORMAT CSV)") as cp:
            cp.write(buf.read())

        # status 파생 규칙은 기존 서빙 계약과 동일하게 유지한다(on_hand 기준).
        cur.execute("""
            UPDATE inventory i SET
                mu=a.mu, sigma=a.sigma, z_used=a.z_used, lead_time_used=a.lead_time_used,
                ss=a.ss, rop=a.rop, target=a.target,
                order_recommendation=a.order_recommendation,
                supply_risk_level=a.supply_risk_level,
                status = CASE
                    WHEN i.on_hand <= 0        THEN 'CRITICAL'
                    WHEN i.on_hand <  a.rop    THEN 'BELOW_ROP'
                    WHEN i.on_hand <  a.rop*1.2 THEN 'WATCH'
                    ELSE 'OK' END,
                updated_at=now()
            FROM _aipol a
            WHERE i.institution_id=a.institution_id AND i.standard_code=a.standard_code""")
        n = cur.rowcount
        conn.commit()
        return n


def main() -> None:
    ai_url = os.environ.get("AI_SERVING_URL")
    if not ai_url:
        sys.exit(
            "AI_SERVING_URL 미설정 — ai 서빙 API 가 아직 배포되지 않았다면 정상입니다.\n"
            "그동안은 임시 계산 스크립트를 사용하세요:\n"
            "    python3 scripts/fix_inventory_stats.py\n"
            "이관 상태는 ai#23 에서 추적합니다."
        )
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        sys.exit("DATABASE_URL 미설정")

    payload = fetch_ai_policy(ai_url)
    items = validate(payload)
    model = payload.get("model", {})
    print(f"AI 응답 수신: {len(items):,}건 · asOf={payload.get('asOf')} "
          f"· model={model.get('name')} v{model.get('version')}")

    if os.environ.get("DRY_RUN"):
        lv: dict[str, int] = {}
        for it in items:
            lv[it["supplyRiskLevel"]] = lv.get(it["supplyRiskLevel"], 0) + 1
        print(f"[DRY_RUN] DB 미반영. 위험레벨 분포: {lv}")
        return

    n = apply_to_db(dsn, items)
    print(f"inventory updated: {n:,} rows (source=ai)")


if __name__ == "__main__":
    main()
