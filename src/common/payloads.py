"""탭 저장본 payload·반영 기록 검증 (PM 관리) — DB 에 접속하지 않습니다.

- payload 는 context / inputs / outputs / meta 네 칸(객체)만 허용합니다. 그 밖의 최상위 키는 거부합니다.
- 저장 제외 필드(docs/data_contract.md 5장)는 제거하고, 제거한 경로를 돌려줍니다.
- 참고자료·필드 출처 항목은 **허용 키만** 남깁니다 (meta.reference_files[], meta.field_provenance[]).
- 그 밖의 위치에서 파일 본문으로 보이는 값(data URL, 긴 base64 문자열)이 있으면 몰래 지우지 않고 거부합니다.
- 크기 상한을 넘으면 잘라 저장하지 않고 PayloadTooLarge 로 거부합니다.
- 탭·schema_version 별 검증 구조는 SCHEMAS 에 둡니다. 세부 계약이 아직 없는 탭은 level="structure" 로만 표시합니다
  (네 칸 구조·파일 본문 제외·크기만 확인, 필드 단위 검증 아님). 개발요청서 v1 은 계약 전체 검사(level="full").
"""

from __future__ import annotations

import copy
import json
import os
import re
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath

TABS = ("regulatory", "margin", "simulation", "requisition")
SECTIONS = ("context", "inputs", "outputs", "meta")

# 저장 제외 필드 (data_contract.md 5장)
# 파일 본문·원문 — 어느 깊이에 있어도 제거
EXCLUDED_KEYS = frozenset({
    "data_url", "dataUrl", "raw_extracted_data", "originalFile", "original_file", "file_content", "fileContent",
    "file_base64", "base64", "blob",
})
# 클라이언트 버전·문서 id·작성자·화면 상태 — 각 칸(context/inputs/outputs/meta)과 applied_values 의 최상위에서 제거
TOP_LEVEL_EXCLUDED_KEYS = frozenset({
    "version", "version_no", "document_id", "documentId", "created_by", "createdBy", "author", "ui_state", "uiState",
})
REFERENCE_FILE_KEYS = ("name", "size", "type")
FIELD_PROVENANCE_KEYS = ("field_key", "source_value", "source_page", "input_source", "review_status", "user_value")
MAX_DEPTH = 32

_DATA_URL_RE = re.compile(r"^\s*data:[\w.+-]+/[\w.+-]+(;[\w=.+-]+)*;base64,", re.I)
_BASE64_RE = re.compile(r"^[A-Za-z0-9+/=\r\n]+$")
BASE64_MIN_LEN = 512   # 이 길이 이상이고 공백 없이 base64 문자만이면 파일 본문으로 봄


class PayloadError(ValueError):
    """잘못된 입력 (400). path 는 문제 위치."""

    def __init__(self, message: str, path: str = "", code: str = "invalid_payload"):
        super().__init__(message)
        self.path = path
        self.code = code


class PayloadTooLarge(PayloadError):
    """크기 상한 초과 (413)."""

    def __init__(self, message: str, path: str = "", size: int = 0, limit: int = 0):
        super().__init__(message, path, code="payload_too_large")
        self.size = size
        self.limit = limit


@dataclass(frozen=True)
class Limits:
    """크기 상한 (UTF-8 JSON 바이트). 근거·측정값은 docs/api_contract.md "크기 제한"."""
    payload_bytes: int = 256 * 1024
    applied_values_bytes: int = 32 * 1024
    links_per_save: int = 20

    @classmethod
    def from_env(cls) -> "Limits":
        def num(name, default):
            raw = (os.getenv(name) or "").strip()
            return int(raw) if raw.isdigit() and int(raw) > 0 else default
        d = cls()
        return cls(num("VERSION_PAYLOAD_MAX_BYTES", d.payload_bytes),
                   num("VERSION_APPLIED_VALUES_MAX_BYTES", d.applied_values_bytes),
                   num("VERSION_LINKS_MAX", d.links_per_save))

    @property
    def request_bytes(self) -> int:
        """요청 본문 상한: payload + 반영 기록 + 여유 16 KiB."""
        return self.payload_bytes + self.applied_values_bytes * self.links_per_save + 16 * 1024


