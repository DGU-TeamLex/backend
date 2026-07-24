# WeP-Stock Backend

전국 보건기관 의료물품 통합 재고관리 웹서비스 **WeP-Stock** 의 백엔드 API — FastAPI 기반 REST + GraphQL 을 Vercel Python 서버리스로 서빙합니다.

## 소개

보건소·보건지소·보건진료소 등 전국 지역보건의료기관의 의료물품 재고를 한 곳에서 관리하기 위한 서비스입니다.
파일 기반(XLSX) 데이터 인테이크로 시작해 **물품 표준화(A) → 수요 예측(B) · 공급위험 경보(C) → 적정재고·알림·재배치(D) → 2-뷰(중앙/기관) 대시보드** 순으로 이어지는 파이프라인을 API 로 노출합니다.

동국대학교 SW교육원 산학협력 프로젝트(TeamLex)의 백엔드 저장소이며, 실제 데이터가 적재된 부분과 데모용 목업이 코드·문서 양쪽에서 명확히 구분되어 있습니다.

| 구분 | 내용 |
|---|---|
| **실데이터** | 기관 마스터 3,598곳(보건복지부 지역보건의료기관 현황) · 표준품목 17,148종(한국사회보장정보원 SSIS 물품 입출고 데이터) · 재고/SS·ROP·발주권고 · 재고미달 알림 |
| **MOCK** | 모듈 A(표준화 검수 큐) · 모듈 B(수요 예측) · 모듈 C(공급위험) · 재배치 제안 · 외부지표 |

목업 엔드포인트는 OpenAPI 태그와 summary 에 `⚠️ MOCK` / `[MOCK]` 으로 표시되어 Swagger 문서에서 바로 구분됩니다.

## ✨ 주요 기능

### 인증 · 권한 (RBAC)

- `POST /api/v1/auth/login` — bcrypt 검증 후 **JWT(HS256, 8시간)** 발급
- 역할 2종 — `CENTRAL`(중앙관리자, 전 기관 조회) / `INSTITUTION`(기관 담당자, 소속 기관으로 스코프)
- 공개 가입 플로우 없음. 계정은 `scripts/seed_users.py` 또는 CENTRAL 전용 계정 관리 API 로만 생성
- `GET/POST /api/v1/users`, `PATCH /api/v1/users/{user_id}` — CENTRAL 전용 계정 관리(응답에서 비밀번호 해시 제외)

### 마스터 · 데이터 인테이크

- 기관 목록/상세, 기관유형(보건소·보건지소·보건진료소)·시도 집계, 표준품목 검색, 품목군 목록
- `POST /api/v1/imports` — XLSX 업로드. **OWASP File Upload 기준 검증**(확장자 화이트리스트 · content-type · 매직바이트 `PK\x03\x04` · 크기 상한 · zip bomb 방지: 압축 해제 총량 및 엔트리별 압축비 상한) 후 `import_batches` 에 `RECEIVED` 배치로 접수
- Vercel 서버리스 요청 본문 하드리밋(약 4.5MB)을 고려해 코드 상한을 4MB 로 두어, 한계 근처 파일이 플랫폼 기본 오류 대신 명확한 422 안내를 받도록 처리

### 적정재고 · 발주 · 알림 (모듈 D)

- `GET /api/v1/inventory-policy` — 안전재고(SS)·재주문점(ROP)·목표재고·상태(`OK`/`WATCH`/`BELOW_ROP`/`CRITICAL`)를 시급도순 제공, 단일 품목 상세는 근거까지 포함
- `GET /api/v1/order-recommendations` — 발주 수량·시점 권고
- `GET /api/v1/alerts`, `GET /api/v1/alerts/{alert_id}` — 알림 목록/상세(근거 JSONB 포함)
- `GET /api/v1/alerts/derived`, `/alerts/derived/summary` — 실재고에서 **온디맨드로 파생**한 재고미달 알림과 실제 규모 집계

### 대시보드

