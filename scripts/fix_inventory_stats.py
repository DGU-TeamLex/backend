#!/usr/bin/env python3
"""inventory 통계 교정 + 메타코드 적재 (2026-07-17).

기존 scripts/import_ssis_dataset.py 의 두 가지 결함을 교정한다.

[결함 1] mu/sigma 가 약 8배 과대 — 결측일 0 미복원
  원본 데이터는 '거래가 있는 날만 행이 존재'하는 희소 패널이다(시계열당 관측
  중앙값 11일 / 731일, 731일 모두 존재하는 시계열은 0%). 그런데 기존 코드의
  Welford 누적은 파일에 존재하는 행만 세어 사실상 '거래한 날의 평균'을 구했다.
      실측: mu 평균 12.77(기존) vs 1.95(0복원) → 7.9배 과대
  → 본 스크립트는 Σx, Σx² 와 pair 최초등장일을 모아 분모를 T(최초등장~기간말)
    로 두고 계산한다(결측일 = 수요 0). ai#17 "mu 결측일 0 복원 보정" 대응.

[결함 2] 리드타임이 상수 1일 — "원본에 없다"는 전제가 틀림
  기존 docstring 은 "리드타임(L)은 원본 데이터에 없어 가정값"이라 했으나,
  원본에 `이전최종재고량`(당일 거래 전 재고)이 있어 '입고 시점에 재고가 0이었나'
  를 정확히 판정할 수 있다(정합성 검증: 직전행 마감재고 == 당일 이전최종재고 100%).
      입고 739,421건 중 249,220건(33.7%)이 이미 품절 상태에서 입고됨
      품절→입고 시차: P10=15일 / P50=36일 / P90=77일 (표본 92,493)
  → 품목별 실측 중앙값을 L 로 사용(94% 매칭, 미매칭은 전체 중앙값 35일).

  ※ 주의(선택편향): 이 L 은 상한이다. 표본이 '품절이 발생한 케이스'만 잡히고
    (정상 보충된 건은 표본에 없음), 값 자체가 [발주지연 + 순수 리드타임] 이다.
    순수 공급 리드타임은 P10~P25(12~15일) 쪽에 가깝다. 보수적 기준을 원하면
    현재값(중앙값), 낙관적 기준을 원하면 L_POLICY='p25' 로 바꾼다.

[추가] supply_risk_level 을 메타코드로 실채움 — 기존엔 전 행 NORMAL 이었다.
  seed_db.py 의 z_for()/lt_mult() 커플링(NORMAL 1.28/1.0 ~ CRITICAL 2.33/1.5)은
  이미 구현돼 있었으나 목업 RISK_BY_GROUP 이 먹이고 있었다. data 레포 PR#1 의
  raw_material_risk_meta_code 로 실제 레벨을 부여한다. ai#20 "공급위험↑ 시
  z·LT 동적 상향" 대응.

실행:
  DATABASE_URL=... STOCK_PARQUET=/path/물품재고_정규화완료.parquet \\
  META_DIR=/path/wep-stock-data-normalization/output_full \\
  python3 scripts/fix_inventory_stats.py
"""
import io
import os
import sys

import numpy as np
import pandas as pd
import psycopg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from routers.institutions_data import INSTITUTIONS

END = pd.Timestamp("2025-12-31")
L_POLICY = os.environ.get("L_POLICY", "median")  # median(보수) | p25(낙관)

# 공급리스크 메타코드 → 백엔드 4단계 레벨. 근거는 data PR#1 meta_code_glossary.
RISK_LEVEL = {
    "API_IMPORT_DEPENDENCY_CN_IN": "CRITICAL",           # 자급률 11.9~25.6%, 중국·인도 50%+
    "BIOLOGICS_FOREIGN_ORIGIN_DEPENDENCY": "CRITICAL",   # 백신 원액 해외, 국내는 충전·포장만
    "DOMESTIC_OLIGOPOLY_CONCENTRATION": "WARNING",       # 수액제 2개사 80%
    "MIDEAST_NAPHTHA_PETROCHEM_SHOCK": "WARNING",        # 2026-04 실사례 진행중
    "SEA_NATURAL_RUBBER_ORIGIN_CONCENTRATION": "WARNING",
    "CHINA_VITAMIN_RAWMATERIAL_CONCENTRATION": "WARNING",
    "CHINA_SPECIALTY_CHEM_IMPORT": "WARNING",
    "RARE_ELEMENT_ORIGIN_CONCENTRATION": "WARNING",
    "PULP_TIMBER_SUPPLY_DISRUPTION": "CAUTION",
    "AGRI_COMMODITY_PRICE_VOLATILITY": "CAUTION",
    "COTTON_COMMODITY_PRICE_VOLATILITY": "CAUTION",
    "HANBANG_MULTISOURCE_ORIGIN_RISK": "CAUTION",
    "PRECIOUS_METAL_COMPONENT_DEPENDENCY": "CAUTION",
    "MINERAL_RAWMATERIAL_GENERIC": "CAUTION",
}
RANK = {"NORMAL": 0, "CAUTION": 1, "WARNING": 2, "CRITICAL": 3}
Z = {"NORMAL": 1.28, "CAUTION": 1.65, "WARNING": 2.05, "CRITICAL": 2.33}
LT = {"NORMAL": 1.0, "CAUTION": 1.1, "WARNING": 1.25, "CRITICAL": 1.5}


