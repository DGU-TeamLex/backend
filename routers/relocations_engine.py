"""재배치 제안 엔진 (모듈 D) — 실데이터 기반.

부족 기관(status CRITICAL/BELOW_ROP)과 여유 기관(status OK, 재고가 target 초과)을
같은 표준품목(standardCode) 기준으로 매칭해 이전(재배치) 제안을 생성한다.
입력은 실데이터(inventory 테이블, db.queries.inventory_policy_rows)다 —
이전의 고정 MOCK 3건(wep_data.RELOCATIONS)을 대체한다(이슈 #26).

매칭 로직
  1. 부족(need = target - available > 0, status CRITICAL/BELOW_ROP)과
     여유(give = available - target > 0, status OK)를 품목별로 나눈다.
  2. 부족은 심각도(CRITICAL > BELOW_ROP) · need 큰 순으로 처리한다.
  3. 각 부족 기관은 같은 품목의 여유 기관 중 **같은 시도(권역 인접)** 를 우선,
     그다음 여유분이 큰 기관에서 채운다. 한 여유 기관의 초과분은 여러 부족
     기관에 소진될 때까지 재사용한다.
  4. 이전 수량 suggestedQty = min(need, 남은 give) (부족분을 target 까지만 채움).

한계(정직 표기)
  - FEFO(유효기간 임박분 우선 소진): inventory 행에 로트별 유효기간이 없어
    현재는 적용 불가 — 로트/유효기간 데이터 확보 후 반영 필요.
  - 기관 매핑 부정확성(#16): '보내는/받는 기관'명은 익명코드↔실명 임의매핑을
    물려받는다 — 재고 수치는 실데이터지만 어느 실제 기관인지는 근거 미확정.
"""
from collections import defaultdict

from db import queries as DB

# status 심각도 우선순위 (작을수록 시급)
_SEV_RANK = {"CRITICAL": 0, "BELOW_ROP": 1}


def _num(v) -> float:
    return float(v) if v is not None else 0.0


def _reason(to_status: str, same_region: bool, from_sido, to_sido) -> str:
    sev = "결품위험(CRITICAL)" if to_status == "CRITICAL" else "재주문점 이하(BELOW_ROP)"
    region = f"동일권역({to_sido})" if same_region else f"타권역({from_sido}→{to_sido})"
    return f"{sev} 기관에 여유분 이전 · {region}"


def compute_relocations(limit: int = 50) -> list:
    """실데이터 재고 현황에서 재배치 제안 목록(제안 상태)을 계산해 반환한다.

    반환 항목은 REST(/relocations)·GraphQL·대시보드가 공유하는 enriched dict 로,
    기존 MOCK 항목과 동일한 키(id/fromInstitution/toInstitution/fromName/toName/
    standardCode/standardName/suggestedQty/reason/status)를 유지한다."""
    # 부족(CRITICAL·BELOW_ROP)과 여유(OK) 행을 각각 조회한다. status 필터를 주면
    # 시급도 정렬 truncation 없이 해당 상태만 넉넉히 가져올 수 있다.
    shortages = (DB.inventory_policy_rows(status="CRITICAL", limit=3000)
                 + DB.inventory_policy_rows(status="BELOW_ROP", limit=3000))
    surplus_rows = DB.inventory_policy_rows(status="OK", limit=5000)

    short_by_code: dict = defaultdict(list)
    for r in shortages:
        need = int(round(_num(r.get("target")) - _num(r.get("available"))))
        if need > 0:
            short_by_code[r["standardCode"]].append((r, need))

    if not short_by_code:
        return []

    # 여유는 부족이 존재하는 품목만 남긴다. 각 항목은 남은 give 를 갱신하려 리스트로.
    surplus_by_code: dict = defaultdict(list)
    for r in surplus_rows:
        code = r["standardCode"]
        if code not in short_by_code:
            continue
        give = int(round(_num(r.get("available")) - _num(r.get("target"))))
        if give > 0:
            surplus_by_code[code].append([r, give])

    out: list = []
    for code, shorts in short_by_code.items():
        surplus = surplus_by_code.get(code)
        if not surplus:
            continue
        shorts.sort(key=lambda x: (_SEV_RANK.get(x[0]["status"], 9), -x[1]))
        for dst, need in shorts:
            remaining = need
            # 같은 시도 우선, 그다음 남은 여유분 큰 순
            cand = sorted(
                surplus,
                key=lambda s: (0 if s[0]["sido"] == dst["sido"] else 1, -s[1]),
            )
            for s in cand:
                if remaining <= 0:
                    break
                src, give = s[0], s[1]
                if give <= 0 or src["institutionId"] == dst["institutionId"]:
                    continue
                qty = min(remaining, give)
                same_region = src["sido"] == dst["sido"]
                out.append({
                    "id": f"rl_{code}_{src['institutionId']}_{dst['institutionId']}",
                    "fromInstitution": src["institutionId"],
                    "toInstitution": dst["institutionId"],
                    "fromName": src["institutionName"],
                    "toName": dst["institutionName"],
                    "standardCode": code,
                    "standardName": dst["standardName"],
                    "suggestedQty": int(qty),
                    "reason": _reason(dst["status"], same_region, src["sido"], dst["sido"]),
                    "status": "제안",
                    "fromStatus": src["status"],
                    "toStatus": dst["status"],
                })
                s[1] -= qty
                remaining -= qty

    # 시급도 · 이전 수량 큰 순으로 상위 limit 건
    out.sort(key=lambda x: (_SEV_RANK.get(x["toStatus"], 9), -x["suggestedQty"]))
    return out[:limit]