- `GET /api/v1/dashboard/central` — 중앙 뷰(전국 요약 · 공급위험 랭킹 · 부족 기관)
- `GET /api/v1/dashboard/institution/{institution_id}` — 기관 뷰

### GraphQL 병행 제공

- `/graphql` (GraphiQL IDE 포함) — Strawberry 기반. REST 와 동일한 도메인을 Query/Mutation 으로 노출
- 요청마다 **DataLoader** 세트를 새로 생성해 `Institution.inventory` / `summary` 같은 중첩 필드가 여러 기관에 대해 동시 요청될 때 배치 조회되도록 처리(N+1 방지)

### API 문서

`/docs`(Swagger UI) · `/redoc` · `/openapi.json` · `/graphql`. 루트 `/` 접속 시 `/docs` 로 리다이렉트됩니다.

## 🛠 기술 스택

| 영역 | 사용 기술 |
|---|---|
| **Language** | Python 3.12 |
| **Framework** | FastAPI, Pydantic v2 |
| **GraphQL** | Strawberry GraphQL (`strawberry-graphql`, DataLoader) |
| **Database** | Neon Postgres (Vercel Marketplace), psycopg 3 (`dict_row`) |
| **Auth** | PyJWT (HS256), bcrypt |
| **Upload** | python-multipart, `zipfile` 기반 XLSX 구조 검증 |
| **Deploy** | Vercel Python Serverless Functions |

## 🏗 아키텍처

```
Client (frontend)
      │  Authorization: Bearer <JWT>
      ▼
vercel.json  ── 모든 경로를 /api/index 로 rewrite
      ▼
api/index.py                     FastAPI 앱 · CORS · 라우터 등록 · GraphQL 마운트
      ├── routers/derived_alerts.py   실재고 파생 재고미달 알림  (※ wep_stock 보다 먼저 등록)
      ├── routers/wep_stock.py        인증·마스터·모듈 A~D·알림·대시보드 REST
      ├── routers/imports_upload.py   XLSX 업로드 검증 + 배치 접수
      ├── routers/user_admin.py       CENTRAL 전용 계정 관리
      └── routers/graphql_schema.py   Strawberry 스키마 (Query/Mutation, DataLoader)
      ▼
auth/   deps.py(get_current_user · require_role) · security.py(JWT · bcrypt)
      ▼
db/     connection.py(요청 단위 커넥션) · queries.py(SQL) · schema.sql(DDL)
      ▼
Neon Postgres
```

**설계상 고정된 규칙 (코드 주석으로 명시)**

- `derived_alerts` 라우터는 반드시 `wep_stock` 보다 **먼저** 등록합니다. FastAPI 는 등록 순서로 매칭하므로, `wep_stock` 의 `/alerts/{alert_id}` 가 구체 경로 `/alerts/derived` 를 `alert_id='derived'` 로 가로챕니다.
- 서버리스 환경이라 전역 커넥션 풀을 두지 않고 **요청마다 짧게 connect** 합니다(Neon pooled DSN 은 앞단 PgBouncer 라 매 요청 연결 비용이 낮고, 콜드스타트마다 프로세스가 새로 뜨는 환경에서 풀은 복잡도만 늘림).
- `users.institution_id` 에는 의도적으로 FK 를 걸지 않습니다. `scripts/seed_db.py` 가 `institutions` 를 `TRUNCATE ... CASCADE` 로 재적재하는데, FK 가 있으면 그 CASCADE 에 계정이 통째로 딸려가기 때문입니다.
- 새 기능은 `routers/<slug>.py` 에 `router = APIRouter(prefix="/api/v1", ...)` 를 정의하고 `api/index.py` 의 "라우터 등록" 구역에 import + `include_router` 두 줄만 추가합니다(정적 import 여야 Vercel 이 `routers/` 를 번들에 포함).

### 데이터 모델 (`db/schema.sql`)

