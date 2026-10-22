"""개발요청서 저장 계약 v1 (tab_versions.schema_version = 1) — 서버 검증. 문서: docs/data_contract.md 4장

공통 검증(src/common/payloads.py)이 저장 제외 필드를 지우고 파일 본문을 거부한 **뒤** 이 검사를 합니다.
이 검사를 통과하면 응답 validation.fully_validated = true 입니다.

기준
- 구조: context / inputs / outputs / meta 의 정해진 키가 **모두 있어야** 합니다 (빈 값은 "" 또는 []).
  정해지지 않은 키는 400 (unknown_field). null 은 ingredients.concept[].must_contain(미확인)과 field_provenance[].user_value 만 허용.
- 자료형·허용값: 아래 _INPUT_RULES. 문자열은 앞뒤 공백 그대로 저장(화면이 정리), 길이 상한만 검사.
- 필수값: REQUIRED_INPUTS (화면의 "작성 완료" 필수 항목과 같음). 고객사는 context.customer_id 로 확인.
- 고객사·프로젝트는 id 로 식별합니다. 이름(context.customer_name / project_name)은 저장 시 서버가 DB 값으로 덮어씁니다 (versions.py).
"""

from __future__ import annotations

import math
import re

from src.common.payloads import PayloadError

from .schema import (APPLICATION_TYPES, CONCEPT_KINDS, FIELDS, LEGACY_PRICE_TIERS, PRODUCT_TYPES, REQUEST_SOURCES,
                     SAMPLE_TYPES, SKINCARE_TYPES, VISCOSITY_LEVELS, blank_inputs)

TEXT_MAX = 10000          # 서술·한 줄 입력 (화면 maxlength 와 같음)
LIST_MAX = 50             # 목록 항목 수 (화면·자동변환과 같음)
ITEM_MAX = 300            # 목록 항목 한 개 길이 (자동변환과 같음)
PRICES_MAX = 10           # 목표 가격대 수
AMOUNT_MAX = 1_000_000_000_000
TAGS_MAX = 10             # 원료 하나의 효능 태그 수
TAG_MAX = 50
SHORT_MAX = 50            # SPF / PA / 언어 이름
PROVENANCE_MAX = 200

CREATION_METHODS = ("auto", "auto_edited", "manual", "manual_edited")
TARGET_LANGUAGES = ("ko", "en", "zh", "ja", "fr", "de", "es")
INPUT_SOURCES = ("auto", "user_edited")
REVIEW_STATUSES = ("confirmed", "needs_review", "missing", "not_applicable", "user_edited")
REQUIRED_INPUTS = ("request_source", "product_name", "sample_request_type", "product_type", "export_countries", "quality.tests")
CONTEXT_KEYS = ("customer_id", "customer_name", "project_id", "project_name", "creation_method", "source_language",
                "target_language", "source_file_name")
META_KEYS = ("field_provenance", "reference_files")
META_OPTIONAL_KEYS = ("legacy_fields",)
_CURRENCY = re.compile(r"[A-Z]{3}")


def _fail(message: str, path: str, code: str = "invalid_payload"):
    raise PayloadError(message, path, code)


def _leaf_paths(tree: dict, prefix: str = "") -> list[str]:
    out = []
    for key, value in tree.items():
        path = f"{prefix}{key}"
        out.extend(_leaf_paths(value, path + ".") if isinstance(value, dict) else [path])
    return out


INPUT_TEMPLATE = blank_inputs()
INPUT_PATHS = _leaf_paths(INPUT_TEMPLATE)
PROVENANCE_FIELD_KEYS = frozenset(INPUT_PATHS) | {"customer"}


# --- 값 검사 --------------------------------------------------------------------

def _text(value, path, max_len=TEXT_MAX):
    if not isinstance(value, str):
        _fail("문자열이어야 합니다.", path)
    if len(value) > max_len:
        _fail(f"{max_len}자 이하여야 합니다.", path)


def _enum(options):
    def check(value, path):
        if value != "" and value not in options:
            _fail(f"허용하지 않는 값입니다. (빈 값 또는 {', '.join(options) if options else '선택값 미정'})", path,
                  "invalid_value")
    return check


def _string_enum(options):
    def check(value, path):
        _text(value, path)
        _enum(options)(value, path)
    return check


def _string_list(value, path):
    if not isinstance(value, list):
        _fail("목록이어야 합니다.", path)
    if len(value) > LIST_MAX:
        _fail(f"항목은 {LIST_MAX}개까지입니다.", path)
    seen = set()
    for i, item in enumerate(value):
        _text(item, f"{path}[{i}]", ITEM_MAX)
        if not item.strip():
            _fail("빈 항목은 넣지 않습니다.", f"{path}[{i}]")
        folded = item.strip().casefold()
        if folded in seen:
            _fail("같은 항목이 중복됩니다.", f"{path}[{i}]", "duplicate_value")
        seen.add(folded)


