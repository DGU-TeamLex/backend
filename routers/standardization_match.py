"""모듈 A — 자유텍스트 물품명 → 표준코드 매칭 엔진 (이슈 #20, 2단계).

1단계(`routers/imports_upload.py`)는 업로드 접수·검증까지만 다뤘다. 이 라우터는
그 후속으로, 자유텍스트 물품명이 들어왔을 때 `standard_items` 카탈로그(17,148종)
중 어떤 표준코드에 대응하는지 후보를 생성하고 신뢰도를 매긴다.

방식: 정규화 → 문자 3-gram 자카드 유사도 + 편집거리 기반 비율(difflib)을 조합한
점수로 후보를 순위화한다. 신뢰도 임계 이상이면 자동매칭, 미달이면
`needsReview=True` 로 표시해 사람이 표준화 검수 큐에서 재검토하도록 한다.

임베딩 기반 재순위(이슈 #20 항목 3의 "임베딩 재순위")는 별도 임베딩 인프라(모델
호스팅·비용)가 필요해 이번 범위에서는 제외한다 — 위 조합 점수로 대체한다.
"""
import difflib
import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth.deps import require_role
from db import queries as DB

router = APIRouter(prefix="/api/v1")

T_A = ["모듈 A · 물품 표준화"]

_central_only = Depends(require_role("CENTRAL"))

# 이 값 이상이면 자동매칭으로 간주, 미만이면 검수 큐로 보낸다.
_AUTO_MATCH_THRESHOLD = 0.82

_WS_RE = re.compile(r"\s+")
_PAREN_RE = re.compile(r"[()\[\]（）]")


def normalize_item_name(name: str) -> str:
    """비교용 정규화: 공백 압축, 괄호류 제거, 소문자화."""
    name = name.strip()
    name = _PAREN_RE.sub(" ", name)
    name = _WS_RE.sub(" ", name)
    return name.strip().lower()


def _bigrams(s: str) -> set:
    return {s[i:i + 2] for i in range(len(s) - 1)} or {s}


def _score(query_norm: str, candidate_norm: str) -> float:
    """문자 2-gram 자카드 유사도와 difflib 비율의 평균."""
    a, b = _bigrams(query_norm), _bigrams(candidate_norm)
    jaccard = len(a & b) / len(a | b) if (a | b) else 0.0
    ratio = difflib.SequenceMatcher(None, query_norm, candidate_norm).ratio()
    return (jaccard + ratio) / 2


def match_candidates(item_name: str, catalog: list, limit: int = 5) -> list:
    query_norm = normalize_item_name(item_name)
    scored = [
        {**item, "score": round(_score(query_norm, normalize_item_name(item["standardName"])), 4)}
        for item in catalog
    ]
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]


class MatchBody(BaseModel):
    itemName: str


@router.post("/standardization/match", tags=T_A, summary="자유텍스트 물품명 → 표준코드 후보 매칭")
def standardization_match(body: MatchBody, _admin: dict = _central_only):
    catalog = DB.standard_items_catalog()
    candidates = match_candidates(body.itemName, catalog, limit=5)
    top = candidates[0] if candidates else None
    auto_matched = bool(top and top["score"] >= _AUTO_MATCH_THRESHOLD)
    return {
        "query": body.itemName,
        "candidates": candidates,
        "autoMatched": auto_matched,
        "matchedStandardCode": top["standardCode"] if auto_matched else None,
        "needsReview": not auto_matched,
        "threshold": _AUTO_MATCH_THRESHOLD,
    }
