"""
WeP-Stock API — 자동 생성 초안
스택: Python + FastAPI (경량 CRUD 프로토타입에 최적)
실행: uvicorn app:app --reload  (이 파일이 있는 디렉토리에서)

⚠️ 실제 명세는 첨부 PDF를 참고해 schemas/DB/비즈니스 로직을 구현하세요.
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone

app = FastAPI(title="WeP-Stock API", version="0.1.0-draft")


# ---------------------------------------------------------------------------
# Schemas — PDF 명세 확인 후 필드 수정 필요
# ---------------------------------------------------------------------------

class StockBase(BaseModel):
    name: str
    ticker: str
    description: Optional[str] = None


class StockCreate(StockBase):
    pass


class StockUpdate(BaseModel):
    name: Optional[str] = None
    ticker: Optional[str] = None
    description: Optional[str] = None


class StockResponse(StockBase):
    id: int
    created_at: str


# ---------------------------------------------------------------------------
# In-memory store (임시) — 실제 DB로 교체 필요
# ---------------------------------------------------------------------------

_db: dict = {}
_seq = 0


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/v1/stocks", response_model=List[StockResponse])
def list_stocks():
    return list(_db.values())


@app.get("/api/v1/stocks/{stock_id}", response_model=StockResponse)
def get_stock(stock_id: int):
    if stock_id not in _db:
        raise HTTPException(status_code=404, detail="Not found")
    return _db[stock_id]


@app.post("/api/v1/stocks", response_model=StockResponse, status_code=201)
def create_stock(body: StockCreate):
    global _seq
    _seq += 1
    record = {**body.model_dump(), "id": _seq, "created_at": datetime.now(timezone.utc).isoformat()}
    _db[_seq] = record
    return record


@app.put("/api/v1/stocks/{stock_id}", response_model=StockResponse)
def update_stock(stock_id: int, body: StockUpdate):
    if stock_id not in _db:
        raise HTTPException(status_code=404, detail="Not found")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    _db[stock_id].update(updates)
    return _db[stock_id]


@app.delete("/api/v1/stocks/{stock_id}", status_code=204)
def delete_stock(stock_id: int):
    if stock_id not in _db:
        raise HTTPException(status_code=404, detail="Not found")
    del _db[stock_id]
