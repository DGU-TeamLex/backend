"""wep-stock 기능 라우터.

새 기능을 추가할 때는 이 파일을 본떠 routers/<slug>.py 를 만들고
`router = APIRouter(...)` 를 정의하면 api/index.py 가 자동 등록한다.
"""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1", tags=["wep-stock"])


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


# In-memory store (서버리스: 영속 X, 데모용 시드 포함)
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


@router.get("/stocks", response_model=List[StockResponse])
def list_stocks():
    return list(_db.values())


@router.get("/stocks/{stock_id}", response_model=StockResponse)
def get_stock(stock_id: int):
    if stock_id not in _db:
        raise HTTPException(status_code=404, detail="Not found")
    return _db[stock_id]


@router.post("/stocks", response_model=StockResponse, status_code=201)
def create_stock(body: StockCreate):
    global _seq
    _seq += 1
    record = {**body.model_dump(), "id": _seq, "created_at": datetime.now(timezone.utc).isoformat()}
    _db[_seq] = record
    return record


@router.put("/stocks/{stock_id}", response_model=StockResponse)
def update_stock(stock_id: int, body: StockUpdate):
    if stock_id not in _db:
        raise HTTPException(status_code=404, detail="Not found")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    _db[stock_id].update(updates)
    return _db[stock_id]


@router.delete("/stocks/{stock_id}", status_code=204)
def delete_stock(stock_id: int):
    if stock_id not in _db:
        raise HTTPException(status_code=404, detail="Not found")
    del _db[stock_id]