def worst_level(codes: str) -> str:
    best = "NORMAL"
    for c in str(codes).split(";"):
        lv = RISK_LEVEL.get(c.strip(), "NORMAL")
        if RANK[lv] > RANK[best]:
            best = lv
    return best


def compute_stats(parquet: str) -> pd.DataFrame:
    """0복원 mu/sigma + 품목별 실증 리드타임 + 최근 재고."""
    df = pd.read_parquet(parquet, columns=[
        "물품코드", "보건기관코드_en", "재고마감일", "정상출고량",
        "마감재고량", "이전최종재고량", "입고량"])

    # --- mu/sigma: 분모를 T(최초등장~기간말)로 두어 결측일을 수요 0 으로 복원 ---
    x = df["정상출고량"].astype("float64")
    g = df.assign(x=x, x2=x * x).groupby(["물품코드", "보건기관코드_en"], observed=True).agg(
        sx=("x", "sum"), sx2=("x2", "sum"), first=("재고마감일", "min"))
    T = ((END - g["first"]).dt.days + 1).clip(lower=1)
    g["mu"] = g["sx"] / T
    g["sigma"] = np.sqrt(((g["sx2"] / T) - g["mu"] ** 2).clip(lower=0))

    # --- 리드타임: 재고 0 상태에서 입고된 건의 '품절 지속일수' ---
    d = df.sort_values(["물품코드", "보건기관코드_en", "재고마감일"])
    d["k"] = pd.factorize(d["물품코드"].astype(str) + "|" + d["보건기관코드_en"].astype(str))[0]
    d["prev_date"] = d.groupby("k", sort=False)["재고마감일"].shift()
    so = d[(d["입고량"] > 0) & (d["이전최종재고량"] == 0)].copy()
    so["lag"] = (so["재고마감일"] - so["prev_date"]).dt.days
    so = so[(so["lag"] > 0) & (so["lag"] <= 365)]
    q = 0.25 if L_POLICY == "p25" else 0.5
    l_item = so.groupby("물품코드")["lag"].quantile(q)
    l_default = so["lag"].quantile(q)

    last = df.sort_values("재고마감일").groupby(
        ["물품코드", "보건기관코드_en"], observed=True)["마감재고량"].last()

    out = g[["mu", "sigma"]].copy()
    out["on_hand"] = last
    out = out.reset_index()
    out["L_emp"] = out["물품코드"].map(l_item).fillna(l_default)
    return out


