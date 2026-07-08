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
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (institution_id, standard_code)
);
CREATE INDEX IF NOT EXISTS idx_inventory_institution ON inventory(institution_id);
CREATE INDEX IF NOT EXISTS idx_inventory_status ON inventory(status);

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