def _prices(value, path):
    if not isinstance(value, list):
        _fail("목록이어야 합니다.", path)
    if len(value) > PRICES_MAX:
        _fail(f"목표 가격대는 {PRICES_MAX}개까지입니다.", path)
    seen = set()
    for i, item in enumerate(value):
        p = f"{path}[{i}]"
        if not isinstance(item, dict):
            _fail("목표 가격대는 {amount, currency} 객체여야 합니다.", p)
        _exact_keys(item, ("amount", "currency"), p)
        amount, currency = item["amount"], item["currency"]
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) \
                or amount <= 0 or amount > AMOUNT_MAX:
            _fail("amount 는 0보다 큰 숫자여야 합니다.", p + ".amount")
        if not isinstance(currency, str) or not _CURRENCY.fullmatch(currency):
            _fail("currency 는 ISO 통화 코드 대문자 3글자여야 합니다 (예: KRW).", p + ".currency")
        if (amount, currency) in seen:
            _fail("같은 목표 가격대가 중복됩니다.", p, "duplicate_value")
        seen.add((amount, currency))


def _concept(value, path):
    if not isinstance(value, list):
        _fail("목록이어야 합니다.", path)
    if len(value) > LIST_MAX:
        _fail(f"컨셉 원료는 {LIST_MAX}개까지입니다.", path)
    seen = set()
    for i, item in enumerate(value):
        p = f"{path}[{i}]"
        if not isinstance(item, dict):
            _fail("컨셉 원료는 객체여야 합니다.", p)
        _exact_keys(item, ("name", "kind", "must_contain", "efficacy_tags"), p)
        _text(item["name"], p + ".name", ITEM_MAX)
        if not item["name"].strip():
            _fail("원료명이 필요합니다.", p + ".name")
        if item["kind"] not in CONCEPT_KINDS:
            _fail(f"kind 는 {', '.join(CONCEPT_KINDS)} 중 하나여야 합니다.", p + ".kind", "invalid_value")
        if item["must_contain"] not in (True, False, None):
            _fail("must_contain 은 true / false / null(미확인) 이어야 합니다.", p + ".must_contain")
        tags = item["efficacy_tags"]
        if not isinstance(tags, list) or len(tags) > TAGS_MAX:
            _fail(f"efficacy_tags 는 {TAGS_MAX}개 이하의 목록이어야 합니다.", p + ".efficacy_tags")
        tag_seen = set()
        for j, tag in enumerate(tags):
            _text(tag, f"{p}.efficacy_tags[{j}]", TAG_MAX)
            if not tag.strip() or tag.strip().casefold() in tag_seen:
                _fail("빈 태그나 중복 태그는 넣지 않습니다.", f"{p}.efficacy_tags[{j}]", "duplicate_value")
            tag_seen.add(tag.strip().casefold())
        folded = item["name"].strip().casefold()
        if folded in seen:                      # 같은 원료를 필수·선호에 함께 두지 않음
            _fail("같은 원료가 중복됩니다.", p + ".name", "duplicate_value")
        seen.add(folded)


_KIND_RULES = {
    "text": _text, "textarea": _text, "list": _string_list, "prices": _prices, "concept": _concept,
    "viscosity": _text,
    "request_source": _string_enum(REQUEST_SOURCES), "sample_type": _string_enum(SAMPLE_TYPES),
    "type": _string_enum(PRODUCT_TYPES), "skincare_type": _string_enum(SKINCARE_TYPES),
    "application": _string_enum(APPLICATION_TYPES), "viscosity_level": _string_enum(VISCOSITY_LEVELS),
}
_SHORT_TEXT = {"product_development.spf", "product_development.pa"}


def _exact_keys(obj: dict, keys, path: str) -> None:
    missing = [k for k in keys if k not in obj]
    if missing:
        _fail(f"필요한 키가 없습니다: {', '.join(missing)}", f"{path}.{missing[0]}" if path else missing[0], "missing_field")
    extra = [k for k in obj if k not in keys]
    if extra:
        _fail(f"계약에 없는 키입니다: {', '.join(extra)}", f"{path}.{extra[0]}" if path else extra[0], "unknown_field")


def _check_tree(value, template: dict, path: str) -> None:
    if not isinstance(value, dict):
        _fail("객체여야 합니다.", path)
    _exact_keys(value, tuple(template), path)
    for key, sub in template.items():
        p = f"{path}.{key}"
        if isinstance(sub, dict):
            _check_tree(value[key], sub, p)