def json_size(value) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _looks_like_file_body(text: str) -> bool:
    if _DATA_URL_RE.match(text):
        return True
    compact = text.strip()
    if len(compact) < BASE64_MIN_LEN or " " in compact or not _BASE64_RE.match(compact):
        return False
    # 실제 파일 base64 는 대·소문자·숫자가 섞여 있음 (같은 글자 반복 등 일반 텍스트 오탐 방지)
    return any(c.isupper() for c in compact) and any(c.islower() for c in compact) and any(c.isdigit() for c in compact)


def _clean(value, path: str, removed: list[str], depth: int = 0):
    """제외 키 제거 + 파일 본문 값 거부. 새 객체를 돌려줍니다."""
    if depth > MAX_DEPTH:
        raise PayloadError("payload 가 너무 깊게 중첩되어 있습니다.", path)
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise PayloadError("객체 키는 문자열이어야 합니다.", path)
            sub = f"{path}.{key}" if path else key
            if key in EXCLUDED_KEYS or (depth == 1 and key in TOP_LEVEL_EXCLUDED_KEYS):
                removed.append(sub)
                continue
            out[key] = _clean(item, sub, removed, depth + 1)
        return out
    if isinstance(value, list):
        return [_clean(item, f"{path}[{i}]", removed, depth + 1) for i, item in enumerate(value)]
    if isinstance(value, str):
        if _looks_like_file_body(value):
            raise PayloadError("파일 본문(data URL·base64)은 저장할 수 없습니다. 파일명·크기 등 메타데이터만 보내세요.",
                               path, code="file_content_not_allowed")
        return value
    if value is None or isinstance(value, (bool, int, float)):
        if isinstance(value, float) and value != value:   # NaN
            raise PayloadError("숫자 값이 올바르지 않습니다.", path)
        return value
    raise PayloadError("JSON 값만 저장할 수 있습니다.", path)


def _only_keys(items, allowed: tuple, path: str, removed: list[str]) -> list:
    if not isinstance(items, list):
        raise PayloadError("목록이어야 합니다.", path)
    result = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise PayloadError("항목은 객체여야 합니다.", f"{path}[{i}]")
        removed.extend(f"{path}[{i}].{k}" for k in item if k not in allowed)
        result.append({k: item[k] for k in allowed if k in item})
    return result


def _file_name_only(name, path: str) -> str:
    if not isinstance(name, str):
        raise PayloadError("파일명은 문자열이어야 합니다.", path)
    base = PureWindowsPath(PurePosixPath(name).name).name
    if len(base) > 255:
        raise PayloadError("파일명이 너무 깁니다.", path)
    return base


# --- 탭·schema_version 별 검증 구조 -------------------------------------------

def _check_reference_files(payload: dict, removed: list[str]) -> None:
    meta = payload["meta"]
    if "reference_files" in meta:
        files = _only_keys(meta["reference_files"], REFERENCE_FILE_KEYS, "meta.reference_files", removed)
        for i, f in enumerate(files):
            p = f"meta.reference_files[{i}]"
            if "name" in f:
                f["name"] = _file_name_only(f["name"], p + ".name")
            if "size" in f and (not isinstance(f["size"], int) or isinstance(f["size"], bool) or f["size"] < 0):
                raise PayloadError("size 는 0 이상의 정수여야 합니다.", p + ".size")
            if "type" in f and not isinstance(f["type"], str):
                raise PayloadError("type 은 문자열이어야 합니다.", p + ".type")
        meta["reference_files"] = files
    if "field_provenance" in meta:
        meta["field_provenance"] = _only_keys(meta["field_provenance"], FIELD_PROVENANCE_KEYS,
                                              "meta.field_provenance", removed)
    if "source_file_name" in payload["context"]:
        payload["context"]["source_file_name"] = _file_name_only(payload["context"]["source_file_name"],
                                                                 "context.source_file_name")


def _check_requisition_v1(payload: dict, removed: list[str]) -> None:
    """개발요청서 저장 계약 v1 전체 검사 — src/05_requisition/contract.py (docs/data_contract.md 4장)."""
    import importlib
    importlib.import_module("src.05_requisition.contract").check_v1(payload, removed)


