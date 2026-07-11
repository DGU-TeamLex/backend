# backend
TeamLex Backend (BE)

## 저장소 책임 범위 (backend vs ai)

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

