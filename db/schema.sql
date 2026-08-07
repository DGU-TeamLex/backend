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
    order_recommendation INTEGER NOT NULL,
    supply_risk_level TEXT NOT NULL,
    status TEXT NOT NULL,        -- OK / WATCH / BELOW_ROP / CRITICAL
    -- ai#25: 수요 성격 분류·절단보정 mu. 계산·적재 주체는 ai(소유권 경계: 스키마=backend, 데이터=ai).
    --   demand_class : DORMANT(재고 있었는데 미사용=진짜 무수요) / CENSORED(재고 없어 못 씀)
    --                  / ACTIVE(그 외). NULL = 아직 미적재.
    --   mu_corrected : 결품기간 절단편향을 보정한 일평균 수요(ai#24). NULL = 미적재.
    -- ⚠️ status 에는 아직 DORMANT 를 넣지 않는다 — 집계·정렬·프론트 라벨이 4값을 전제하므로
    --    별도 대응 후 2단계에서 반영한다.
    demand_class TEXT,
    mu_corrected DOUBLE PRECISION,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (institution_id, standard_code)
);
CREATE INDEX IF NOT EXISTS idx_inventory_institution ON inventory(institution_id);
CREATE INDEX IF NOT EXISTS idx_inventory_status ON inventory(status);
CREATE INDEX IF NOT EXISTS idx_inventory_demand_class ON inventory(demand_class);

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
