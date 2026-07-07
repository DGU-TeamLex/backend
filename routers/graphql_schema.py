"""GraphQL 레이어 — REST(routers/wep_stock.py)와 병행 제공.

사업수행계획서 4.3.2 "백엔드: 기본 재고량 조회 REST/JSON API + GraphQL" 대응.
REST가 이미 쓰는 데이터 모듈(wep_data, wep_inventory)을 그대로 재사용하므로
데이터는 REST와 100% 동일하다 — 차이는 조회 방식뿐이다.

REST로는 기관 목록 → 기관별 재고를 보려면 N+1번 왕복해야 하지만, GraphQL은
`institutions { id name inventory { standardName available } }` 한 번의 쿼리로
기관과 그 재고를 함께 가져올 수 있다. "기본 재고량 조회"에 가장 먼저 해당하는
institutions/institution 쿼리를 중심으로 하고, supplyRisk·alerts를 보조로 둔다.
"""
from typing import List, Optional

import strawberry

from . import wep_data as D
from . import wep_inventory as INV


@strawberry.type(description="기관의 표준품목별 재고·SS/ROP·발주권고 (결정론적 생성값, REST /facilities/{id} 와 동일 데이터)")
class InventoryItem:
    standard_code: str
    standard_name: str
    item_group_id: str
    criticality: str
    uom: str
    on_hand: int
    available: int
    mu: float
    sigma: float
    lead_time_used: float
    z_used: float
    ss: float
    rop: float
    target: float
    order_recommendation: int
    supply_risk_level: str
    status: str


def _to_inventory_item(row: dict) -> InventoryItem:
    return InventoryItem(
        standard_code=row["standardCode"],
        standard_name=row["standardName"],
        item_group_id=row["itemGroupId"],
        criticality=row["criticality"],
        uom=row["uom"],
        on_hand=row["onHand"],
        available=row["available"],
        mu=row["mu"],
        sigma=row["sigma"],
        lead_time_used=row["leadTimeUsed"],
        z_used=row["zUsed"],
        ss=row["SS"],
        rop=row["ROP"],
        target=row["target"],
        order_recommendation=row["orderRecommendation"],
        supply_risk_level=row["supplyRiskLevel"],
        status=row["status"],
    )


@strawberry.type(description="보건기관 (전국 지역보건의료기관 현황, 실데이터 3,598곳)")
class Institution:
    id: str
    name: str
    type: str
    category: str
    sido: str
    sigungu: str
    island: bool

    @strawberry.field(description="이 기관의 품목별 재고 목록 (기관 조회와 한 번에 가져올 수 있음)")
    def inventory(self) -> List[InventoryItem]:
        inst = INV.INST_BY_ID.get(self.id)
        if not inst:
            return []
        return [_to_inventory_item(r) for r in INV.inventory_for(inst)]


def _to_institution(inst: dict) -> Institution:
    return Institution(
        id=inst["id"],
        name=inst["name"],
        type=inst["type"],
        category=inst["category"],
        sido=inst["sido"],
        sigungu=inst["sigungu"],
        island=inst["island"],
    )


@strawberry.type(description="품목군 공급위험 현황 (모듈 C)")
class SupplyRisk:
    item_group_id: str
    item_group_name: str
    date: str
    risk_score: int
    level: str
    lead_time_estimate: int
    confidence: float


@strawberry.type(description="알림 (재고미달·공급위험·유효기간임박)")
class Alert:
    alert_id: str
    alert_type: str
    severity: str
    title: str
    message: str
    institution_id: Optional[str]
    resolved: bool


@strawberry.type
class Query:
    @strawberry.field(description="지역·기관유형별 기관 목록 (REST /facilities 와 동일 필터, 이슈 #8)")
    def institutions(
        self,
        category: Optional[str] = None,
        sido: Optional[str] = None,
        sigungu: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 50,
    ) -> List[Institution]:
        items = INV._filtered(category=category, sido=sido, sigungu=sigungu, q=q)
        return [_to_institution(i) for i in items[:limit]]

    @strawberry.field(description="단일 기관 — inventory 하위 필드까지 한 번의 쿼리로 조회 가능")
    def institution(self, id: str) -> Optional[Institution]:
        inst = INV.INST_BY_ID.get(id)
        return _to_institution(inst) if inst else None

    @strawberry.field(description="품목군 공급위험 현황 목록")
    def supply_risk(self) -> List[SupplyRisk]:
        name = {g["itemGroupId"]: g["name"] for g in D.ITEM_GROUPS}
        return [
            SupplyRisk(
                item_group_id=r["itemGroupId"],
                item_group_name=name.get(r["itemGroupId"], r["itemGroupId"]),
                date=r["date"],
                risk_score=r["riskScore"],
                level=r["level"],
                lead_time_estimate=r["leadTimeEstimate"],
                confidence=r["confidence"],
            )
            for r in D.SUPPLY_RISK
        ]

    @strawberry.field(description="알림 목록 (severity/resolved 필터)")
    def alerts(self, severity: Optional[str] = None, resolved: Optional[bool] = None) -> List[Alert]:
        rows = D.ALERTS
        if severity:
            rows = [a for a in rows if a["severity"] == severity]
        if resolved is not None:
            rows = [a for a in rows if (a["resolvedAt"] is not None) == resolved]
        return [
            Alert(
                alert_id=a["alertId"],
                alert_type=a["alertType"],
                severity=a["severity"],
                title=a["title"],
                message=a["message"],
                institution_id=a.get("institutionId"),
                resolved=a["resolvedAt"] is not None,
            )
            for a in rows
        ]


schema = strawberry.Schema(query=Query)