def main():
    parquet = os.environ["STOCK_PARQUET"]
    meta_dir = os.environ["META_DIR"]
    out = compute_stats(parquet)

    # 익명 기관코드 → 실 기관 ID (import_ssis_dataset.py 와 동일한 정렬 1:1 매핑)
    anon = sorted(out["보건기관코드_en"].dropna().unique())
    real = sorted(i["id"] for i in INSTITUTIONS)
    out["institution_id"] = out["보건기관코드_en"].map(dict(zip(anon, real)))
    out = out.dropna(subset=["institution_id"]).rename(columns={"물품코드": "standard_code"})

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        cur = conn.cursor()

        # ---- 메타코드 사전 + 매핑 적재(물품명 조인) ----
        gl = pd.read_csv(f"{meta_dir}/meta_code_glossary_full.csv", encoding="utf-8-sig").fillna("")
        cur.execute("TRUNCATE material_meta_codes")
        buf = io.StringIO()
        gl[["meta_code", "category", "description", "supply_stage",
            "supply_stage_note", "stage_confidence"]].to_csv(buf, index=False, header=False)
        buf.seek(0)
        with cur.copy("COPY material_meta_codes (meta_code,category,description,supply_stage,"
                      "supply_stage_note,stage_confidence) FROM STDIN WITH (FORMAT CSV)") as cp:
            cp.write(buf.read())

        mp = pd.read_csv(f"{meta_dir}/item_material_event_mapping_full.csv", encoding="utf-8-sig",
                         usecols=["representative_name", "item_family_id_suggested",
                                  "standard_family_name_suggested", "family_basis", "supply_cluster_id",
                                  "raw_material_meta_code", "raw_material_risk_meta_code",
                                  "demand_risk_meta_code", "material_confidence",
                                  "activity_scope"]).fillna("")
        cur.execute("SELECT standard_code, standard_name FROM standard_items")
        items = pd.DataFrame(cur.fetchall(), columns=["standard_code", "standard_name"])
        j = items.merge(mp, left_on="standard_name", right_on="representative_name",
                        how="inner").drop_duplicates("standard_code")
        cur.execute("TRUNCATE item_meta_map")
        cols = ["standard_code", "item_family_id_suggested", "standard_family_name_suggested",
                "family_basis", "supply_cluster_id", "raw_material_meta_code",
                "raw_material_risk_meta_code", "demand_risk_meta_code",
                "material_confidence", "activity_scope"]
        buf = io.StringIO()
        j[cols].to_csv(buf, index=False, header=False)
        buf.seek(0)
        with cur.copy("COPY item_meta_map (standard_code,item_family_id,standard_family_name,family_basis,"
                      "supply_cluster_id,raw_material_meta_code,raw_material_risk_meta_code,"
                      "demand_risk_meta_code,material_confidence,activity_scope) "
                      "FROM STDIN WITH (FORMAT CSV)") as cp:
            cp.write(buf.read())
        print(f"meta: dict={len(gl)} map={len(j)} ({len(j)/len(items)*100:.1f}% of standard_items)")

        # ---- 공급위험 레벨 + C↔D 커플링 반영해 inventory 재계산 ----
        risk = j[["standard_code", "raw_material_risk_meta_code"]].copy()
        risk["level"] = risk["raw_material_risk_meta_code"].apply(worst_level)
        out2 = out.merge(risk[["standard_code", "level"]], on="standard_code", how="left")
        out2["level"] = out2["level"].fillna("NORMAL")

        mu = out2["mu"].clip(lower=0.5)
        sg = out2["sigma"].clip(lower=0.1)
        z = out2["level"].map(Z)
        L = (out2["L_emp"].clip(lower=1.0) * out2["level"].map(LT))
        ss = (z * sg * np.sqrt(L)).round(1)
        rop = (mu * L + ss).round(1)
        tgt = (mu * (L + 1.0) + ss).round(1)
        out2 = out2.assign(
            mu_=mu.round(2), sg_=sg.round(2), z_=z, L_=L.round(1), ss_=ss, rop_=rop, tgt_=tgt,
            ord_=(tgt - out2["on_hand"]).clip(lower=0).round().astype(int),
            st_=np.where(out2["on_hand"] <= 0, "CRITICAL",
                np.where(out2["on_hand"] < rop, "BELOW_ROP",
                np.where(out2["on_hand"] < rop * 1.2, "WATCH", "OK"))))

        cur.execute("""CREATE TEMP TABLE _fix (institution_id TEXT, standard_code TEXT,
            mu DOUBLE PRECISION, sigma DOUBLE PRECISION, z_used DOUBLE PRECISION,
            lead_time_used DOUBLE PRECISION, ss DOUBLE PRECISION, rop DOUBLE PRECISION,
            target DOUBLE PRECISION, order_recommendation INT, supply_risk_level TEXT, status TEXT)""")
        buf = io.StringIO()
        out2[["institution_id", "standard_code", "mu_", "sg_", "z_", "L_", "ss_", "rop_",
              "tgt_", "ord_", "level", "st_"]].to_csv(buf, index=False, header=False)
        buf.seek(0)
        with cur.copy("COPY _fix FROM STDIN WITH (FORMAT CSV)") as cp:
            cp.write(buf.read())
        cur.execute("""UPDATE inventory i SET mu=f.mu, sigma=f.sigma, z_used=f.z_used,
            lead_time_used=f.lead_time_used, ss=f.ss, rop=f.rop, target=f.target,
            order_recommendation=f.order_recommendation, supply_risk_level=f.supply_risk_level,
            status=f.status, updated_at=now()
            FROM _fix f WHERE i.institution_id=f.institution_id AND i.standard_code=f.standard_code""")
        print(f"inventory updated: {cur.rowcount:,} rows (L_POLICY={L_POLICY})")
        conn.commit()


if __name__ == "__main__":
    main()
