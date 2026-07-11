"""모듈 B — 수요 예측 (실데이터 기반 월별 분포 예측).

이전엔 고정 MOCK 2건(`routers/wep_data.py:FORECASTS`)을 그대로 반환했다.
이 모듈은 그것을 배포 DB 의 실데이터로 대체한다.

## 데이터 제약 (중요 — 이슈 #21 대비 이번 구현 범위)
배포된 Postgres(`inventory` 테이블)에는 품목×기관별 **일별 수요의 평균(`mu`)·표준편차
(`sigma`)** 만 저장돼 있다(SSIS 실거래 이력에서 산출, `scripts/import_ssis_dataset.py`
line 13, 251-253 참고). **일별/월별 원계열 자체는 배포 DB 에 없다** — 원계열은 적재
스크립트 실행 시점에만 존재하고 집계값(mu/sigma)만 DB 에 남는다.

따라서 이번 구현은 `mu`/`sigma` 로부터 **월별 수요 분포를 정규근사로 산출하는 분포 예측**
이며, 이슈 #21 이 지목한 Croston/SBA/TSB 처럼 **일별 간헐수요 원계열을 학습하는 모델이
아니다**. 학습형 모델과 재고 시뮬레이터 기반 평가(이슈 #21 항목 2·3)는 일별 원계열을
DB 에 적재하는 스키마 변경이 선행돼야 하며, 후속 작업으로 남긴다(PR 본문에 명시).

## 산출 방식
일별 수요를 독립으로 가정하면 D일 누적 수요의 평균은 `mu·D`, 분산은 `sigma^2·D`
(중심극한정리로 월 누적은 근사적으로 정규). 월별 분위수는 표준정규 분위수로 얻는다.
- mean = mu · (해당 월 일수)
- q50  = mean (정규 중앙값)
- q10  = max(0, mean - z90·sd),  q90 = mean + z90·sd,  sd = sigma·sqrt(일수)
`patternClass` 는 변동계수 CV=sigma/mu 로 SMOOTH/ERRATIC/LUMPY 를 구분한다(일별
0-수요 비율을 알 수 없어 Syntetos-Boylan ADI/CV² 사분면이 아닌 CV 단일 휴리스틱).
"""
import datetime
import math

# 표준정규 90분위 (= 10분위의 대칭). 적재 스크립트의 Z_NORMAL(1.28)과 동일 계열 근거.
_Z90 = 1.2815515594
_DAYS_IN_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def _days_in_month(year: int, month: int) -> int:
    if month == 2 and (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
        return 29
    return _DAYS_IN_MONTH[month - 1]


def _next_months(n: int, today: datetime.date | None = None) -> list[tuple[int, int]]:
    """이번 달부터 n개월치 (year, month) 목록."""
    today = today or datetime.date.today()
    year, month = today.year, today.month
    out = []
    for _ in range(n):
        out.append((year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return out


def _pattern_class(mu: float, sigma: float) -> str:
    cv = sigma / mu if mu > 0 else 0.0
    if cv < 0.75:
        return "SMOOTH"
    if cv < 1.25:
        return "ERRATIC"
    return "LUMPY"


def forecast_for(row: dict, horizon: int = 3, today: datetime.date | None = None) -> dict:
    """단일 (기관,품목) 재고행(mu/sigma 포함) → 예측 dict.

    REST(`routers/wep_stock.py`)·GraphQL(`routers/graphql_schema.py`)이 공유하는 계약과
    동일한 키(camelCase, horizon 포인트: month/mean/q10/q50/q90/confidence)를 반환한다.
    입력 row 는 `db.queries.forecast_inputs()`/`forecast_input_one()` 의 반환 형식이다.
    """
    mu = max(0.0, float(row["mu"]))
    sigma = max(0.0, float(row["sigma"]))
    cv = sigma / mu if mu > 0 else 0.0
    # CV 가 낮을수록(변동 작을수록) 신뢰도 높게 — [0.3, 0.9] 로 클램프한 단순 휴리스틱.
    confidence = round(max(0.3, min(0.9, 1.0 / (1.0 + cv))), 2)

    points = []
    for (year, month) in _next_months(horizon, today):
        days = _days_in_month(year, month)
        mean = mu * days
        sd = sigma * math.sqrt(days)
        q10 = max(0.0, mean - _Z90 * sd)
        q90 = mean + _Z90 * sd
        points.append({
            "month": f"{year:04d}-{month:02d}",
            "mean": round(mean, 1),
            "q10": int(round(q10)),
            "q50": int(round(mean)),
            "q90": int(round(q90)),
            "confidence": confidence,
        })

    return {
        "institutionId": row["institutionId"],
        "standardCode": row["standardCode"],
        "patternClass": _pattern_class(mu, sigma),
        # 학습형 챔피언 모델이 아니라 집계통계(mu/sigma) 기반 정규근사임을 명시.
        "championModel": "AGG_NORMAL",
        "modelVersion": "b-dist-2026.07",
        # 일별 원계열 부재 — 집계값만으로 산출했음을 프론트/검수자에게 알리는 플래그.
        "dataQualityFlag": "aggregate_only",
        "horizon": points,
    }


def forecasts_for(rows: list[dict], horizon: int = 3, today: datetime.date | None = None) -> list[dict]:
    return [forecast_for(r, horizon=horizon, today=today) for r in rows]
