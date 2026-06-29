"""WeP-Stock 데모용 시드 데이터.

명세(기능/데이터모델/API)에 맞춘 현실적인 의료물품 재고 도메인 데이터.
서버리스 인메모리 — 영속되지 않음. 시연/검증용.
실제 운영에서는 인테이크/표준화/예측/경보 파이프라인이 이 값들을 산출한다.
"""

TODAY = "2026-06-29"

# ---- 품목군 (item_group) ----
ITEM_GROUPS = [
    {"itemGroupId": "ig_plastic_consumable", "name": "플라스틱 소모품"},
    {"itemGroupId": "ig_rubber_latex", "name": "고무·라텍스"},
    {"itemGroupId": "ig_metal_instrument", "name": "금속 기구"},
    {"itemGroupId": "ig_textile", "name": "면·부직포"},
    {"itemGroupId": "ig_glass", "name": "유리"},
]

# ---- 표준품목 (standard_item) ----
STANDARD_ITEMS = [
    {"standardItemId": "si_KD0192", "standardCode": "KD0192", "standardName": "일회용 주사기 10mL", "itemGroupId": "ig_plastic_consumable", "uom": "EA", "shelfLifeDays": 1095, "criticality": "CONSUMABLE"},
    {"standardItemId": "si_KD0451", "standardCode": "KD0451", "standardName": "수액세트(IV set)", "itemGroupId": "ig_plastic_consumable", "uom": "EA", "shelfLifeDays": 1095, "criticality": "MEDICAL"},
    {"standardItemId": "si_KD2570", "standardCode": "KD2570", "standardName": "정맥 카테터 24G", "itemGroupId": "ig_plastic_consumable", "uom": "EA", "shelfLifeDays": 1095, "criticality": "MEDICAL"},
    {"standardItemId": "si_KD2031", "standardCode": "KD2031", "standardName": "인슐린 주사기 1mL", "itemGroupId": "ig_plastic_consumable", "uom": "EA", "shelfLifeDays": 730, "criticality": "MEDICAL"},
    {"standardItemId": "si_KD0820", "standardCode": "KD0820", "standardName": "라텍스 검진장갑(M)", "itemGroupId": "ig_rubber_latex", "uom": "BOX", "shelfLifeDays": 730, "criticality": "CONSUMABLE"},
    {"standardItemId": "si_KD1133", "standardCode": "KD1133", "standardName": "멸균거즈 10x10", "itemGroupId": "ig_textile", "uom": "PK", "shelfLifeDays": 1825, "criticality": "CONSUMABLE"},
    {"standardItemId": "si_KD1490", "standardCode": "KD1490", "standardName": "보건용 마스크 KF94", "itemGroupId": "ig_textile", "uom": "EA", "shelfLifeDays": 1095, "criticality": "CONSUMABLE"},
    {"standardItemId": "si_KD2244", "standardCode": "KD2244", "standardName": "수술용 봉합사", "itemGroupId": "ig_textile", "uom": "EA", "shelfLifeDays": 1460, "criticality": "MEDICAL"},
    {"standardItemId": "si_KD2899", "standardCode": "KD2899", "standardName": "디지털 체온계", "itemGroupId": "ig_metal_instrument", "uom": "EA", "shelfLifeDays": 3650, "criticality": "CONSUMABLE"},
    {"standardItemId": "si_KD3120", "standardCode": "KD3120", "standardName": "유리 채혈관", "itemGroupId": "ig_glass", "uom": "EA", "shelfLifeDays": 1095, "criticality": "CONSUMABLE"},
]
ITEM_BY_CODE = {it["standardCode"]: it for it in STANDARD_ITEMS}

