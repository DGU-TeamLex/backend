-- WeP-Stock 핵심 스키마 (Neon Postgres, Vercel Marketplace)
-- 범위: 기관(실데이터) · 표준품목/품목군 · 재고 · 알림
-- 예측(B)/공급위험(C)/외부지표/인테이크/표준화검수는 이번 단계에서 제외(시드 데이터 유지).

CREATE TABLE IF NOT EXISTS item_groups (
    item_group_id TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS standard_items (
    standard_item_id TEXT PRIMARY KEY,
    standard_code TEXT UNIQUE NOT NULL,
    standard_name TEXT NOT NULL,
    item_group_id TEXT NOT NULL REFERENCES item_groups(item_group_id),
    uom TEXT NOT NULL,
    shelf_life_days INTEGER,
    criticality TEXT NOT NULL
);

-- 전국 지역보건의료기관 현황 (보건복지부, 2022-12-31) — 실데이터 3,598곳
CREATE TABLE IF NOT EXISTS institutions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    category TEXT NOT NULL,      -- 보건소 / 보건지소 / 보건진료소
    sido TEXT NOT NULL,
    sigungu TEXT NOT NULL,
    island BOOLEAN NOT NULL DEFAULT FALSE,
    parent TEXT,
    address TEXT,
    eupmyeondong TEXT,
    phone TEXT
);
CREATE INDEX IF NOT EXISTS idx_institutions_region ON institutions(sido, sigungu);
CREATE INDEX IF NOT EXISTS idx_institutions_category ON institutions(category);

