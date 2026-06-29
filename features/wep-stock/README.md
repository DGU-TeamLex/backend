# wep-stock — 자동 생성 초안

> **스택 선택 근거**: Python + FastAPI — 경량 CRUD/프로토타입 구현에 최적, 빠른 서비스 기동 가능.

## 출처
- 메일 제목: 기능명세서 및 api명세서 초안
- 수신일: 2026-06-29
- 첨부: `WeP-Stock 기능 명세서 & API 명세서.pdf` (파싱 불가 — 실제 명세는 PDF 확인 필요)

## 구조

```
features/wep-stock/
├── app.py           # FastAPI 앱 (진입점 + 라우터 일체 포함)
├── requirements.txt
└── README.md
```

## 실행

```bash
cd features/wep-stock
pip install -r requirements.txt
uvicorn app:app --reload
# Swagger UI: http://localhost:8000/docs
```

## 다음 실제 구현 시 해야 할 일

- [ ] PDF 명세서 확인 후 `StockBase` 필드 수정
- [ ] SQLAlchemy / 원하는 DB ORM 연동
- [ ] 인증/권한 미들웨어 추가
- [ ] 비즈니스 로직 구현