# ---- 기관 (institution) ----
INSTITUTIONS = [
    {"institutionId": "inst_012", "institutionName": "강남구보건소", "institutionType": "HEALTH_CENTER", "regionCode": "11680", "regionName": "서울 강남구"},
    {"institutionId": "inst_023", "institutionName": "해운대구보건소", "institutionType": "HEALTH_CENTER", "regionCode": "26350", "regionName": "부산 해운대구"},
    {"institutionId": "inst_031", "institutionName": "중구보건소", "institutionType": "HEALTH_CENTER", "regionCode": "27110", "regionName": "대구 중구"},
    {"institutionId": "inst_044", "institutionName": "유성구보건소", "institutionType": "HEALTH_CENTER", "regionCode": "30200", "regionName": "대전 유성구"},
    {"institutionId": "inst_058", "institutionName": "완주군보건소", "institutionType": "HEALTH_CENTER", "regionCode": "45710", "regionName": "전북 완주군"},
    {"institutionId": "inst_066", "institutionName": "춘천시보건소", "institutionType": "HEALTH_CENTER", "regionCode": "51110", "regionName": "강원 춘천시"},
    {"institutionId": "inst_071", "institutionName": "남원읍보건지소", "institutionType": "BRANCH", "regionCode": "50130", "regionName": "제주 서귀포시"},
    {"institutionId": "inst_085", "institutionName": "신안군 도서진료소", "institutionType": "CLINIC", "regionCode": "46900", "regionName": "전남 신안군"},
]
INST_BY_ID = {i["institutionId"]: i for i in INSTITUTIONS}

# ---- 공급위험 (supply_risk) ----
SUPPLY_RISK = [
    {"itemGroupId": "ig_plastic_consumable", "date": TODAY, "riskScore": 82, "level": "CRITICAL", "leadTimeEstimate": 21, "confidence": 0.73,
     "topContributors": [{"materialType": "naphtha", "contrib": 0.51, "lagDays": 14}, {"materialType": "crude_oil", "contrib": 0.22, "lagDays": 20}],
     "evidenceNews": [{"newsId": "n_771", "title": "호르무즈 해협 긴장 고조…원유·나프타 가격 급등", "url": "https://news.example.go.kr/771", "publishedAt": "2026-06-27"},
                      {"newsId": "n_769", "title": "국내 PP·PVC 스프레드 8주 연속 확대", "url": "https://news.example.go.kr/769", "publishedAt": "2026-06-24"}]},
    {"itemGroupId": "ig_rubber_latex", "date": TODAY, "riskScore": 64, "level": "WARNING", "leadTimeEstimate": 18, "confidence": 0.62,
     "topContributors": [{"materialType": "natural_rubber", "contrib": 0.42, "lagDays": 25}],
     "evidenceNews": [{"newsId": "n_752", "title": "동남아 천연고무 작황 부진…수급 경고", "url": "https://news.example.go.kr/752", "publishedAt": "2026-06-22"}]},
    {"itemGroupId": "ig_textile", "date": TODAY, "riskScore": 47, "level": "CAUTION", "leadTimeEstimate": 25, "confidence": 0.55,
     "topContributors": [{"materialType": "cotton", "contrib": 0.28, "lagDays": 30}],
     "evidenceNews": [{"newsId": "n_740", "title": "면화 선물 강세 지속", "url": "https://news.example.go.kr/740", "publishedAt": "2026-06-18"}]},
    {"itemGroupId": "ig_metal_instrument", "date": TODAY, "riskScore": 33, "level": "CAUTION", "leadTimeEstimate": 30, "confidence": 0.5,
     "topContributors": [{"materialType": "nickel", "contrib": 0.21, "lagDays": 35}],
     "evidenceNews": [{"newsId": "n_733", "title": "니켈 LME 재고 감소세", "url": "https://news.example.go.kr/733", "publishedAt": "2026-06-15"}]},
    {"itemGroupId": "ig_glass", "date": TODAY, "riskScore": 18, "level": "NORMAL", "leadTimeEstimate": 28, "confidence": 0.48,
     "topContributors": [], "evidenceNews": []},
]
RISK_BY_GROUP = {r["itemGroupId"]: r for r in SUPPLY_RISK}


def _z_for_level(level):
    return {"NORMAL": 1.28, "CAUTION": 1.65, "WARNING": 2.05, "CRITICAL": 2.33}.get(level, 1.28)


