"""Shared development-request fields; only these fields reach the research form/PDF.

화면(직접 작성·편집)·자동변환·인쇄/PDF·저장 계약 v1(contract.py)이 모두 이 정의를 씁니다.
FIX(10.19) 반영: 목표 가격대(금액+통화 목록), SPF/PA, 컨셉 원료(필수·선호, 함유 필수 여부, 효능 태그),
R&D 확인 요청사항, 용기(참고값), 스킨케어 세부 유형, 점도(선택값 + 서술). 매핑표: docs/data_contract.md 4-3
"""

PRODUCT_TYPES = ["스킨케어", "베이스 메이크업", "립", "아이", "바디", "헤어", "클렌징", "선케어", "기타"]
SKINCARE_TYPES = ["토너", "스킨", "세럼", "앰플", "크림", "로션"]            # 확정(FIX) — product_type == 스킨케어 일 때만
REQUEST_SOURCES = ["고객사 요청", "자사기획"]
SAMPLE_TYPES = ["신규 샘플", "개선 샘플"]
APPLICATION_TYPES = ["Leave-on", "Rinse-off", "기타", "확인 필요"]
# 점도 드롭다운 값 — **미정**. FIX 는 "서술형 + 드롭다운" 구조만 정했고 값 목록 근거가 없어 비워 둡니다.
# 값이 정해지면 여기에 추가합니다. 비어 있는 동안 화면은 서술형만 받고, 저장 계약은 "" 만 허용합니다.
VISCOSITY_LEVELS: list[str] = []
CONCEPT_KINDS = {"necessary": "필수 원료", "ideal": "선호 원료"}
CURRENCIES = ["KRW", "USD", "EUR", "JPY", "CNY"]   # 화면 선택 목록. 저장 계약은 ISO 4217 형식(대문자 3글자)이면 허용
LEGACY_PRICE_TIERS = {"low": "저가", "mid": "중가", "high": "고가"}   # 이전 형식 — 금액으로 바꾸지 않음 (data_contract.md 4-4)

SECTIONS = [
    ("01 기본정보", [
        ("customer", "고객사", "text"), ("request_source", "요청 구분", "request_source"), ("product_name", "품명(가칭)", "text"),
        ("sample_request_type", "샘플 구분", "sample_type"),
        ("product_type", "제품 유형", "type"), ("target_prices", "목표 가격대", "prices"),
        ("export_countries", "수출 대상국", "list"),
        ("company_description", "업체 설명", "textarea"),
        ("basic_notes", "기타사항", "textarea"),
    ]),
    ("02 제품 개발 요구사항", [
        ("benchmark_product_name", "벤치마크 제품명", "text"),
        ("product_development.application_type", "사용 타입", "application"),
        ("product_development.product_description", "제품 설명", "textarea"),
        ("product_development.formula_guidelines", "처방 가이드", "textarea"),
        ("product_development.texture", "제형 / 텍스처", "textarea"),
        ("product_development.appearance_sensory", "사용감 / 외관", "textarea"),
        ("product_development.viscosity", "점도", "viscosity"),
        ("product_development.spf", "SPF", "text"),
        ("product_development.pa", "PA", "text"),
        ("product_development.container_reference", "용기 (참고값)", "textarea"),
        ("product_development.fragrance_flavor", "향 / Flavor", "text"),
        ("product_development.finish", "피니시", "text"),
        ("product_development.coverage", "커버력", "text"),
        ("product_development.color_shade_reference", "컬러 / 쉐이드 참고", "textarea"),
        ("product_development.other_requirements", "기타 요구사항", "textarea"),
    ]),
    ("03 원료 요구사항", [
        ("buyer_prohibited_ingredients", "수출 금지 원료", "list"),
        ("ingredients.concept", "컨셉 원료", "concept"),
        ("ingredients.other_notes", "기타사항", "textarea"),
        ("rnd_check_requests", "R&D 확인 요청사항", "textarea"),
    ]),
    ("04 품질 확인사항", [
        ("quality.tests", "품질 확인 테스트", "list"),
        ("quality.additional_notes", "품질 관련 추가사항", "textarea"),
    ]),
]
FIELDS = {key: kind for _, fields in SECTIONS for key, _, kind in fields}
FIELDS.update({"product_type_custom": "text", "product_type_detail": "skincare_type",
               "product_development.viscosity_level": "viscosity_level",
               "regulatory_restricted_ingredients": "list", "reference_notes": "textarea"})
LABELS = {key: label for _, fields in SECTIONS for key, label, _ in fields}
LABELS.update(product_type_custom="제품 유형 직접 입력", product_type_detail="스킨케어 세부 유형",
              **{"product_development.viscosity_level": "점도 선택값"},
              regulatory_restricted_ingredients="규제 검토 대상 원료", reference_notes="참고자료 기타사항")

# 자동변환(AI)이 채우지 않는 칸 — 원문에서 근거 있게 뽑을 수 없거나 다른 탭에서 반영할 칸
#   target_prices: 바이어 Target Cost 는 원문 보존 데이터로만 두고 금액 칸은 사용자가 직접 입력 (이전 low/mid/high 는 참고 표시)
#   viscosity_level: 값 목록 미정 / container_reference: 모델링 용기 적합성 반영 칸 / rnd_check_requests: 규제 메모 반영 칸
#   ingredients.concept: 아래 이전 형식 목록(necessary·ideal)으로 추출한 뒤 kind 만 채워 옮김 (함유 필수·효능 태그는 비움)
NOT_EXTRACTED = {"target_prices", "product_development.viscosity_level", "product_development.container_reference",
                 "rnd_check_requests", "ingredients.concept"}
LEGACY_EXTRACTED = {"target_price_tier": "tier", "ingredients.necessary": "list", "ingredients.ideal": "list"}
EXTRACTED_FIELDS = {key: kind for key, kind in FIELDS.items() if key not in NOT_EXTRACTED}
EXTRACTED_FIELDS.update(LEGACY_EXTRACTED)


def get_value(data, path, default=None):
    for key in path.split("."):
        if not isinstance(data, dict) or key not in data:
            return default
        data = data[key]
    return data


def set_value(data, path, value):
    keys = path.split(".")
    for key in keys[:-1]:
        data = data.setdefault(key, {})
    data[keys[-1]] = value


def empty_value(kind):
    return [] if kind in ("list", "prices", "concept") else None if kind == "required" else ""


def blank_inputs() -> dict:
    """저장 계약 v1 inputs 의 빈 구조 (customer 제외 — 고객사는 context 의 id 로). 화면 빈 양식과 같은 모양."""
    inputs: dict = {}
    for key, kind in FIELDS.items():
        if key != "customer":
            set_value(inputs, key, empty_value(kind))
    return inputs


def page_options() -> dict:
    """화면(requisition.js)에 내려보내는 선택값·빈 구조. 서버 계약과 같은 값을 쓰기 위해 여기서만 정의합니다."""
    return {"product_types": PRODUCT_TYPES, "skincare_types": SKINCARE_TYPES, "request_sources": REQUEST_SOURCES,
            "sample_types": SAMPLE_TYPES, "application_types": APPLICATION_TYPES, "viscosity_levels": VISCOSITY_LEVELS,
            "concept_kinds": CONCEPT_KINDS, "currencies": CURRENCIES, "legacy_price_tiers": LEGACY_PRICE_TIERS,
            "input_defaults": blank_inputs(), "labels": LABELS}
