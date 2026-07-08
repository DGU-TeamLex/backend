"""GraphQL 레이어 — REST(routers/wep_stock.py)와 병행 제공, 전체 리소스 커버.

사업수행계획서 4.3.2 "백엔드: 기본 재고량 조회 REST/JSON API + GraphQL" 대응.
기관(실데이터 3,598곳)·재고·알림은 Neon Postgres(db/queries.py)에서 조회한다 —
REST(routers/wep_stock.py)와 동일 쿼리 레이어를 공유하므로 두 API의 값은 항상
일치한다. 예측(B)/공급위험(C)/외부지표/인테이크/표준화검수/재배치는 아직 실
파이프라인이 없어 시드 데이터(wep_data.py)를 그대로 쓴다.

목록/상세로 나뉘어 있던 REST 를 GraphQL 에선 하나의 타입 + 중첩 필드로 통합했다
(예: Institution.inventory, Institution.summary). 단, 이 중첩 필드는 상위
institutions() 목록 안에서 여러 기관에 대해 동시에 요청되면 기관 수만큼 별도
DB 조회가 발생한다(N+1) — 배치 로더는 이후 과제로 남겨둔다.

`dashboardInstitution` 은 이전엔 구식 8개 기관 샘플만 지원했으나, 이번에 전국
3,598개 기관 전체를 지원하도록 실데이터로 전환했다.
"""
from typing import List, Optional

import strawberry
from strawberry.scalars import JSON

from . import wep_data as D
from db import queries as DB


# ============================================================
# 마스터 — 기관(실데이터 3,598곳) · 품목군 · 표준품목
# ============================================================

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
        standard_code=row["standardCode"], standard_name=row["standardName"],
        item_group_id=row["itemGroupId"], criticality=row["criticality"], uom=row["uom"],
        on_hand=row["onHand"], available=row["available"], mu=row["mu"], sigma=row["sigma"],
        lead_time_used=row["leadTimeUsed"], z_used=row["zUsed"], ss=row["SS"], rop=row["ROP"],
        target=row["target"], order_recommendation=row["orderRecommendation"],
        supply_risk_level=row["supplyRiskLevel"], status=row["status"],
    )


@strawberry.type(description="기관 상태 배지 (REST facilities 목록의 summary.badge)")
class FacilityBadge:
    level: str
    label: str
    count: int


@strawberry.type(description="기관 재고 현황 요약 (REST facilities 목록/상세의 summary)")
class FacilitySummary:
    tracked_items: int
    critical: int
    below_rop: int
    watch: int
    order_needed: int
    badge: FacilityBadge