@dataclass(frozen=True)
class Schema:
    tab: str
    version: int
    level: str          # "structure" = 네 칸 구조·파일 제외·크기만 / "partial" = 일부 확정 필드 추가 검사 / "full" = 계약 전체
    note: str
    checks: tuple = ()
    project_bound: bool = False   # context.customer_id / project_id 가 저장 대상 프로젝트와 같아야 함 (versions.py 가 DB 로 확인)


SCHEMAS: dict[tuple[str, int], Schema] = {
    ("regulatory", 1): Schema("regulatory", 1, "structure", "규제 탭 저장본 구조는 4단계 합의 전 (data_contract.md 2-3)",
                              (_check_reference_files,)),
    ("margin", 1): Schema("margin", 1, "structure", "마진 탭 세부 필드 미정 — 탭 담당자 합의 전",
                          (_check_reference_files,)),
    ("simulation", 1): Schema("simulation", 1, "structure", "모델링 탭 세부 필드 미정 — 탭 담당자 합의 전",
                              (_check_reference_files,)),
    ("requisition", 1): Schema("requisition", 1, "full",
                               "개발요청서 저장 계약 v1 전체 검사 (data_contract.md 4장)",
                               (_check_reference_files, _check_requisition_v1), project_bound=True),
}


@dataclass
class CleanResult:
    payload: dict
    removed: list[str]
    size: int
    schema: Schema

    def validation(self) -> dict:
        return {"schema": f"{self.schema.tab}.v{self.schema.version}", "level": self.schema.level,
                "fully_validated": self.schema.level == "full", "note": self.schema.note,
                "removed_fields": self.removed, "payload_bytes": self.size}


def validate_tab(tab) -> str:
    if tab not in TABS:
        raise PayloadError(f"알 수 없는 탭입니다. ({', '.join(TABS)})", "tab", code="invalid_tab")
    return tab


def clean_payload(tab: str, schema_version, payload, limits: Limits) -> CleanResult:
    validate_tab(tab)
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise PayloadError("schema_version 은 정수여야 합니다.", "schema_version")
    schema = SCHEMAS.get((tab, schema_version))
    if schema is None:
        raise PayloadError(f"{tab} 탭은 schema_version {schema_version} 을 지원하지 않습니다.", "schema_version",
                           code="unsupported_schema_version")
    if not isinstance(payload, dict):
        raise PayloadError("payload 는 객체여야 합니다.", "payload")
    extra = sorted(set(payload) - set(SECTIONS))
    if extra:
        raise PayloadError(f"payload 최상위에는 {', '.join(SECTIONS)} 만 둘 수 있습니다: {', '.join(extra)}", "payload")
    for section in SECTIONS:
        if not isinstance(payload.get(section), dict):
            raise PayloadError(f"payload.{section} 는 객체여야 합니다.", section)
    removed: list[str] = []
    cleaned = _clean(copy.deepcopy(payload), "", removed)
    for check in schema.checks:
        check(cleaned, removed)
    size = json_size(cleaned)
    if size > limits.payload_bytes:
        raise PayloadTooLarge(f"payload 가 너무 큽니다 ({size} > {limits.payload_bytes} 바이트). 잘라서 저장하지 않습니다.",
                              "payload", size, limits.payload_bytes)
    return CleanResult(cleaned, removed, size, schema)


def clean_applied_values(values, path: str, limits: Limits) -> tuple[dict, list[str]]:
    """반영 기록(applied_values): 객체, 저장 제외 필드 제거, 파일 본문 거부, 크기 상한."""
    if not isinstance(values, dict) or not values:
        raise PayloadError("applied_values 는 비어 있지 않은 객체여야 합니다.", path)
    removed: list[str] = []
    cleaned = _clean(copy.deepcopy(values), path, removed, depth=1)   # depth=1: 최상위 키도 제외 대상
    size = json_size(cleaned)
    if size > limits.applied_values_bytes:
        raise PayloadTooLarge(f"반영 기록이 너무 큽니다 ({size} > {limits.applied_values_bytes} 바이트).",
                              path, size, limits.applied_values_bytes)
    return cleaned, removed


def clean_title(title) -> str | None:
    if title is None:
        return None
    if not isinstance(title, str):
        raise PayloadError("title 은 문자열이어야 합니다.", "title")
    title = title.strip()
    if not title:
        return None
    if len(title) > 200:
        raise PayloadError("title 은 200자 이하여야 합니다.", "title")
    return title