# ---- 재고/적정재고 (inventory + inventory_policy) 생성 ----
# (institution, code, on_hand, available, mu, sigma, base_lead)
_INV_RAW = [
    ("inst_012", "KD0192", 420, 410, 180.0, 52.0, 1.0),
    ("inst_012", "KD0451", 38, 30, 60.0, 22.0, 1.2),
    ("inst_012", "KD0820", 12, 9, 25.0, 11.0, 1.0),
    ("inst_012", "KD1490", 1500, 1500, 800.0, 240.0, 1.0),
    ("inst_012", "KD2570", 64, 58, 40.0, 18.0, 1.3),
    ("inst_023", "KD0192", 90, 80, 150.0, 60.0, 1.1),
    ("inst_023", "KD0820", 4, 2, 22.0, 12.0, 1.0),
    ("inst_023", "KD1133", 210, 205, 90.0, 28.0, 1.0),
    ("inst_031", "KD0451", 120, 118, 45.0, 15.0, 1.2),
    ("inst_031", "KD2031", 30, 22, 35.0, 16.0, 1.4),
    ("inst_044", "KD0192", 600, 590, 170.0, 48.0, 1.0),
    ("inst_044", "KD2244", 8, 5, 18.0, 9.0, 1.5),
    ("inst_058", "KD1490", 120, 110, 300.0, 130.0, 1.2),
    ("inst_058", "KD0820", 60, 55, 20.0, 10.0, 1.1),
    ("inst_066", "KD2570", 14, 9, 38.0, 17.0, 1.3),
    ("inst_066", "KD3120", 300, 295, 80.0, 24.0, 1.0),
    ("inst_071", "KD1133", 24, 20, 30.0, 14.0, 1.4),
    ("inst_085", "KD0451", 6, 3, 12.0, 7.0, 1.8),
    ("inst_085", "KD1490", 40, 35, 60.0, 30.0, 1.6),
]