-- 기관 x 표준품목 재고 (모듈 D: SS/ROP/발주권고)
CREATE TABLE IF NOT EXISTS inventory (
    id BIGSERIAL PRIMARY KEY,
    institution_id TEXT NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
    standard_code TEXT NOT NULL REFERENCES standard_items(standard_code),
    on_hand INTEGER NOT NULL,
    available INTEGER NOT NULL,
    mu DOUBLE PRECISION NOT NULL,
    sigma DOUBLE PRECISION NOT NULL,
    lead_time_used DOUBLE PRECISION NOT NULL,
    z_used DOUBLE PRECISION NOT NULL,
    ss DOUBLE PRECISION NOT NULL,
    rop DOUBLE PRECISION NOT NULL,
    target DOUBLE PRECISION NOT NULL,
    -- ai 정책(inventory-status-v1.1)은 판단 불가 건에 NULL 을 요구한다.
    --   DATA_MISSING(재고 기재 누락 의심) · STALE(관측이 오래됨) → 권고량 산출 불가 = NULL
    --   DORMANT / NOT_OPERATED                                  → 발주 대상 아님 = 0
    -- 0 과 NULL 을 구분하지 않으면 "발주 안 함"과 "모르겠음"이 화면에서 같아진다.
    order_recommendation INTEGER,
    supply_risk_level TEXT NOT NULL,
    -- OK / WATCH / BELOW_ROP / CRITICAL / EXCLUDED
    --   EXCLUDED(2026-07-28, ai#38): 재고가 0 이지만 결품이 아닌 건.
    --     해당 기관이 취급하지 않거나(NOT_OPERATED) 데이터가 누락된(DATA_MISSING) 품목으로,
    --     사유는 zero_stock_reason 컬럼에 있다. 판정·발주·알림 대상에서 뺀다.
    --     알림 쿼리는 status 화이트리스트(CRITICAL/BELOW_ROP)를 쓰므로 자동으로 제외되지만,
    --     on_hand=0 기준 집계는 별도로 걸러야 한다(db/queries.py stockout_items 참조).
    status TEXT NOT NULL,
    -- ai#25: 수요 성격 분류·절단보정 mu. 계산·적재 주체는 ai(소유권 경계: 스키마=backend, 데이터=ai).
    --   demand_class : DORMANT(재고 있었는데 미사용=진짜 무수요) / CENSORED(재고 없어 못 씀)
    --                  / ACTIVE(그 외). NULL = 아직 미적재.
    --   mu_corrected : 결품기간 절단편향을 보정한 일평균 수요(ai#24). NULL = 미적재.
    -- ⚠️ status 에는 아직 DORMANT 를 넣지 않는다 — 집계·정렬·프론트 라벨이 4값을 전제하므로
    --    별도 대응 후 2단계에서 반영한다.
    demand_class TEXT,
    mu_corrected DOUBLE PRECISION,
    -- 발주 억제 감사용(ai#52). 계산 결과를 덮어쓰기만 하면 왜 0/NULL 인지 되짚을 수 없다.
    --   raw_order_recommendation : 억제 전 원시 권고량
    --   order_suppress_reason    : DORMANT | NOT_OPERATED | DATA_MISSING | STALE
    raw_order_recommendation INTEGER,
    order_suppress_reason TEXT,
    -- 수요 모멘트에 바닥값이 적용됐는지. ai 정책은 이 플래그를 판정·예측·API 에 노출하도록 한다.
    mu_is_floored BOOLEAN,
    sigma_is_floored BOOLEAN,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (institution_id, standard_code)
);
CREATE INDEX IF NOT EXISTS idx_inventory_institution ON inventory(institution_id);
CREATE INDEX IF NOT EXISTS idx_inventory_status ON inventory(status);
-- idx_inventory_demand_class 제거 (2026-07-30).
--   demand_class 는 값이 3종(DORMANT/CENSORED/ACTIVE)뿐인 저카디널리티 컬럼이고,
--   조회 경로에서 WHERE 절로 쓰이지 않는다. 실측 스캔 10회 / 16MB.
--   Neon 무료 한도 512MB 중 354MB 를 쓰던 상황이라 회수했다.
--   되살리려면: CREATE INDEX idx_inventory_demand_class ON inventory(demand_class);

-- 사용자 (인증/RBAC). 공개 가입 없음 — 관리자가 미리 생성(scripts/seed_users.py).
-- role: CENTRAL(중앙관리자, 전 기관 조회) / INSTITUTION(개별 보건기관 담당자, institution_id 로 스코프)
-- institution_id 는 의도적으로 FK 를 걸지 않는다 — scripts/seed_db.py 가 institutions 를
-- 주기적으로 TRUNCATE ... CASCADE 로 재적재하는데(실데이터 갱신 시 재실행됨), FK 를 걸면
-- 그 CASCADE 에 users 테이블까지 딸려가 계정이 통째로 삭제된다.
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    institution_id TEXT,
    -- is_active=false 면 관리자 콘솔에서 비활성화된 계정 — 로그인 거부(이슈 #25 PATCH).
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- 기존(이미 CREATE 된) DB 도 컬럼을 얻도록 멱등 마이그레이션. seed_db.py 가 schema.sql
-- 전체를 실행하므로 재적재 시 자동 반영된다.
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true;
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- 적재 배치 이력 (데이터 인테이크). scripts/import_ssis_dataset.py 등 실제
-- 적재 스크립트가 실행될 때마다 이 테이블에 실행 기록을 남긴다(더 이상 목업 아님).
CREATE TABLE IF NOT EXISTS import_batches (
    import_batch_id TEXT PRIMARY KEY,
    file_name TEXT NOT NULL,
    source_vendor TEXT,
    status TEXT NOT NULL,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    total_rows INTEGER NOT NULL,
    valid_rows INTEGER NOT NULL,
    error_rows INTEGER NOT NULL,
    mapping_rate DOUBLE PRECISION NOT NULL,
    period_start TEXT,
    period_end TEXT
);

-- 알림 (재고미달 등). 재고 행 상태 변화로부터 파생되며, resolved_at 갱신이 실제 DB 상태로 남는다.
CREATE TABLE IF NOT EXISTS alerts (
    alert_id TEXT PRIMARY KEY,
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    institution_id TEXT REFERENCES institutions(id) ON DELETE CASCADE,
    standard_code TEXT,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_alerts_institution ON alerts(institution_id);
CREATE INDEX IF NOT EXISTS idx_alerts_resolved ON alerts(resolved_at);

-- ===== 메타코드 3축 (data 레포 PR#1: wep-stock-data-normalization) =====
-- 원재료(무엇으로 만들었나) · 공급리스크(왜 위험한가) · 수요트리거(언제 튀나)
CREATE TABLE IF NOT EXISTS material_meta_codes (
    meta_code TEXT PRIMARY KEY,
    category TEXT NOT NULL,              -- raw_material / raw_material_risk / demand_risk
    description TEXT NOT NULL,
    supply_stage TEXT,                   -- 원물/원광/정제·가공/합성/생물유래/제조부품
    supply_stage_note TEXT,
    stage_confidence TEXT                -- confirmed / assumed_synth / n/a
);
CREATE INDEX IF NOT EXISTS idx_mmc_category ON material_meta_codes(category);

-- 표준품목 → 메타코드 매핑.
-- 조인 키는 물품명(표준물품명) 이다 — 보건의료정보부 회의(2026-07-14) 결정사항:
-- "USE 계열 코드는 보건소별로 일련번호를 각자 부여해 동일 코드에 다른 물품이 매핑되므로,
--  물품코드를 무시하고 물품명 기준으로 정리한다". data 레포의 representative_item_id
-- (ITEM_<hash>) 와 본 DB 의 standard_code 는 체계가 달라 ID 로는 조인되지 않는다.
CREATE TABLE IF NOT EXISTS item_meta_map (
    standard_code TEXT PRIMARY KEY REFERENCES standard_items(standard_code) ON DELETE CASCADE,
    item_family_id TEXT,
    standard_family_name TEXT,
    family_basis TEXT,                   -- 근거 티어(공식표>괄호추출>웹검색>일반지식>미상)
    supply_cluster_id TEXT,
    raw_material_meta_code TEXT,         -- 다중코드는 ';' 구분
    raw_material_risk_meta_code TEXT,
    demand_risk_meta_code TEXT,
    material_confidence TEXT,            -- identified / group_coarse / unspecified
    activity_scope TEXT                  -- active_high / active_low / one_off
);
CREATE INDEX IF NOT EXISTS idx_imm_cluster ON item_meta_map(supply_cluster_id);
CREATE INDEX IF NOT EXISTS idx_imm_conf ON item_meta_map(material_confidence);
CREATE INDEX IF NOT EXISTS idx_imm_scope ON item_meta_map(activity_scope);

-- ===== 약성분 (#65) — 2026-07-28 3차 수신 =====
-- 원본: (한국사회보장정보원) ... 데이터셋(약성분)_수정.DAT, 8컬럼 / 3,576,320행.
-- 실측: 기관 3,861 × 약품코드 80,934, 성분코드 13,223종.
--   (보건기관코드_en, 약품코드) 는 전수 유니크(3,576,320 = 행수) 이므로 그대로 PK 로 쓴다.
-- 조인키는 무변환: 약품코드 = 물품재고의 물품코드 = standard_items.standard_code.
-- ⚠️ 정의서 Data5 시트는 10컬럼(`사용시작일자`·`사용종료일자` 포함)으로 기재하나
--    실제 파일에는 두 컬럼이 없다. 날짜 기반 취급여부 판별은 설계에서 제외한다.
-- 적재 주체는 ai (소유권 경계: 스키마=backend, 데이터=ai).
CREATE TABLE IF NOT EXISTS drug_ingredients (
    institution_code TEXT NOT NULL,      -- 보건기관코드_en (익명화 코드 원본)
    drug_code TEXT NOT NULL,             -- 약품코드 (= standard_items.standard_code)
    drug_name TEXT,                      -- 약품명1
    usage_division TEXT,                 -- 용도구분: 진료약 95.9% / 접종약 3.1% / 결핵약 / 영양제
    drug_kind TEXT,                      -- 약종류구분: 경구 75.0% / 외용 12.0% / 주사 8.2%
    drug_unit TEXT,                      -- 약품단위1
    ingredient_code TEXT,                -- 성분코드 (행 단위 결측 12.75%)
    ingredient_name TEXT,                -- 성분명
    PRIMARY KEY (institution_code, drug_code)
);
CREATE INDEX IF NOT EXISTS idx_drug_ing_code ON drug_ingredients(drug_code);
CREATE INDEX IF NOT EXISTS idx_drug_ing_ingredient ON drug_ingredients(ingredient_code);
CREATE INDEX IF NOT EXISTS idx_drug_ing_usage ON drug_ingredients(usage_division, drug_kind);

-- 약품코드 canonical 성분 매핑 (기관 간 교차 보완 결과).
-- 행 단위 결측은 12.75% 이나, 같은 약품이라도 기관에 따라 채워진 곳이 있어
-- 약품코드 기준으로 합치면 87.49%(70,812/80,934)까지 외부 데이터 없이 자체 복구된다.
-- ai#43(is_medical 판정)·ai#45(성분군 계층)·pipeline#3(동일성분 매칭)이 이 테이블을 참조한다.
CREATE TABLE IF NOT EXISTS drug_ingredient_master (
    drug_code TEXT PRIMARY KEY,
    ingredient_code TEXT,                -- 교차 보완 후 대표 성분코드 (미확보 시 NULL)
    ingredient_name TEXT,
    usage_division TEXT,
    drug_kind TEXT,
    -- 한 약품코드에 성분코드가 2개 이상 관측된 경우(복합제 또는 이력 변경). 실측 72종.
    has_multiple_ingredients BOOLEAN NOT NULL DEFAULT FALSE,
    source_institution_count INTEGER NOT NULL DEFAULT 0   -- 성분코드를 제공한 기관 수
    -- ⚠️ standard_items 로의 FK 는 의도적으로 두지 않는다.
    --    약성분 파일의 약품코드는 80,934종인데 standard_items 는 17,148종(W품목 9,641)이라
    --    FK 를 걸면 카탈로그에 없는 약품이 전부 적재 실패한다. 조인은 애플리케이션에서
    --    standard_code 로 수행하고, 매칭 여부는 아래 인덱스로 확인한다.
);
CREATE INDEX IF NOT EXISTS idx_dim_ingredient ON drug_ingredient_master(ingredient_code);

-- ===== 일별 재고 시계열 (#63) =====
-- 기존 `inventory` 는 (institution_id, standard_code) 유니크 = 현재 스냅샷이라
-- 시간축·부서축이 없다. 롤링 백테스트 DB 재현·결측일 복원·폐기 지표·2018~19 적재가
-- 모두 불가하므로 원장을 그대로 담는 테이블을 신설한다.
--   2024~25: 16,265,602행(정의서) / 2018~19: 6,106,936행(정의서·실측 일치)
-- 기간 분리는 stock_date RANGE 파티션으로 처리한다. 2020~2023 은 기관 제공 불가가
-- 확정되어 파티션을 두지 않으며, 이 4년 공백은 영구 제약이다.
CREATE TABLE IF NOT EXISTS inventory_daily (
    institution_code TEXT NOT NULL,      -- 보건기관코드_en (익명화 원본 코드)
    dept_code TEXT NOT NULL DEFAULT '',  -- 부서코드
    standard_code TEXT NOT NULL,         -- 물품코드
    stock_date DATE NOT NULL,            -- 재고마감일
    prev_closing_qty NUMERIC,            -- 이전최종재고량
    closing_qty NUMERIC,                 -- 마감재고량
    -- 입고 3종
    qty_in NUMERIC,                      -- 입고량 (외부 구매)
    qty_in_transfer NUMERIC,             -- 불출입고량
    qty_in_return NUMERIC,               -- 반납입고량
    -- 출고 6종
    qty_out_transfer NUMERIC,            -- 불출출고량
    qty_out_normal NUMERIC,              -- 정상출고량 ★순수요 (ai#40)
    qty_out_return NUMERIC,              -- 반품출고량
    qty_out_disposal NUMERIC,            -- 폐기출고량
    qty_out_auto_disposal NUMERIC,       -- 자동폐기출고량 ※수지 미반영·수요 제외 (ai#42)
    qty_out_adjust NUMERIC,              -- 보정출고량
    -- 2018~19 파일(16컬럼)에는 없는 컬럼 → NULL
    purchase_place_code TEXT,            -- 구입처코드
    purchase_unit_price NUMERIC,         -- 구입단가
    -- ⚠️ PRIMARY KEY 를 두지 않는다.
    --    (institution_code, dept_code, standard_code, stock_date) 가 자연키로 보이지만
    --    원본이 유니크하지 않다. 2018~19 전수 실측:
    --      6,106,936행 / 고유키 6,103,735 → 중복키 2,955개, 초과 3,201행(0.052%)
    --      최대 8중복. 표본 140건 중 107건은 같은 키에 값이 다르다
    --      (예: 같은 기관·부서·물품·일자에 마감재고량이 서로 다른 두 행).
    --    PK 를 걸면 적재가 UniqueViolation 으로 실패하고, 임의로 하나만 남기면
    --    원본이 왜곡된다. 원장 보존이 목적이므로 인덱스만 둔다.
    --    중복 해석(정정 이력인지 분할 기록인지)은 정보원 확인 필요.
    load_batch_id TEXT                   -- 적재 배치 식별자(재적재 시 범위 삭제용)
) PARTITION BY RANGE (stock_date);

CREATE TABLE IF NOT EXISTS inventory_daily_2018_2019 PARTITION OF inventory_daily
    FOR VALUES FROM ('2018-01-01') TO ('2020-01-01');
CREATE TABLE IF NOT EXISTS inventory_daily_2024_2025 PARTITION OF inventory_daily
    FOR VALUES FROM ('2024-01-01') TO ('2026-01-01');

-- 인덱스는 조회 패턴에 꼭 필요한 2개만 둔다.
-- 2,240만 행 규모에서는 인덱스 하나가 초기 적재 시간을 크게 늘린다
-- (실측: 인덱스 유지하며 COPY 시 610만 행에 20분 이상).
-- 대량 최초 적재는 인덱스를 지운 뒤 넣고 마지막에 다시 만드는 편이 빠르다.
CREATE INDEX IF NOT EXISTS idx_inv_daily_item_date ON inventory_daily(standard_code, stock_date);
CREATE INDEX IF NOT EXISTS idx_inv_daily_inst_date ON inventory_daily(institution_code, stock_date);

-- 과거(2018~19) 전용 품목 플래그 (#63).
-- 2018~19 신규 품목 2,707종(W 2,155 / O 523 / 기타 29)은 현재 재고 화면에
-- 노출되면 안 되므로 카탈로그에 플래그를 둔다.
ALTER TABLE standard_items ADD COLUMN IF NOT EXISTS historical_only BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_std_items_historical ON standard_items(historical_only);

-- ── 기존 DB 반영용 멱등 DDL ──────────────────────────────────────────
-- CREATE TABLE IF NOT EXISTS 는 이미 있는 테이블을 바꾸지 않으므로 별도로 적용한다.
ALTER TABLE inventory ALTER COLUMN order_recommendation DROP NOT NULL;
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS raw_order_recommendation INTEGER;
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS order_suppress_reason TEXT;
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS mu_is_floored BOOLEAN;
ALTER TABLE inventory ADD COLUMN IF NOT EXISTS sigma_is_floored BOOLEAN;

-- ===== 기관 실명 표기 중단 → 보건기관코드_en 키 전환 (이슈 #75, #16) =====
-- institutions.id(inst_XXXX)는 익명 기관코드 3,530개를 보건복지부 실명목록과
-- '정렬 순서로 1:1 임의 매핑'한 값이라(scripts/import_ssis_dataset.py) 실제 신원과
-- 대응한다는 보장이 없고, 연도별 자료를 추가 적재하면 조용히 어긋난다(실측 재현율 0.71%).
-- 정보원이 원문으로 제공한 `보건기관코드_en`(익명화 코드 원문, 예: "D3;34")을 그대로
-- 보존해 화면·API 가 실명/지역 대신 이 코드를 안정적인 키로 쓸 수 있게 한다.
-- 값 채우기는 scripts/backfill_institution_code.py (기존 매핑의 '정렬 역산') 참고 —
-- 원장 재적재(#39) 전까지의 임시 조치이며, DB 재적재를 하지 않는다.
ALTER TABLE institutions ADD COLUMN IF NOT EXISTS institution_code TEXT;
CREATE INDEX IF NOT EXISTS idx_institutions_code ON institutions(institution_code);