`institutions` · `item_groups` · `standard_items` · `inventory` · `users` · `import_batches` · `alerts`,
그리고 메타코드 3축(원재료 / 공급리스크 / 수요트리거)을 담는 `material_meta_codes` · `item_meta_map`.

> `item_meta_map` 의 조인 키는 **물품명** 입니다. 보건의료정보부 회의(2026-07-14) 결정에 따라, USE 계열 물품코드는 보건소별로 각자 일련번호를 부여해 동일 코드에 다른 물품이 매핑되므로 물품코드를 무시하고 물품명 기준으로 정리합니다.

`inventory.demand_class`(`DORMANT`/`CENSORED`/`ACTIVE`)와 `mu_corrected`(결품기간 절단편향 보정 일평균 수요)는 **스키마는 backend, 값의 계산·적재는 ai** 가 소유합니다.

## 🚀 시작하기

### 1. 설치

```bash
pip install -r requirements.txt
pip install uvicorn   # requirements.txt 에는 없음 — 배포 시엔 Vercel 런타임이 서빙
```

### 2. 환경변수

| 변수 | 필수 | 쓰이는 곳 | 설명 |
|---|---|---|---|
| `DATABASE_URL` | ✅ | `db/connection.py`, 모든 스크립트 | Neon Postgres 연결 문자열(pooled DSN 권장) |
| `JWT_SECRET` | ✅ (운영) | `auth/security.py` | JWT 서명 키. 미설정 시 개발용 기본값으로 폴백하므로 **배포 환경에는 반드시 설정** |
| `SEED_CENTRAL_PASSWORD` | | `scripts/seed_users.py` | 데모 CENTRAL 계정 비밀번호(미설정 시 개발용 기본값) |
| `SEED_INSTITUTION_PASSWORD` | | `scripts/seed_users.py` | 데모 INSTITUTION 계정 비밀번호 |
| `SSIS_DATA_DIR` | | `scripts/import_ssis_dataset.py` | SSIS 원본 `.dat` 파일이 있는 디렉토리(기본값 `extracted`) |
| `STOCK_PARQUET` / `META_DIR` | | `scripts/fix_inventory_stats.py` | 재고 정규화 parquet 경로 / 메타코드 산출물 디렉토리 |
| `L_POLICY` | | `scripts/fix_inventory_stats.py` | 리드타임 산정 정책 — `median`(기본, 보수) \| `p25`(낙관) |
| `AI_SERVING_URL` | | `scripts/ai_policy_adapter.py` | ai 서빙 API 베이스 URL. 미설정 시 스킵(ai 미배포 상태면 정상) |
| `DRY_RUN` | | `scripts/ai_policy_adapter.py` | 값이 있으면 검증·집계만 하고 DB 를 건드리지 않음 |

### 3. 실행

```bash
uvicorn api.index:app --reload
# Swagger UI  http://127.0.0.1:8000/docs
# GraphiQL    http://127.0.0.1:8000/graphql
```

### 4. DB 초기화 · 데이터 적재

```bash
# 스키마 + 기본 시드
DATABASE_URL=... python3 scripts/seed_db.py
DATABASE_URL=... python3 scripts/seed_users.py         # 데모 계정 (idempotent upsert)

# SSIS 실데이터 적재 · 분류 정리
SSIS_DATA_DIR=/path/to/extracted DATABASE_URL=... python3 scripts/import_ssis_dataset.py
DATABASE_URL=... python3 scripts/reclassify_item_groups.py        # 정식 물품분류표 기준 재분류
DATABASE_URL=... python3 scripts/consolidate_item_meta_groups.py  # 25개 분류 → 14개 메타코드 통합

# 재고 통계 교정 · AI 재고정책 반영
DATABASE_URL=... STOCK_PARQUET=... META_DIR=... python3 scripts/fix_inventory_stats.py
AI_SERVING_URL=... DATABASE_URL=... python3 scripts/ai_policy_adapter.py
```

### 5. 배포

