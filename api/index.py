"""
WeP-Stock API — Vercel(Python 서버리스) 배포 진입점.

features/wep-stock/app.py 의 초안 로직을 배포용으로 정리한 버전:
- CORS 허용 (프론트엔드에서 호출 가능하도록)
- 서버리스 콜드스타트 시 보이도록 데모 시드 데이터 주입
- 인메모리 저장소이므로 서버리스에서 데이터는 영속되지 않음 (데모/프로토타입용)

vercel.json 의 rewrite 로 모든 경로가 이 함수(/api/index)로 라우팅되고,
FastAPI 가 원본 경로(/api/v1/stocks 등)로 다시 라우팅한다.
"""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="WeP-Stock API", version="0.1.0-draft")

# 프론트엔드(다른 도메인)에서 호출 가능하도록 CORS 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Schemas ---
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


# --- In-memory store (서버리스: 영속 X, 데모용 시드 포함) ---
_db: dict = {}
_seq = 0


def _seed(name: str, ticker: str, description: str) -> None:
    global _seq
    _seq += 1
    _db[_seq] = {
        "id": _seq,
        "name": name,
        "ticker": ticker,
        "description": description,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


_seed("삼성전자", "005930", "데모 시드 데이터")
_seed("Apple Inc.", "AAPL", "데모 시드 데이터")
_seed("NVIDIA", "NVDA", "데모 시드 데이터")


# --- Routes ---
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
