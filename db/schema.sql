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

-- 기관별 원본 물품코드 ↔ 표준품목 크로스워크 (초안 — 아직 데이터 미적재).
--
-- 배경: SSIS 원본 데이터의 물품코드는 두 종류다 — 전국 공통 "공식코드"와, 기관이
-- 각자 임의로 붙이는 "USE코드"(AI 파트 정규화 작업 중 확인, 2026-07-12). USE코드는
-- 기관마다 독립적으로 부여되어 같은 코드 번호가 기관마다 다른 물품을 가리킬 수 있고,
-- 반대로 같은 물품이 기관마다 다른 코드로 등록돼 있을 수 있다. 표준품목(standard_items)
-- 으로 통합하면서 이 원본 (기관, 코드) 쌍을 버리면, 예측/알림 결과를 그 기관 자체
-- 시스템으로 되돌려줄 때 그 기관이 알아듣는 코드로 되돌릴 방법이 없어진다.
--
-- 따라서 원본 코드를 별도 테이블에 보존한다 — standard_items 는 "이 물품이 뭔지"를
-- 위한 전국 공통 카탈로그로, 이 테이블은 "이 기관은 이 물품을 이 코드로 부른다"를
-- 위한 기관별 별칭 테이블로 역할을 분리한다.
--
-- code_type 은 매핑 신뢰도 구분용: '공식코드'(전국 공통, 별도 매칭 불필요) vs
-- 'USE코드(규칙기반)'(자유텍스트 물품명을 규칙기반으로 표준코드에 매칭한 결과 —
-- 동의어(예: "혈당스틱"/"혈당 스트립")까지는 못 잡는 등 여전히 불완전하다는 게
-- AI 파트에서 확인됨. 검수 상태를 어떻게 표현할지는 후속 결정 필요).
--
-- 미해결로 남아있는 별개 문제: 여기 institution_id 로 쓰이는 기관코드 자체가
-- 실제 기관 신원과 매칭되지 않은 임의값일 수 있다(institutions 테이블 코멘트,
-- backend#16 참고) — 이 테이블은 그 문제를 풀지 않는다.
CREATE TABLE IF NOT EXISTS institution_item_codes (
    institution_id TEXT NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
    raw_item_code TEXT NOT NULL,   -- 기관이 실제 쓰는 원본 코드(공식코드 또는 USE코드) — 기관 내에서만 유일
    raw_item_name TEXT NOT NULL,   -- 원본 물품명(정규화 전) — 매핑 검수/추적용
    standard_code TEXT NOT NULL REFERENCES standard_items(standard_code),
    code_type TEXT NOT NULL,       -- '공식코드' | 'USE코드(규칙기반)'
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (institution_id, raw_item_code)
);
CREATE INDEX IF NOT EXISTS idx_institution_item_codes_standard ON institution_item_codes(standard_code);

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
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
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