Vercel 에 그대로 올리면 `vercel.json` 의 rewrite(`/(.*)` → `/api/index`)에 따라 단일 서버리스 함수로 서빙됩니다. Vercel 프로젝트 환경변수에 `DATABASE_URL`, `JWT_SECRET` 을 설정해야 합니다.

## 📁 구조

```
.
├── api/
│   └── index.py                 # Vercel 진입점 — FastAPI 앱, 라우터/GraphQL 등록
├── routers/
│   ├── wep_stock.py             # 인증·마스터·모듈 A~D·알림·대시보드 REST
│   ├── derived_alerts.py        # 실재고 파생 재고미달 알림
│   ├── imports_upload.py        # XLSX 업로드 검증 + 배치 접수
│   ├── user_admin.py            # CENTRAL 전용 계정 관리
│   ├── graphql_schema.py        # Strawberry 스키마 (Query/Mutation + DataLoader)
│   ├── wep_data.py              # 실 파이프라인이 아직 없는 영역의 인메모리 시드
│   └── institutions_data.py     # 기관 시드 데이터
├── auth/
│   ├── security.py              # bcrypt 해시 · JWT 발급/검증
│   └── deps.py                  # get_current_user · require_role
├── db/
│   ├── schema.sql               # 전체 DDL
│   ├── connection.py            # 요청 단위 Neon 연결 헬퍼
│   └── queries.py               # SQL 쿼리 모음
├── scripts/                     # 시드·적재·교정 CLI (위 "4. DB 초기화" 참고)
│   └── data/                    # 품목군 메타코드/재분류 매핑 JSON
├── features/wep-stock/          # spec-bot 이 명세서 메일에서 자동 생성한 초안(참고용)
├── requirements.txt
└── vercel.json
```

## 🔀 저장소 책임 범위 (backend vs ai)

WeP-Stock은 저장소가 나뉘어 있습니다. 이슈를 backend에 만들기 전에 아래를 먼저 확인하세요.

**이 저장소(backend)가 담당하는 것:**
```
인증 / 사용자 / 권한 (JWT, RBAC)
파일 업로드 및 import_batch 관리
물품 표준화 검수 UI/API (모듈 A)
기관/중앙 운영 대시보드 API
알림 상태 관리
재배치 승인 워크플로우
DB 트랜잭션/감사 로그
```

**[DGU-TeamLex/ai](https://github.com/DGU-TeamLex/ai) (dev 브랜치)가 담당하는 것 — 여기서 직접 구현하지 말 것:**
```
수요예측 모델 학습/평가 (모듈 B — Croston/SBA/TSB 등)
뉴스·원자재 위험 점수 산출 (모듈 C)
재고정책(safety stock)·발주권고 알고리즘
AI serving API (/api/v1/ai/forecasts, /api/v1/ai/supply-risk, /api/v1/ai/order-recommendations 등)
```

`/forecasts`, `/supply-risk`, `/external-indicators` 관련 이슈는 **ai 레포의 서빙 API를
연동하는 작업**으로 스코프를 잡아야 합니다 — backend에서 자체 휴리스틱/모델을 새로
구현하지 않습니다. ai 레포가 아직 배포되지 않은 상태라면 연동 이슈는 blocked로 표시하고,
ai 레포 쪽에 대응 이슈가 있는지 먼저 확인하세요(중복 생성 금지).

(2026-07-11: 모듈 B 관련 backend#21 이슈는 ai#9 로 이관, 모듈 C 관련 backend#22 는
ai#2/ai#4 와 중복이라 종료하고 세부내용만 이관했습니다.)

## 👤 기여도 & 개발 환경

| 항목 | 내용 |
|---|---|
| **기여 비율** | **100%** (단독 개발) |
| **커밋** | 44 / 44 (본인 / 전체 사람 커밋) |
| **참여 인원** | 1명 |
| **AI 코딩 도구** | Claude Code |

<sub>기여 비율은 커밋 author 이메일 기준 집계이며 봇·자동화 커밋은 제외했습니다.</sub>