def _to_summary(s: dict) -> FacilitySummary:
    b = s["badge"]
    return FacilitySummary(
        tracked_items=s["trackedItems"], critical=s["critical"], below_rop=s["belowRop"],
        watch=s["watch"], order_needed=s["orderNeeded"],
        badge=FacilityBadge(level=b["level"], label=b["label"], count=b["count"]),
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
        return [_to_inventory_item(r) for r in DB.inventory_for(self.id)]

    @strawberry.field(description="재고 상태 요약 + 배지 (긴급/주의/관찰/정상)")
    def summary(self) -> FacilitySummary:
        return _to_summary(DB.summary_for_institution(self.id))


def _to_institution(inst: dict) -> Institution:
    return Institution(
        id=inst["id"], name=inst["name"], type=inst["type"], category=inst["category"],
        sido=inst["sido"], sigungu=inst["sigungu"], island=inst["island"],
    )


@strawberry.type(description="기관유형 분류(보건소/보건지소/보건진료소)+개수")
class FacilityCategory:
    category: str
    count: int


@strawberry.type(description="시도(또는 시군구) 이름+개수")
class RegionCount:
    name: str
    count: int


@strawberry.type(description="품목군 (+ 공급위험 레벨/점수)")
class ItemGroup:
    item_group_id: str
    name: str
    risk_level: str
    risk_score: int


@strawberry.type(description="표준품목 마스터")
class StandardItem:
    standard_item_id: str
    standard_code: str
    standard_name: str
    item_group_id: str
    uom: str
    shelf_life_days: int
    criticality: str


# ============================================================
# 인증 · 사용자 (데모 목업)
# ============================================================

@strawberry.type(description="내 프로필·역할·소속 (데모 목업)")
class Me:
    id: str
    role: str
    institution_id: Optional[str]


@strawberry.type(description="로그인 응답 (데모 목업)")
class LoginResult:
    access_token: str
    refresh_token: str
    expires_in: int
    user: Me


# ============================================================
# 데이터 인테이크
# ============================================================

@strawberry.type(description="적재 배치 (import_batch)")
class ImportBatch:
    import_batch_id: str
    file_name: str
    source_vendor: str
    status: str
    uploaded_at: str
    total_rows: int
    valid_rows: int
    error_rows: int
    mapping_rate: float
    period_start: str
    period_end: str


def _to_import_batch(b: dict) -> ImportBatch:
    return ImportBatch(
        import_batch_id=b["importBatchId"], file_name=b["fileName"], source_vendor=b["sourceVendor"],
        status=b["status"], uploaded_at=b["uploadedAt"], total_rows=b["totalRows"],
        valid_rows=b["validRows"], error_rows=b["errorRows"], mapping_rate=b["mappingRate"],
        period_start=b["periodStart"], period_end=b["periodEnd"],
    )


# ============================================================
# 모듈 A — 물품 표준화
# ============================================================

@strawberry.type(description="표준화 매칭 추천 후보")
class TopCandidate:
    standard_code: str
    standard_name: str
    score: float


@strawberry.type(description="표준화 검수 대기 큐 항목")
class StandardizationQueueItem:
    raw_item_id: str
    raw_name: str
    status: str
    top_candidate: Optional[TopCandidate]


def _to_queue_item(x: dict) -> StandardizationQueueItem:
    tc = x.get("topCandidate")
    return StandardizationQueueItem(
        raw_item_id=x["rawItemId"], raw_name=x["rawName"], status=x["status"],
        top_candidate=TopCandidate(standard_code=tc["standardCode"], standard_name=tc["standardName"], score=tc["score"]) if tc else None,
    )


# ============================================================
# 모듈 B — 수요 예측
# ============================================================

@strawberry.type(description="월별 수요 분포(평균+분위수)")
class ForecastPoint:
    month: str
    mean: float
    q10: int
    q50: int
    q90: int
    confidence: float


@strawberry.type(description="기관×표준품목 수요 예측")
class Forecast:
    institution_id: str
    standard_code: str
    pattern_class: str
    champion_model: str
    model_version: str
    data_quality_flag: str
    horizon: List[ForecastPoint]


def _to_forecast(f: dict) -> Forecast:
    return Forecast(
        institution_id=f["institutionId"], standard_code=f["standardCode"], pattern_class=f["patternClass"],
        champion_model=f["championModel"], model_version=f["modelVersion"], data_quality_flag=f["dataQualityFlag"],
        horizon=[ForecastPoint(month=h["month"], mean=h["mean"], q10=h["q10"], q50=h["q50"], q90=h["q90"], confidence=h["confidence"]) for h in f["horizon"]],
    )


# ============================================================
# 모듈 C — 공급위험 조기경보
# ============================================================

@strawberry.type(description="공급위험 기여 원재료")
class MaterialContributor:
    material_type: str
    contrib: float
    lag_days: int


@strawberry.type(description="근거 뉴스")
class NewsEvidence:
    news_id: str
    title: str
    url: str
    published_at: str


@strawberry.type(description="품목군 공급위험 현황 (근거 포함)")
class SupplyRisk:
    item_group_id: str
    item_group_name: str
    date: str
    risk_score: int
    level: str
    lead_time_estimate: int
    confidence: float
    top_contributors: List[MaterialContributor]
    evidence_news: List[NewsEvidence]


def _to_supply_risk(r: dict, name_map: dict) -> SupplyRisk:
    return SupplyRisk(
        item_group_id=r["itemGroupId"], item_group_name=name_map.get(r["itemGroupId"], r["itemGroupId"]),
        date=r["date"], risk_score=r["riskScore"], level=r["level"],
        lead_time_estimate=r["leadTimeEstimate"], confidence=r["confidence"],
        top_contributors=[MaterialContributor(material_type=c["materialType"], contrib=c["contrib"], lag_days=c["lagDays"]) for c in r["topContributors"]],
        evidence_news=[NewsEvidence(news_id=n["newsId"], title=n["title"], url=n["url"], published_at=n["publishedAt"]) for n in r["evidenceNews"]],
    )


# ============================================================
# 모듈 D — 적정재고 · 발주 · 재배치
# ============================================================

@strawberry.type(description="SS/ROP 재고 현황 (REST /inventory-policy 목록, 주요 보건소 샘플)")
class InventoryPolicyRow:
    institution_id: str
    institution_name: str
    sido: str
    sigungu: str
    standard_code: str
    standard_name: str
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


def _to_policy_row(r: dict) -> InventoryPolicyRow:
    return InventoryPolicyRow(
        institution_id=r["institutionId"], institution_name=r["institutionName"], sido=r["sido"], sigungu=r["sigungu"],
        standard_code=r["standardCode"], standard_name=r["standardName"], criticality=r["criticality"], uom=r["uom"],
        on_hand=r["onHand"], available=r["available"], mu=r["mu"], sigma=r["sigma"],
        lead_time_used=r["leadTimeUsed"], z_used=r["zUsed"], ss=r["SS"], rop=r["ROP"], target=r["target"],
        order_recommendation=r["orderRecommendation"], supply_risk_level=r["supplyRiskLevel"], status=r["status"],
    )


@strawberry.type(description="단일 SS/ROP·근거 (REST /inventory-policy/{institutionId}/{standardCode}, 구식 8기관 샘플)")
class InventoryPolicyDetail:
    institution_id: str
    standard_code: str
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
    assumed_lead_time: bool


def _to_policy_detail(r: dict) -> InventoryPolicyDetail:
    return InventoryPolicyDetail(
        institution_id=r["institutionId"], standard_code=r["standardCode"], on_hand=r["onHand"], available=r["available"],
        mu=r["mu"], sigma=r["sigma"], lead_time_used=r["leadTimeUsed"], z_used=r["zUsed"], ss=r["SS"], rop=r["ROP"],
        target=r["target"], order_recommendation=r["orderRecommendation"], supply_risk_level=r["supplyRiskLevel"],
        status=r["status"], assumed_lead_time=r["assumedLeadTime"],
    )


@strawberry.type(description="발주 권고 (수량·근거)")
class OrderRecommendation:
    institution_id: str
    institution_name: str
    standard_code: str
    standard_name: str
    available: int
    rop: float
    target: float
    recommended_qty: int
    uom: str
    supply_risk_level: str
    status: str


@strawberry.type(description="재배치 제안 (부족↔여유 매칭)")
class Relocation:
    id: str
    from_institution: str
    from_name: Optional[str]
    to_institution: str
    to_name: Optional[str]
    standard_code: str
    standard_name: str
    suggested_qty: int
    reason: str
    status: str


def _to_relocation(r: dict, nm: dict) -> Relocation:
    return Relocation(
        id=r["id"], from_institution=r["fromInstitution"], from_name=nm.get(r["fromInstitution"]),
        to_institution=r["toInstitution"], to_name=nm.get(r["toInstitution"]), standard_code=r["standardCode"],
        standard_name=D.ITEM_BY_CODE.get(r["standardCode"], {}).get("standardName", r["standardCode"]),
        suggested_qty=r["suggestedQty"], reason=r["reason"], status=r["status"],
    )


# ============================================================
# 알림
# ============================================================

@strawberry.type(description="알림 (재고미달·공급위험·유효기간임박)")
class Alert:
    alert_id: str
    alert_type: str
    severity: str
    title: str
    message: str
    institution_id: Optional[str]
    institution_name: Optional[str]
    generated_at: str
    resolved_at: Optional[str]
    evidence: JSON


def _to_alert_db(a: dict) -> Alert:
    """DB.alerts_list()/alert_one() 결과(institutionName 이미 조인됨) → Alert."""
    return Alert(
        alert_id=a["alertId"], alert_type=a["alertType"], severity=a["severity"], title=a["title"],
        message=a["message"], institution_id=a.get("institutionId"), institution_name=a.get("institutionName"),
        generated_at=a["generatedAt"], resolved_at=a.get("resolvedAt"), evidence=a.get("evidence") or {},
    )


# ============================================================
# 외부지표
# ============================================================

@strawberry.type(description="외부지표 관측치")
class IndicatorObservation:
    observed_at: str
    value: float


@strawberry.type(description="외부지표 (원자재 가격·뉴스리스크지수 등)")
class ExternalIndicator:
    indicator_id: str
    source_system: str
    indicator_type: str
    unit: str
    granularity: str
    latest: List[IndicatorObservation]


def _to_indicator(i: dict) -> ExternalIndicator:
    return ExternalIndicator(
        indicator_id=i["indicatorId"], source_system=i["sourceSystem"], indicator_type=i["indicatorType"],
        unit=i["unit"], granularity=i["granularity"],
        latest=[IndicatorObservation(observed_at=o["observedAt"], value=o["value"]) for o in i["latest"]],
    )


# ============================================================
# 대시보드
# ============================================================

@strawberry.type(description="중앙 대시보드 요약 지표")
class CentralSummary:
    institutions: int
    standard_items: int
    item_groups: int
    open_alerts: int
    total_on_hand: int
    below_rop_items: int
    critical_risk_groups: int


@strawberry.type(description="품목군 공급위험 랭킹 항목")
class SupplyRiskRankItem:
    item_group_id: str
    item_group_name: Optional[str]
    risk_score: int
    level: str


@strawberry.type(description="부족 상위 기관")
class ShortageInstitution:
    institution_id: str
    institution_name: Optional[str]
    shortage_items: int


@strawberry.type(description="중앙 뷰 대시보드 (REST /dashboard/central)")
class DashboardCentral:
    as_of: str
    summary: CentralSummary
    alerts_by_severity: JSON
    supply_risk_ranking: List[SupplyRiskRankItem]
    top_shortage_institutions: List[ShortageInstitution]
    relocations: List[Relocation]


@strawberry.type(description="기관 참조 (REST dashboard/institution 전용 뷰)")
class DashboardInstitutionRef:
    institution_id: str
    institution_name: str
    institution_type: str
    region_name: str


@strawberry.type(description="기관 대시보드 요약")
class InstitutionDashboardSummary:
    tracked_items: int
    below_rop: int
    order_needed: int
    open_alerts: int


@strawberry.type(description="기관 뷰 대시보드 (REST /dashboard/institution/{id}, 전국 3,598개 기관 전체 지원)")
class DashboardInstitution:
    as_of: str
    institution: DashboardInstitutionRef
    summary: InstitutionDashboardSummary
    inventory: List[InventoryItem]
    alerts: List[Alert]


# ============================================================
# Query root
# ============================================================

@strawberry.type
class Query:
    # ---- 인증·사용자 ----
    @strawberry.field(description="내 프로필·역할·소속 (데모 목업)")
    def me(self, role: str = "CENTRAL", institution_id: Optional[str] = None) -> Me:
        return Me(id="u_demo", role=role, institution_id=institution_id)

    # ---- 마스터 ----
    @strawberry.field(description="지역·기관유형별 기관 목록 (REST /facilities 와 동일 필터, 이슈 #8)")
    def institutions(
        self,
        category: Optional[str] = None,
        sido: Optional[str] = None,
        sigungu: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 50,
    ) -> List[Institution]:
        items = DB.list_institutions(category=category, sido=sido, sigungu=sigungu, q=q)
        return [_to_institution(i) for i in items[:limit]]

    @strawberry.field(description="단일 기관 — inventory/summary 하위 필드까지 한 번의 쿼리로 조회 가능")
    def institution(self, id: str) -> Optional[Institution]:
        inst = DB.get_institution(id)
        return _to_institution(inst) if inst else None

    @strawberry.field(description="기관유형 분류(보건소/보건지소/보건진료소)+개수")
    def facility_categories(self) -> List[FacilityCategory]:
        return [FacilityCategory(category=c["category"], count=c["count"]) for c in DB.categories()]

    @strawberry.field(description="시도(또는 시군구) 목록+개수")
    def facility_regions(self, category: Optional[str] = None, sido: Optional[str] = None) -> List[RegionCount]:
        r = DB.regions(category=category, sido=sido)
        return [RegionCount(name=x["name"], count=x["count"]) for x in r["items"]]

    @strawberry.field(description="품목군 목록(+위험레벨)")
    def item_groups(self) -> List[ItemGroup]:
        risk = {r["itemGroupId"]: r for r in D.SUPPLY_RISK}
        out = []
        for g in D.ITEM_GROUPS:
            r = risk.get(g["itemGroupId"], {})
            out.append(ItemGroup(item_group_id=g["itemGroupId"], name=g["name"],
                                  risk_level=r.get("level", "NORMAL"), risk_score=r.get("riskScore", 0)))
        return out

    @strawberry.field(description="표준품목 마스터 검색")
    def standard_items(self, q: Optional[str] = None, group: Optional[str] = None) -> List[StandardItem]:
        items = D.STANDARD_ITEMS
        if q:
            items = [i for i in items if q.lower() in i["standardName"].lower() or q.upper() in i["standardCode"]]
        if group:
            items = [i for i in items if i["itemGroupId"] == group]
        return [StandardItem(standard_item_id=i["standardItemId"], standard_code=i["standardCode"],
                              standard_name=i["standardName"], item_group_id=i["itemGroupId"], uom=i["uom"],
                              shelf_life_days=i["shelfLifeDays"], criticality=i["criticality"]) for i in items]

    # ---- 데이터 인테이크 ----
    @strawberry.field(description="적재 배치 목록")
    def imports(self, status: Optional[str] = None) -> List[ImportBatch]:
        items = D.IMPORTS
        if status:
            items = [b for b in items if b["status"] == status]
        return [_to_import_batch(b) for b in items]

    # ---- 모듈 A ----
    @strawberry.field(description="표준화 검수 대기 큐")
    def standardization_queue(self, status: Optional[str] = None) -> List[StandardizationQueueItem]:
        items = D.STD_QUEUE
        if status:
            items = [x for x in items if x["status"] == status]
        return [_to_queue_item(x) for x in items]

    # ---- 모듈 B ----
    @strawberry.field(description="수요 예측 목록")
    def forecasts(self, institution: Optional[str] = None) -> List[Forecast]:
        items = list(D.FORECASTS.values())
        if institution:
            items = [f for f in items if f["institutionId"] == institution]
        return [_to_forecast(f) for f in items]

    @strawberry.field(description="단일 수요 분포(mean+분위수)")
    def forecast(self, institution_id: str, standard_code: str) -> Optional[Forecast]:
        f = D.FORECASTS.get((institution_id, standard_code))
        return _to_forecast(f) if f else None

    # ---- 모듈 C ----
    @strawberry.field(description="품목군 공급위험 현황 목록 (근거 포함)")
    def supply_risk(self, level: Optional[str] = None) -> List[SupplyRisk]:
        items = D.SUPPLY_RISK
        if level:
            items = [r for r in items if r["level"] == level]
        name = {g["itemGroupId"]: g["name"] for g in D.ITEM_GROUPS}
        return [_to_supply_risk(r, name) for r in items]

    @strawberry.field(description="품목군 위험 상세(근거 포함)")
    def supply_risk_one(self, item_group_id: str) -> Optional[SupplyRisk]:
        r = D.RISK_BY_GROUP.get(item_group_id)
        if not r:
            return None
        name = {g["itemGroupId"]: g["name"] for g in D.ITEM_GROUPS}
        return _to_supply_risk(r, name)

    # ---- 모듈 D ----
    @strawberry.field(description="SS/ROP·재고 현황 목록(전국, 시급도순)")
    def inventory_policy(self, institution: Optional[str] = None, status: Optional[str] = None) -> List[InventoryPolicyRow]:
        rows = DB.inventory_policy_rows(institution=institution, status=status)
        return [_to_policy_row(r) for r in rows]

    @strawberry.field(description="단일 SS/ROP·근거")
    def inventory_policy_one(self, institution_id: str, standard_code: str) -> Optional[InventoryPolicyDetail]:
        for r in DB.inventory_policy_rows(institution=institution_id):
            if r["standardCode"] == standard_code:
                return _to_policy_detail({**r, "assumedLeadTime": True})
        return None

    @strawberry.field(description="발주 권고(수량·시점)")
    def order_recommendations(self, institution: Optional[str] = None) -> List[OrderRecommendation]:
        rows = DB.order_recommendations(institution=institution)
        return [OrderRecommendation(
            institution_id=r["institutionId"], institution_name=r["institutionName"], standard_code=r["standardCode"],
            standard_name=r["standardName"], available=r["available"], rop=r["ROP"], target=r["target"],
            recommended_qty=r["recommendedQty"], uom=r["uom"], supply_risk_level=r["supplyRiskLevel"], status=r["status"],
        ) for r in rows]

    @strawberry.field(description="재배치 제안 목록")
    def relocations(self) -> List[Relocation]:
        nm = {i["institutionId"]: i["institutionName"] for i in D.INSTITUTIONS}
        return [_to_relocation(r, nm) for r in D.RELOCATIONS]

    # ---- 알림 ----
    @strawberry.field(description="알림 목록 (severity/type/resolved/institution 필터)")
    def alerts(self, severity: Optional[str] = None, type: Optional[str] = None,
               resolved: Optional[bool] = None, institution: Optional[str] = None) -> List[Alert]:
        rows = DB.alerts_list(severity=severity, alert_type=type, resolved=resolved, institution=institution)
        return [_to_alert_db(a) for a in rows]

    @strawberry.field(description="알림 상세(근거 포함)")
    def alert(self, alert_id: str) -> Optional[Alert]:
        a = DB.alert_one(alert_id)
        return _to_alert_db(a) if a else None

    # ---- 외부지표 ----
    @strawberry.field(description="외부지표 시계열")
    def external_indicators(self) -> List[ExternalIndicator]:
        return [_to_indicator(i) for i in D.EXTERNAL_INDICATORS]

    # ---- 대시보드 ----
    @strawberry.field(description="중앙 뷰 대시보드")
    def dashboard_central(self) -> DashboardCentral:
        open_alerts = DB.alerts_list(resolved=False)
        sev: dict = {}
        for a in open_alerts:
            sev[a["severity"]] = sev.get(a["severity"], 0) + 1
        core = DB.dashboard_central_summary()
        top_shortage = [
            ShortageInstitution(institution_id=s["institutionId"], institution_name=s["institutionName"],
                                 shortage_items=s["shortageItems"])
            for s in DB.top_shortage_institutions(8)
        ]
        name = {g["itemGroupId"]: g["name"] for g in D.ITEM_GROUPS}
        risk_rank = sorted(
            [SupplyRiskRankItem(item_group_id=r["itemGroupId"], item_group_name=name.get(r["itemGroupId"]),
                                 risk_score=r["riskScore"], level=r["level"]) for r in D.SUPPLY_RISK],
            key=lambda x: x.risk_score, reverse=True)
        rel_nm = {i["institutionId"]: i["institutionName"] for i in D.INSTITUTIONS}
        return DashboardCentral(
            as_of=D.TODAY,
            summary=CentralSummary(
                institutions=core["institutions"], standard_items=len(D.STANDARD_ITEMS), item_groups=len(D.ITEM_GROUPS),
                open_alerts=len(open_alerts), total_on_hand=core["totalOnHand"],
                below_rop_items=core["belowRopItems"],
                critical_risk_groups=sum(1 for r in D.SUPPLY_RISK if r["level"] == "CRITICAL"),
            ),
            alerts_by_severity=sev,
            supply_risk_ranking=risk_rank,
            top_shortage_institutions=top_shortage,
            relocations=[_to_relocation(r, rel_nm) for r in D.RELOCATIONS],
        )

    @strawberry.field(description="기관 뷰 대시보드 (전국 3,598개 기관 전체 지원)")
    def dashboard_institution(self, institution_id: str) -> Optional[DashboardInstitution]:
        d = DB.dashboard_institution(institution_id)
        if not d:
            return None
        inst = d["institution"]
        return DashboardInstitution(
            as_of=D.TODAY,
            institution=DashboardInstitutionRef(
                institution_id=inst["id"], institution_name=inst["name"], institution_type=inst["type"],
                region_name=f"{inst['sido']} {inst['sigungu']}",
            ),
            summary=InstitutionDashboardSummary(
                tracked_items=d["summary"]["trackedItems"], below_rop=d["summary"]["belowRop"],
                order_needed=d["summary"]["orderNeeded"], open_alerts=d["summary"]["openAlerts"],
            ),
            inventory=[_to_inventory_item(r) for r in d["inventory"]],
            alerts=[_to_alert_db(a) for a in d["alerts"]],
        )


# ============================================================
# Mutation root (데모 목업 — 인증만)
# ============================================================

@strawberry.type
class Mutation:
    @strawberry.mutation(description="로그인(목업) — REST POST /auth/login 과 동일")
    def login(self, role: str = "CENTRAL", institution_id: Optional[str] = None) -> LoginResult:
        return LoginResult(
            access_token="demo.jwt.token", refresh_token="demo.refresh.token", expires_in=3600,
            user=Me(id="u_demo", role=role, institution_id=institution_id),
        )


schema = strawberry.Schema(query=Query, mutation=Mutation)