def _check_inputs(inputs: dict) -> None:
    _check_tree(inputs, INPUT_TEMPLATE, "inputs")
    get = lambda key: _get(inputs, key)   # noqa: E731
    for key in INPUT_PATHS:
        rule = _KIND_RULES[FIELDS[key]]
        if key in _SHORT_TEXT:
            _text(get(key), f"inputs.{key}", SHORT_MAX)
        else:
            rule(get(key), f"inputs.{key}")
    # 서로 묶인 값
    if get("product_type") != "스킨케어" and get("product_type_detail"):
        _fail("스킨케어 세부 유형은 제품 유형이 스킨케어일 때만 넣습니다.", "inputs.product_type_detail", "invalid_value")
    if get("product_type") != "기타" and get("product_type_custom"):
        _fail("제품 유형 직접 입력은 제품 유형이 기타일 때만 넣습니다.", "inputs.product_type_custom", "invalid_value")
    # 필수값
    missing = [key for key in REQUIRED_INPUTS if not (get(key).strip() if isinstance(get(key), str) else get(key))]
    if get("product_type") == "기타" and not get("product_type_custom").strip():
        missing.append("product_type_custom")
    if missing:
        _fail(f"필수 항목이 비어 있습니다: {', '.join(missing)}", f"inputs.{missing[0]}", "required_field")


def _get(data: dict, path: str):
    for key in path.split("."):
        data = data[key]
    return data


def _check_context(context: dict) -> None:
    _exact_keys(context, CONTEXT_KEYS, "context")
    for key in ("customer_id", "project_id"):
        value = context[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            _fail("고객사·프로젝트는 id(양의 정수)로 연결합니다.", f"context.{key}", "invalid_value")
    for key in ("customer_name", "project_name", "source_file_name"):
        _text(context[key], f"context.{key}", 300)
    if context["creation_method"] not in CREATION_METHODS:
        _fail(f"creation_method 는 {', '.join(CREATION_METHODS)} 중 하나여야 합니다.", "context.creation_method", "invalid_value")
    _text(context["source_language"], "context.source_language", SHORT_MAX)
    if context["target_language"] not in TARGET_LANGUAGES:
        _fail("target_language 가 올바르지 않습니다.", "context.target_language", "invalid_value")


def _check_meta(meta: dict) -> None:
    missing = [k for k in META_KEYS if k not in meta]
    if missing:
        _fail(f"필요한 키가 없습니다: {', '.join(missing)}", f"meta.{missing[0]}", "missing_field")
    extra = [k for k in meta if k not in META_KEYS + META_OPTIONAL_KEYS]
    if extra:
        _fail(f"계약에 없는 키입니다: {', '.join(extra)}", f"meta.{extra[0]}", "unknown_field")
    provenance = meta["field_provenance"]
    if not isinstance(provenance, list) or len(provenance) > PROVENANCE_MAX:
        _fail(f"field_provenance 는 {PROVENANCE_MAX}개 이하의 목록이어야 합니다.", "meta.field_provenance")
    for i, item in enumerate(provenance):          # 허용 키 밖은 공통 검증이 이미 제거 (removed_fields)
        p = f"meta.field_provenance[{i}]"
        _exact_keys(item, ("field_key", "source_value", "source_page", "input_source", "review_status", "user_value"), p)
        if item["field_key"] not in PROVENANCE_FIELD_KEYS:
            _fail("알 수 없는 필드의 출처입니다.", p + ".field_key", "unknown_field")
        _text(item["source_value"], p + ".source_value", 2000)
        _text(item["source_page"], p + ".source_page", 100)
        if item["input_source"] not in INPUT_SOURCES:
            _fail(f"input_source 는 {', '.join(INPUT_SOURCES)} 중 하나여야 합니다.", p + ".input_source", "invalid_value")
        if item["review_status"] not in REVIEW_STATUSES:
            _fail("review_status 가 올바르지 않습니다.", p + ".review_status", "invalid_value")
    files = meta["reference_files"]
    if not isinstance(files, list) or len(files) > 20:
        _fail("reference_files 는 20개 이하의 목록이어야 합니다.", "meta.reference_files")
    for i, item in enumerate(files):
        _exact_keys(item, ("name", "size", "type"), f"meta.reference_files[{i}]")
        _text(item["name"], f"meta.reference_files[{i}].name", 255)
        _text(item["type"], f"meta.reference_files[{i}].type", 100)
    if "legacy_fields" in meta:
        legacy = meta["legacy_fields"]
        if not isinstance(legacy, dict):
            _fail("legacy_fields 는 객체여야 합니다.", "meta.legacy_fields")
        extra = [k for k in legacy if k != "target_price_tier"]
        if extra:
            _fail("계약에 없는 키입니다.", f"meta.legacy_fields.{extra[0]}", "unknown_field")
        if "target_price_tier" in legacy and legacy["target_price_tier"] not in LEGACY_PRICE_TIERS:
            _fail("이전 목표 가격대 값은 low / mid / high 만 남깁니다.", "meta.legacy_fields.target_price_tier", "invalid_value")


def check_v1(payload: dict, removed: list[str]) -> None:
    """payloads.SCHEMAS[("requisition", 1)] 의 검사. 실패하면 PayloadError(400)."""
    _check_context(payload["context"])
    _check_inputs(payload["inputs"])
    if payload["outputs"]:
        _fail("개발요청서 v1 의 outputs 는 빈 객체입니다 (검토 상태 등은 화면에서 다시 계산).", "outputs."
              + next(iter(payload["outputs"])), "unknown_field")
    _check_meta(payload["meta"])