def _build_inventory():
    rows = []
    for inst, code, on_hand, avail, mu, sigma, base_l in _INV_RAW:
        item = ITEM_BY_CODE[code]
        risk = RISK_BY_GROUP.get(item["itemGroupId"], {"level": "NORMAL"})
        level = risk["level"]
        z = _z_for_level(level)
        l_mult = {"NORMAL": 1.0, "CAUTION": 1.1, "WARNING": 1.25, "CRITICAL": 1.5}.get(level, 1.0)
        L = round(base_l * l_mult, 2)
        ss = round(z * sigma * (L ** 0.5), 1)
        rop = round(mu * L + ss, 1)
        target = round(mu * (L + 1.0) + ss, 1)
        inbound = 0
        rec = max(0, round(target - avail - inbound))
        if rec > 0:  # MOQ/포장단위 올림(10단위)
            rec = int((rec + 9) // 10 * 10)
        if avail < rop * 0.5:
            status = "CRITICAL"
        elif avail < rop:
            status = "BELOW_ROP"
        elif avail < rop * 1.3:
            status = "WATCH"
        else:
            status = "OK"
        rows.append({
            "institutionId": inst,
            "institutionName": INST_BY_ID[inst]["institutionName"],
            "standardCode": code,
            "standardName": item["standardName"],
            "itemGroupId": item["itemGroupId"],
            "criticality": item["criticality"],
            "uom": item["uom"],
            "onHand": on_hand,
            "available": avail,
            "mu": mu,
            "sigma": sigma,
            "leadTimeUsed": L,
            "zUsed": z,
            "SS": ss,
            "ROP": rop,
            "target": target,
            "orderRecommendation": rec,
            "supplyRiskLevel": level,
            "status": status,
            "assumedLeadTime": True,
        })
    return rows


INVENTORY = _build_inventory()

# ---- 알림 (alert) ----
ALERTS = [
    {"alertId": "al_5001", "alertType": "STOCK_BELOW_ROP", "severity": "CRITICAL", "institutionId": "inst_085", "standardCode": "KD0451",
     "generatedAt": TODAY + "T08:12:00Z", "resolvedAt": None, "title": "수액세트 재고 미달(가용 3 < ROP)",
     "message": "신안군 도서진료소 수액세트 가용재고가 재주문점 아래입니다. 리드타임 가정값(섬 지역) 적용.", "evidence": {"available": 3, "ROP": 16.2}},
    {"alertId": "al_5002", "alertType": "STOCK_BELOW_ROP", "severity": "CRITICAL", "institutionId": "inst_023", "standardCode": "KD0820",
     "generatedAt": TODAY + "T08:12:00Z", "resolvedAt": None, "title": "라텍스 장갑 재고 미달(가용 2)",
     "message": "해운대구보건소 라텍스 검진장갑 가용재고가 위험 수준입니다.", "evidence": {"available": 2, "ROP": 16.0}},
    {"alertId": "al_5003", "alertType": "SUPPLY_RISK", "severity": "CRITICAL", "institutionId": None, "itemGroupId": "ig_plastic_consumable",
     "generatedAt": TODAY + "T07:00:00Z", "resolvedAt": None, "title": "플라스틱 소모품 공급위험 CRITICAL(82)",
     "message": "나프타 급등·호르무즈 긴장 영향. 주사기/수액세트/카테터 선제 발주 권고. 선행 약 14일.", "evidence": {"riskScore": 82, "leadDays": 14}},
    {"alertId": "al_5004", "alertType": "SUPPLY_RISK", "severity": "WARNING", "institutionId": None, "itemGroupId": "ig_rubber_latex",
     "generatedAt": TODAY + "T07:00:00Z", "resolvedAt": None, "title": "고무·라텍스 공급위험 WARNING(64)",
     "message": "천연고무 작황 부진. 라텍스 장갑 버퍼 상향 권고.", "evidence": {"riskScore": 64}},
    {"alertId": "al_5005", "alertType": "STOCK_BELOW_ROP", "severity": "WARNING", "institutionId": "inst_044", "standardCode": "KD2244",
     "generatedAt": TODAY + "T08:12:00Z", "resolvedAt": None, "title": "수술용 봉합사 재고 미달", "message": "유성구보건소 봉합사 가용 5.", "evidence": {"available": 5, "ROP": 14.0}},
    {"alertId": "al_5006", "alertType": "EXPIRY", "severity": "WARNING", "institutionId": "inst_012", "standardCode": "KD0820",
     "generatedAt": TODAY + "T06:30:00Z", "resolvedAt": None, "title": "라텍스 장갑 유효기간 임박(D-45)", "message": "강남구보건소 로트 LOT-0820-A FEFO 우선 소진 권고.", "evidence": {"daysToExpiry": 45, "lot": "LOT-0820-A"}},
    {"alertId": "al_5007", "alertType": "STOCK_BELOW_ROP", "severity": "WARNING", "institutionId": "inst_066", "standardCode": "KD2570",
     "generatedAt": TODAY + "T08:12:00Z", "resolvedAt": None, "title": "정맥 카테터 재고 미달", "message": "춘천시보건소 카테터 가용 9.", "evidence": {"available": 9, "ROP": 60.6}},
    {"alertId": "al_5008", "alertType": "EXPIRY", "severity": "CAUTION", "institutionId": "inst_058", "standardCode": "KD1490",
     "generatedAt": TODAY + "T06:30:00Z", "resolvedAt": TODAY + "T09:40:00Z", "title": "마스크 유효기간 임박(D-80)", "message": "완주군보건소 마스크 재배치 검토.", "evidence": {"daysToExpiry": 80}},
]

# ---- 재배치 제안 (relocation_suggestion) ----
RELOCATIONS = [
    {"id": "rl_9001", "fromInstitution": "inst_044", "toInstitution": "inst_085", "standardCode": "KD0451", "suggestedQty": 40, "reason": "부족↔여유 매칭(권역 인접·FEFO)", "status": "제안"},
    {"id": "rl_9002", "fromInstitution": "inst_012", "toInstitution": "inst_023", "standardCode": "KD0820", "suggestedQty": 30, "reason": "유효기간 임박 재고 우선 소진", "status": "제안"},
    {"id": "rl_9003", "fromInstitution": "inst_066", "toInstitution": "inst_071", "standardCode": "KD1133", "suggestedQty": 20, "reason": "거리 최소·여유분 이전", "status": "승인"},
]

# ---- 수요예측 (demand_forecast_monthly) 샘플 ----
FORECASTS = {
    ("inst_012", "KD0451"): {"institutionId": "inst_012", "standardCode": "KD0451", "patternClass": "INTERMITTENT", "championModel": "SBA", "modelVersion": "b-2026.06",
        "horizon": [
            {"month": "2026-07", "mean": 62.0, "q10": 38, "q50": 60, "q90": 92, "confidence": 0.61},
            {"month": "2026-08", "mean": 65.0, "q10": 40, "q50": 63, "q90": 98, "confidence": 0.60},
            {"month": "2026-09", "mean": 70.0, "q10": 44, "q50": 68, "q90": 105, "confidence": 0.58}],
        "dataQualityFlag": "ok"},
    ("inst_023", "KD0820"): {"institutionId": "inst_023", "standardCode": "KD0820", "patternClass": "LUMPY", "championModel": "TSB", "modelVersion": "b-2026.06",
        "horizon": [
            {"month": "2026-07", "mean": 23.0, "q10": 6, "q50": 20, "q90": 48, "confidence": 0.52},
            {"month": "2026-08", "mean": 26.0, "q10": 8, "q50": 24, "q90": 55, "confidence": 0.50}],
        "dataQualityFlag": "ok"},
}

# ---- 적재 배치 (import_batch) ----
IMPORTS = [
    {"importBatchId": "ib_20260629_001", "fileName": "2026-06_보건소_통합.xlsx", "sourceVendor": "v_03", "status": "COMPLETED", "uploadedAt": TODAY + "T05:10:00Z",
     "totalRows": 18420, "validRows": 18197, "errorRows": 223, "mappingRate": 0.967, "periodStart": "2026-06-01", "periodEnd": "2026-06-28"},
    {"importBatchId": "ib_20260629_002", "fileName": "2026-06_의료용품_주간.xlsx", "sourceVendor": "v_01", "status": "LOADING", "uploadedAt": TODAY + "T08:40:00Z",
     "totalRows": 5102, "validRows": 5090, "errorRows": 12, "mappingRate": 0.981, "periodStart": "2026-06-22", "periodEnd": "2026-06-28"},
    {"importBatchId": "ib_20260628_004", "fileName": "2026-06_도서지역.xlsx", "sourceVendor": "v_07", "status": "VALIDATION_FAILED", "uploadedAt": "2026-06-28T14:02:00Z",
     "totalRows": 980, "validRows": 0, "errorRows": 980, "mappingRate": 0.0, "periodStart": "2026-06-01", "periodEnd": "2026-06-27"},
    {"importBatchId": "ib_20260627_003", "fileName": "2026-05_월간_전체.xlsx", "sourceVendor": "v_03", "status": "COMPLETED", "uploadedAt": "2026-06-27T03:00:00Z",
     "totalRows": 17110, "validRows": 16980, "errorRows": 130, "mappingRate": 0.972, "periodStart": "2026-05-01", "periodEnd": "2026-05-31"},
]

# ---- 표준화 검수 큐 (standardization queue) ----
STD_QUEUE = [
    {"rawItemId": "raw_8842", "rawName": "10cc 일회용주사기", "topCandidate": {"standardCode": "KD0192", "standardName": "일회용 주사기 10mL", "score": 0.71}, "status": "NEEDS_REVIEW"},
    {"rawItemId": "raw_8855", "rawName": "라텍스장갑(중)", "topCandidate": {"standardCode": "KD0820", "standardName": "라텍스 검진장갑(M)", "score": 0.83}, "status": "NEEDS_REVIEW"},
    {"rawItemId": "raw_8861", "rawName": "거즈10X10멸균", "topCandidate": {"standardCode": "KD1133", "standardName": "멸균거즈 10x10", "score": 0.9}, "status": "AUTO_ACCEPT"},
    {"rawItemId": "raw_8890", "rawName": "수액쎄트", "topCandidate": {"standardCode": "KD0451", "standardName": "수액세트(IV set)", "score": 0.66}, "status": "NEEDS_REVIEW"},
    {"rawItemId": "raw_8902", "rawName": "체온계(디지털) 신규", "topCandidate": None, "status": "NO_MATCH"},
]

# ---- 외부지표 (external_indicator) ----
EXTERNAL_INDICATORS = [
    {"indicatorId": "ei_naphtha", "sourceSystem": "PETRONET", "indicatorType": "naphtha_price", "unit": "USD/T", "granularity": "DAILY",
     "latest": [{"observedAt": "2026-06-25", "value": 712}, {"observedAt": "2026-06-26", "value": 738}, {"observedAt": "2026-06-27", "value": 781}, {"observedAt": "2026-06-29", "value": 803}]},
    {"indicatorId": "ei_news_risk", "sourceSystem": "NEWS", "indicatorType": "news_risk_index", "unit": "0-100", "granularity": "DAILY",
     "latest": [{"observedAt": "2026-06-25", "value": 41}, {"observedAt": "2026-06-26", "value": 53}, {"observedAt": "2026-06-27", "value": 76}, {"observedAt": "2026-06-29", "value": 72}]},
    {"indicatorId": "ei_rubber", "sourceSystem": "PETRONET", "indicatorType": "natural_rubber_price", "unit": "USD/T", "granularity": "DAILY",
     "latest": [{"observedAt": "2026-06-25", "value": 1620}, {"observedAt": "2026-06-27", "value": 1685}, {"observedAt": "2026-06-29", "value": 1722}]},
]
