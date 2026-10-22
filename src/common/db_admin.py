"""업무 DB 관리 명령 (PM 관리) — 서버 실행과 분리된 명령. 저장소 루트에서 실행합니다.

    python -m src.common.db_admin test-marker check            # 테스트 DB 식별 확인 (읽기만)
    python -m src.common.db_admin test-marker init             # 테스트 DB 표식 최초 설정 (TEST_DATABASE_URL 대상만)
    python -m src.common.db_admin status  --target test|dev    # 적용·대기 마이그레이션과 테이블 상태
    python -m src.common.db_admin migrate --target test|dev [--dry-run]
    python -m src.common.db_admin rollback-last --target test  # 테스트 DB 전용 되돌리기 확인
    python -m src.common.db_admin create-first-user --target test|dev --email <이메일> --name <이름> [--team <팀>]
    python -m src.common.db_admin set-password --target test|dev --email <이메일>   # 기존 계정 비밀번호 변경
    python -m src.common.db_admin create-user --target test|dev --email <이메일> --name <이름> [--team <팀>] --by <생성 담당자 이메일>
    python -m src.common.db_admin app-role init-group   --target test|dev                # 공통 권한 역할 cosmoa_app (NOLOGIN)
    python -m src.common.db_admin app-role create-login --target test|dev --role <역할>  # 앱 접속용 로그인 역할 (비밀번호 숨김 입력)
    python -m src.common.db_admin app-role check        --target test|dev [--role <역할>]  # 역할·권한 확인 (읽기만)
    python -m src.common.db_admin app-role whoami       --target dev|test               # 앱 주소의 실제 접속 역할 (읽기만)

대상 주소 — 다른 변수로 자동 대체하지 않습니다.
    test → TEST_DATABASE_URL (TEST_DATABASE_ENDPOINT_ID 와 DB 내부 표식을 모두 확인해야 진행)
    dev  → DATABASE_URL_DIRECT (DEV_DATABASE_ENDPOINT_ID·DATABASE_URL 과 일치해야 하고, 테스트 endpoint·표식이면 거부)
운영 환경(COSMOA_ENV=production 또는 Render)에서는 모든 명령을 거부합니다. 운영 DB 적용은 PM 이 별도로 합니다 (docs/development.md 5-3).
접속 주소·비밀번호·endpoint id 는 출력하지 않습니다.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.db import (  # noqa: E402
    DatabaseConfigError, DatabaseConnectionError, connect, env_url, is_pooled_url, mask_secrets, neon_endpoint_id,
)

MIGRATIONS_DIR = ROOT / "db" / "migrations"
TARGETS = {"test": "TEST_DATABASE_URL", "dev": "DATABASE_URL_DIRECT"}
TEST_ENDPOINT_VAR = "TEST_DATABASE_ENDPOINT_ID"
DEV_ENDPOINT_VAR = "DEV_DATABASE_ENDPOINT_ID"
MARKER_PREFIX = "cosmoa-test-db v1"
YOYO_TABLES = {"_yoyo_migration", "_yoyo_log", "_yoyo_version", "yoyo_lock"}
_MARKER_RE = re.compile(r"^cosmoa-test-db v1 endpoint=(ep-[a-z0-9-]+) branch=([A-Za-z0-9_-]+)$")


class GuardError(RuntimeError):
    """대상 DB 를 확인할 수 없어 작업을 거부함."""


# --- 테스트 DB 식별 ---------------------------------------------------------

def marker_text(endpoint: str, branch: str) -> str:
    return f"{MARKER_PREFIX} endpoint={endpoint} branch={branch}"


def parse_marker(comment: str | None) -> dict | None:
    m = _MARKER_RE.match((comment or "").strip())
    return {"endpoint": m.group(1), "branch": m.group(2)} if m else None


def server_identity(conn) -> dict:
    """DB 가 돌려주는 식별 정보: Neon endpoint·branch id, DB 설명(표식)."""
    return conn.execute(
        """SELECT current_database() AS db,
                  current_setting('neon.endpoint_id', true) AS endpoint,
                  current_setting('neon.branch_id', true) AS branch,
                  shobj_description(d.oid, 'pg_database') AS comment
           FROM pg_database d WHERE d.datname = current_database()"""
    ).fetchone()


def check_test_config() -> tuple[str, str]:
    """접속 전 확인: TEST_DATABASE_URL 이 허용 endpoint 의 직접 연결이고 dev 주소와 다른 endpoint 인지."""
    refuse_production_env()
    url = env_url("TEST_DATABASE_URL")
    allowed = (os.getenv(TEST_ENDPOINT_VAR) or "").strip()
    if not allowed:
        raise GuardError(f"{TEST_ENDPOINT_VAR} 가 설정되지 않아 테스트 DB 를 확인할 수 없습니다.")
    endpoint = neon_endpoint_id(url)
    if endpoint is None:
        raise GuardError("TEST_DATABASE_URL 이 Neon endpoint 주소가 아닙니다.")
    if endpoint != allowed:
        raise GuardError(f"TEST_DATABASE_URL 의 endpoint 가 {TEST_ENDPOINT_VAR} 와 다릅니다.")
    if is_pooled_url(url):
        raise GuardError("TEST_DATABASE_URL 은 직접 연결(-pooler 없는) 주소여야 합니다.")
    for var in ("DATABASE_URL", "DATABASE_URL_DIRECT"):
        other = (os.getenv(var) or "").strip()
        if other and neon_endpoint_id(other) == endpoint:
            raise GuardError(f"TEST_DATABASE_URL 이 {var} 와 같은 endpoint 를 가리킵니다.")
    if endpoint == (os.getenv(DEV_ENDPOINT_VAR) or "").strip():
        raise GuardError(f"TEST_DATABASE_URL 이 {DEV_ENDPOINT_VAR} 와 같은 endpoint 를 가리킵니다.")
    return url, allowed


def verify_test_identity(ident: dict, allowed: str) -> None:
    """접속 후 확인: DB 가 보고한 endpoint 가 허용 값이고, 표식이 현재 endpoint·branch 와 일치하는지.
    표식만 다른 브랜치로 복제되면 branch/endpoint 가 달라 실패합니다."""
    if not ident.get("endpoint") or not ident.get("branch"):
        raise GuardError("DB 에서 Neon endpoint·branch 식별 정보를 읽지 못했습니다.")
    if ident["endpoint"] != allowed:
        raise GuardError(f"DB 가 보고한 endpoint 가 {TEST_ENDPOINT_VAR} 와 다릅니다.")
    marker = parse_marker(ident.get("comment"))
    if marker is None:
        raise GuardError("테스트 DB 표식이 없습니다. 'test-marker init' 으로 먼저 설정하세요. (자동 생성하지 않음)")
    if marker["endpoint"] != ident["endpoint"] or marker["branch"] != ident["branch"]:
        raise GuardError("테스트 DB 표식이 현재 endpoint·branch 와 일치하지 않습니다 (복제된 표식).")


def open_verified_test_db(**kwargs):
    """식별 확인을 모두 통과한 TEST_DATABASE_URL 연결. 실패하면 GuardError."""
    url, allowed = check_test_config()
    conn = connect(url, **kwargs)
    try:
        verify_test_identity(server_identity(conn), allowed)
        conn.rollback()
    except BaseException:
        conn.close()
        raise
    return conn, url


def check_dev_config() -> tuple[str, str]:
    """접속 전 확인: DATABASE_URL_DIRECT·DATABASE_URL 이 고정한 dev endpoint 의 같은 DB 이고 테스트 endpoint 가 아닌지."""
    url = env_url("DATABASE_URL_DIRECT")
    pooled = env_url("DATABASE_URL")
    allowed = (os.getenv(DEV_ENDPOINT_VAR) or "").strip()
    if not allowed:
        raise GuardError(f"{DEV_ENDPOINT_VAR} 가 설정되지 않아 개발 DB 를 확인할 수 없습니다.")
    endpoint = neon_endpoint_id(url)
    if endpoint is None:
        raise GuardError("DATABASE_URL_DIRECT 가 Neon endpoint 주소가 아닙니다.")
    if endpoint != allowed:
        raise GuardError(f"DATABASE_URL_DIRECT 의 endpoint 가 {DEV_ENDPOINT_VAR} 와 다릅니다.")
    if is_pooled_url(url):
        raise GuardError("DATABASE_URL_DIRECT 는 직접 연결(-pooler 없는) 주소여야 합니다.")
    if neon_endpoint_id(pooled) != endpoint or urlsplit(pooled).path != urlsplit(url).path:
        raise GuardError("DATABASE_URL 과 DATABASE_URL_DIRECT 가 같은 endpoint·DB 를 가리키지 않습니다.")
    if endpoint == (os.getenv(TEST_ENDPOINT_VAR) or "").strip():
        raise GuardError("DATABASE_URL_DIRECT 가 테스트 endpoint 를 가리킵니다.")
    return url, allowed


def open_verified_dev_db(**kwargs):
    """DATABASE_URL_DIRECT 연결. 고정 dev endpoint 가 아니거나, 테스트 endpoint·테스트 표식이면 거부."""
    url, allowed = check_dev_config()
    conn = connect(url, **kwargs)
    try:
        ident = server_identity(conn)
        if ident["endpoint"] != allowed:
            raise GuardError(f"DB 가 보고한 endpoint 가 {DEV_ENDPOINT_VAR} 와 다릅니다.")
        if parse_marker(ident["comment"]) is not None:
            raise GuardError("DATABASE_URL_DIRECT 대상 DB 에 테스트 표식이 있습니다.")
        conn.rollback()
    except BaseException:
        conn.close()
        raise
    return conn, url


def is_production_env() -> bool:
    """운영 모드 판단 (app.py 와 같은 기준: COSMOA_ENV=production 또는 Render)."""
    return (os.getenv("COSMOA_ENV") or "").strip().lower() == "production" or bool((os.getenv("RENDER") or "").strip())


def refuse_production_env() -> None:
    if is_production_env():
        raise GuardError("운영 환경(COSMOA_ENV=production 또는 Render)에서는 개발·테스트용 관리 명령을 실행하지 않습니다.")


def open_target(target: str, **kwargs):
    refuse_production_env()
    if target == "test":
        return open_verified_test_db(**kwargs)
    if target == "dev":
        return open_verified_dev_db(**kwargs)
    raise GuardError(f"알 수 없는 대상: {target}")


def init_test_marker() -> str:
    """TEST_DATABASE_URL 대상에만 표식을 처음 설정합니다. 다른 설명이 이미 있으면 덮어쓰지 않습니다."""
    url, allowed = check_test_config()
    with connect(url, autocommit=True) as conn:
        ident = server_identity(conn)
        if not ident.get("endpoint") or not ident.get("branch"):
            raise GuardError("DB 에서 Neon endpoint·branch 식별 정보를 읽지 못했습니다.")
        if ident["endpoint"] != allowed:
            raise GuardError(f"DB 가 보고한 endpoint 가 {TEST_ENDPOINT_VAR} 와 다릅니다.")
        expected = marker_text(ident["endpoint"], ident["branch"])
        if ident["comment"] == expected:
            return "테스트 DB 표식이 이미 설정되어 있습니다. (변경 없음)"
        if ident["comment"]:
            raise GuardError("DB 에 다른 설명(또는 다른 브랜치의 표식)이 이미 있어 덮어쓰지 않았습니다. PM 이 확인하세요.")
        conn.execute(sql.SQL("COMMENT ON DATABASE {} IS {}").format(
            sql.Identifier(ident["db"]), sql.Literal(expected)))
        verify_test_identity(server_identity(conn), allowed)
    return "테스트 DB 표식을 설정하고 확인했습니다."


# --- 마이그레이션 ------------------------------------------------------------

def yoyo_url(url: str) -> str:
    """yoyo 의 psycopg 3 백엔드 주소 (postgresql+psycopg://). .env 원본은 바꾸지 않습니다."""
    return urlsplit(url)._replace(scheme="postgresql+psycopg").geturl()


def migration_files() -> dict[str, set[str]]:
    """{마이그레이션 id: 그 파일이 만드는 테이블}. 되돌리기 파일은 제외."""
    result = {}
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name.endswith(".rollback.sql"):
            continue
        text = path.read_text(encoding="utf-8")
        result[path.stem] = {t.lower() for t in re.findall(r"^\s*CREATE TABLE\s+(\w+)", text, re.I | re.M)}
    return result


def inspect_state(conn) -> dict:
    """DB 의 public 테이블·적용 기록을 저장소 마이그레이션과 비교합니다. 읽기만 합니다."""
    files = migration_files()
    tables = {r["relname"] for r in conn.execute(
        """SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'f')""")}
    applied = []
    if "_yoyo_migration" in tables:
        applied = [r["migration_id"] for r in conn.execute(
            "SELECT migration_id FROM _yoyo_migration ORDER BY applied_at_utc")]
    conn.rollback()
    known = set().union(*files.values()) if files else set()
    problems = []
    unknown = sorted(tables - known - YOYO_TABLES)
    if unknown:
        problems.append(f"마이그레이션에 없는 테이블: {', '.join(unknown)}")
    for mid, created in files.items():
        if mid not in applied and created & tables:
            problems.append(f"{mid} 미적용인데 테이블이 이미 있음: {', '.join(sorted(created & tables))}")
        if mid in applied and created - tables:
            problems.append(f"{mid} 적용 기록이 있는데 테이블이 없음: {', '.join(sorted(created - tables))}")
    foreign = [mid for mid in applied if mid not in files]
    if foreign:
        problems.append(f"저장소에 없는 마이그레이션 적용 기록: {', '.join(foreign)}")
    return {"applied": applied, "pending": [m for m in files if m not in applied],
            "tables": sorted(tables), "problems": problems}


def _yoyo(url: str):
    import functools
    import yoyo.migrations
    from yoyo import get_backend, read_migrations

    # yoyo 9.0.0 Migration.load() 는 encoding 없이 open() 해서 Windows(cp949)에서 한글 주석이 깨집니다.
    # yoyo.migrations 모듈 안의 open 만 UTF-8 기본으로 바꿉니다. (encoding 을 넘기는 호출은 그대로)
    yoyo.migrations.open = functools.partial(open, encoding="utf-8")
    try:
        return get_backend(yoyo_url(url)), read_migrations(str(MIGRATIONS_DIR))
    except Exception as e:
        raise DatabaseConnectionError(mask_secrets(f"yoyo 연결 실패: {e}", url, yoyo_url(url))) from None


def migrate(target: str, dry_run: bool = False) -> dict:
    conn, url = open_target(target)
    with conn:
        before = inspect_state(conn)
    if before["problems"]:
        raise GuardError("예상과 다른 DB 상태라 마이그레이션하지 않았습니다 (삭제·덮어쓰기 없음):\n  - "
                         + "\n  - ".join(before["problems"]))
    if dry_run or not before["pending"]:
        return {"before": before, "applied_now": []}
    backend, migrations = _yoyo(url)
    try:
        with backend.lock():
            todo = backend.to_apply(migrations)
            backend.apply_migrations(todo)
            applied_now = [m.id for m in todo]
    except Exception as e:
        raise RuntimeError(mask_secrets(f"마이그레이션 실패 (해당 파일은 롤백됨): {e}", url, yoyo_url(url))) from None
    finally:
        backend.connection.close()
    conn, _ = open_target(target)
    with conn:
        after = inspect_state(conn)
    return {"before": before, "applied_now": applied_now, "after": after}


def rollback_last(target: str) -> list[str]:
    if target != "test":
        raise GuardError("되돌리기는 테스트 DB(--target test)에서만 실행합니다.")
    conn, url = open_target(target)
    with conn:
        state = inspect_state(conn)
    if state["problems"]:
        raise GuardError("예상과 다른 DB 상태라 되돌리지 않았습니다:\n  - " + "\n  - ".join(state["problems"]))
    backend, migrations = _yoyo(url)
    try:
        with backend.lock():
            todo = backend.to_rollback(migrations)[:1]
            backend.rollback_migrations(todo)
            return [m.id for m in todo]
    except Exception as e:
        raise RuntimeError(mask_secrets(f"되돌리기 실패: {e}", url, yoyo_url(url))) from None
    finally:
        backend.connection.close()


# --- 최초 계정 ------------------------------------------------------------

def check_first_user_possible(target: str) -> None:
    """비밀번호를 묻기 전에 대상 확인·users 테이블·기존 계정 여부를 먼저 봅니다."""
    conn, _ = open_target(target)
    with conn:
        if "users" not in inspect_state(conn)["tables"]:
            raise GuardError("users 테이블이 없습니다. 먼저 migrate 를 실행하세요.")
        if conn.execute("SELECT count(*) AS n FROM users").fetchone()["n"]:
            raise GuardError("이미 계정이 있어 최초 계정을 만들지 않습니다.")


def create_first_user(target: str, email: str, name: str, team: str, password: str) -> int:
    """계정이 하나도 없을 때만 최초 계정을 만듭니다 (시스템 작업, created_by NULL)."""
    from werkzeug.security import generate_password_hash   # 기존 SQLite 로그인과 같은 해시 방식

    email, name, team = email.strip().lower(), name.strip(), team.strip()
    if "@" not in email or not name:
        raise ValueError("이메일과 이름을 확인하세요.")
    conn, _ = open_target(target)
    with conn:
        if "users" not in inspect_state(conn)["tables"]:
            raise GuardError("users 테이블이 없습니다. 먼저 migrate 를 실행하세요.")
        with conn.transaction():
            conn.execute("LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE")
            if conn.execute("SELECT count(*) AS n FROM users").fetchone()["n"]:
                raise GuardError("이미 계정이 있어 최초 계정을 만들지 않았습니다.")
            row = conn.execute(
                """INSERT INTO users (email, name, team, password_hash, created_by)
                   VALUES (%s, %s, %s, %s, NULL) RETURNING id""",
                (email, name, team, generate_password_hash(password)),
            ).fetchone()
    return row["id"]


def check_user_exists(target: str, email: str) -> None:
    """비밀번호를 묻기 전에 대상 확인·계정 존재 여부를 먼저 봅니다."""
    conn, _ = open_target(target)
    with conn:
        if "users" not in inspect_state(conn)["tables"]:
            raise GuardError("users 테이블이 없습니다. 먼저 migrate 를 실행하세요.")
        if conn.execute("SELECT 1 FROM users WHERE email = %s", (email.strip().lower(),)).fetchone() is None:
            raise GuardError("해당 이메일의 계정이 없습니다.")


def set_password(target: str, email: str, password: str) -> None:
    """이미 있는 계정의 비밀번호를 바꿉니다 (werkzeug 해시)."""
    from werkzeug.security import generate_password_hash

    conn, _ = open_target(target)
    with conn:
        with conn.transaction():
            cur = conn.execute("UPDATE users SET password_hash = %s WHERE email = %s",
                               (generate_password_hash(password), email.strip().lower()))
            if cur.rowcount != 1:
                raise GuardError("해당 이메일의 계정이 없습니다.")


# --- 팀원 계정 추가 -------------------------------------------------------
# 최초 계정(created_by NULL)과 달리, 이미 있는 계정 생성 담당자가 만들고 그 담당자를 created_by 에 기록합니다.
# 담당자는 --by 이메일 + 본인 비밀번호(숨김 입력)로 확인합니다. 비밀번호·해시·접속 주소는 출력하지 않습니다.

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PASSWORD_MIN = 8


def normalize_account(email: str, name: str, team: str = "") -> tuple[str, str, str]:
    """이메일 소문자·앞뒤 공백 제거 (DB CHECK 와 같은 기준), 이름 필수."""
    email, name, team = (email or "").strip().lower(), (name or "").strip(), (team or "").strip()
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise ValueError("이메일 형식을 확인하세요.")
    if not name or len(name) > 100:
        raise ValueError("이름을 1~100자로 입력하세요.")
    if len(team) > 100:
        raise ValueError("팀은 100자 이하로 입력하세요.")
    return email, name, team


def check_create_user_possible(target: str, email: str, name: str, team: str, created_by_email: str) -> None:
    """비밀번호를 묻기 전에 대상 확인·입력 형식·중복·생성 담당자 존재를 먼저 봅니다."""
    email, _, _ = normalize_account(email, name, team)
    conn, _ = open_target(target)
    with conn:
        if "users" not in inspect_state(conn)["tables"]:
            raise GuardError("users 테이블이 없습니다. 먼저 migrate 를 실행하세요.")
        if conn.execute("SELECT 1 FROM users WHERE email = %s", (email,)).fetchone():
            raise GuardError("이미 같은 이메일의 계정이 있습니다.")
        if conn.execute("SELECT 1 FROM users WHERE email = %s",
                        ((created_by_email or "").strip().lower(),)).fetchone() is None:
            raise GuardError("계정 생성 담당자(--by) 계정이 없습니다.")


def create_user(target: str, *, email: str, name: str, team: str, password: str,
                created_by_email: str, created_by_password: str) -> int:
    """팀원 계정 추가. 생성 담당자(이미 있는 계정)의 비밀번호를 확인하고 created_by 에 그 계정 id 를 기록합니다."""
    from psycopg import errors
    from werkzeug.security import check_password_hash, generate_password_hash   # 로그인과 같은 해시 방식

    email, name, team = normalize_account(email, name, team)
    if len(password or "") < PASSWORD_MIN:
        raise ValueError(f"비밀번호는 {PASSWORD_MIN}자 이상이어야 합니다.")
    conn, _ = open_target(target)
    with conn:
        with conn.transaction():
            creator = conn.execute("SELECT id, password_hash FROM users WHERE email = %s",
                                   ((created_by_email or "").strip().lower(),)).fetchone()
            if creator is None or not check_password_hash(creator["password_hash"], created_by_password or ""):
                raise GuardError("계정 생성 담당자 확인에 실패했습니다 (이메일 또는 비밀번호).")
            try:
                row = conn.execute(
                    """INSERT INTO users (email, name, team, password_hash, created_by)
                       VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                    (email, name, team, generate_password_hash(password), creator["id"]),
                ).fetchone()
            except errors.UniqueViolation:
                raise GuardError("이미 같은 이메일의 계정이 있습니다.") from None
    return row["id"]


def _ask_password(min_length: int = PASSWORD_MIN) -> str | None:
    password = getpass.getpass("비밀번호 (화면에 표시되지 않음): ")
    if len(password) < min_length or password != getpass.getpass("비밀번호 확인: "):
        return None
    return password


# --- 앱용 PostgreSQL 접속 역할 (docs/db_rules.md 8장) ---------------------------
# PostgreSQL 로그인 역할 = 앱(Flask)이 DB 에 접속할 때 쓰는 DB 계정 (DATABASE_URL 의 사용자).
# 대시보드 로그인 계정(users 테이블 행, create-user)과 별개입니다.
# 책임: 공통 권한 역할 생성(init-group) → 업무 표 권한(마이그레이션 0004) → 로그인 역할 생성·비밀번호(create-login).
# Neon 역할은 브랜치마다 따로 있으므로 대상(test·dev)마다 실행합니다.
# 같은 이름의 역할이 이미 있으면 db_admin 표식·속성·멤버십이 맞을 때만 "변경 없음"으로 통과하고,
# 다르면 고치거나 인수하지 않고 거부합니다. 이미 있는 역할의 비밀번호는 바꾸지 않습니다.

APP_GROUP = "cosmoa_app"
APP_GROUP_MARK = "cosmoa-app-group v1"
APP_LOGIN_MARK = "cosmoa-app-login v1"
APP_LOGIN_RE = re.compile(r"^cosmoa_app_[a-z][a-z0-9_]{0,39}$")
APP_GRANTS_MIGRATION = "0004_app_role_grants"
APP_PASSWORD_MIN = 16
TEST_APP_URL_VAR = "TEST_APP_DATABASE_URL"
MIN_SERVER_VERSION = 160000   # GRANT ... WITH INHERIT TRUE, SET FALSE (PostgreSQL 16+)

# 0004_app_role_grants.sql 과 같은 내용. app-role check 가 실제 권한과 비교합니다 (적거나 많으면 문제).
APP_TABLE_PRIVILEGES = {
    "users": {"SELECT"}, "customer_contacts": {"SELECT"}, "project_history": {"SELECT"},
    "customers": {"SELECT", "INSERT"}, "projects": {"SELECT", "INSERT"},
    "tab_versions": {"SELECT", "INSERT"}, "final_history": {"SELECT", "INSERT"}, "version_links": {"SELECT", "INSERT"},
}
APP_UPDATE_COLUMNS = {"users": {"password_hash"}, "customers": {"updated_at"}, "projects": {"updated_at"}}
_ROLE_ADMIN_ATTRS = ("rolsuper", "rolcreaterole", "rolcreatedb", "rolreplication", "rolbypassrls")


def validate_app_login_name(name: str) -> str:
    name = (name or "").strip()
    if not APP_LOGIN_RE.match(name):
        raise ValueError("로그인 역할 이름은 cosmoa_app_<영문 소문자·숫자·_> 형식이어야 합니다 (예: cosmoa_app_test).")
    return name


def _server_version(conn) -> int:
    version = int(conn.execute("SHOW server_version_num").fetchone()["server_version_num"])
    if version < MIN_SERVER_VERSION:
        raise GuardError("PostgreSQL 16 이상에서만 앱 역할 명령을 실행합니다 (멤버십 SET 옵션).")
    return version


def _role(conn, name: str) -> dict | None:
    return conn.execute(
        """SELECT oid, rolname, rolsuper, rolinherit, rolcreaterole, rolcreatedb, rolcanlogin, rolreplication,
                  rolbypassrls, shobj_description(oid, 'pg_authid') AS comment
           FROM pg_roles WHERE rolname = %s""", (name,)).fetchone()


def _role_problems(conn, role: dict, *, login: bool) -> list[str]:
    """db_admin 이 만든 그대로인지: 표식, 관리 속성 없음, 소유 객체 없음, 멤버십(로그인 역할은 cosmoa_app 하나만)."""
    name, problems = role["rolname"], []
    if (role["comment"] or "") != (APP_LOGIN_MARK if login else APP_GROUP_MARK):
        problems.append(f"{name}: db_admin 표식이 없습니다 (알 수 없는 기존 역할 — 인수하지 않음)")
    problems += [f"{name}: {attr} 속성이 켜져 있습니다" for attr in _ROLE_ADMIN_ATTRS if role[attr]]
    if role["rolcanlogin"] is not login:
        problems.append(f"{name}: LOGIN 속성이 {'없습니다' if login else '있습니다'}")
    if role["rolinherit"] is not login:
        problems.append(f"{name}: INHERIT 속성이 예상({'INHERIT' if login else 'NOINHERIT'})과 다릅니다")
    owned = conn.execute("""SELECT count(*) AS n FROM pg_shdepend
                            WHERE refclassid = 'pg_authid'::regclass AND refobjid = %s AND deptype = 'o'""",
                         (role["oid"],)).fetchone()["n"]
    if owned:
        problems.append(f"{name}: 소유한 객체가 {owned}개 있습니다")
    member_of = conn.execute(
        """SELECT r.rolname, a.admin_option, a.inherit_option, a.set_option
           FROM pg_auth_members a JOIN pg_roles r ON r.oid = a.roleid WHERE a.member = %s ORDER BY 1""",
        (role["oid"],)).fetchall()
    expected = [{"rolname": APP_GROUP, "admin_option": False, "inherit_option": True, "set_option": False}] if login else []
    if member_of != expected:
        problems.append(f"{name}: 역할 멤버십이 예상과 다릅니다: {[m['rolname'] for m in member_of] or '(없음)'}")
    return problems


def _app_group_problems(conn) -> list[str]:
    role = _role(conn, APP_GROUP)
    if role is None:
        return [f"{APP_GROUP} 역할이 없습니다. 먼저 'app-role init-group' 을 실행하세요."]
    return _role_problems(conn, role, login=False)


def _require_app_grants_ready(conn) -> None:
    """로그인 역할을 만들기 전에: 공통 권한 역할이 맞고 0004 권한 마이그레이션이 적용되었는지."""
    problems = _app_group_problems(conn)
    if APP_GRANTS_MIGRATION not in inspect_state(conn)["applied"]:
        problems.append(f"{APP_GRANTS_MIGRATION} 미적용. 'migrate' 를 먼저 실행하세요.")
    if problems:
        raise GuardError("앱 로그인 역할을 만들 준비가 되지 않았습니다:\n  - " + "\n  - ".join(problems))


def init_app_group(target: str) -> str:
    """공통 권한 역할(NOLOGIN)을 만듭니다. 이미 있으면 db_admin 이 만든 그대로인지만 확인합니다 (변경 없음)."""
    conn, _ = open_target(target)
    with conn:
        _server_version(conn)
        with conn.transaction():
            created = _role(conn, APP_GROUP) is None
            if created:
                ident = sql.Identifier(APP_GROUP)
                conn.execute(sql.SQL("CREATE ROLE {} NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE "
                                     "NOREPLICATION NOBYPASSRLS").format(ident))
                conn.execute(sql.SQL("COMMENT ON ROLE {} IS {}").format(ident, sql.Literal(APP_GROUP_MARK)))
            problems = _app_group_problems(conn)
            if problems:   # 방금 만든 경우에도 확인 실패면 트랜잭션 롤백
                raise GuardError(f"{APP_GROUP} 역할이 예상과 달라 진행하지 않았습니다:\n  - " + "\n  - ".join(problems))
    return f"{APP_GROUP} 역할을 만들었습니다." if created else f"{APP_GROUP} 역할이 이미 있습니다 (확인 통과, 변경 없음)."


def check_create_app_login_possible(target: str, name: str) -> bool:
    """비밀번호를 묻기 전에 확인합니다. 이미 있으면 True (검사 통과 → 변경 없음), 없으면 False, 다르면 거부."""
    name = validate_app_login_name(name)
    conn, _ = open_target(target)
    with conn:
        _server_version(conn)
        _require_app_grants_ready(conn)
        role = _role(conn, name)
        if role is None:
            return False
        problems = _role_problems(conn, role, login=True)
        if problems:
            raise GuardError("같은 이름의 역할이 이미 있지만 예상과 달라 바꾸지 않았습니다:\n  - " + "\n  - ".join(problems))
        return True


def create_app_login(target: str, name: str, password: str) -> bool:
    """앱 접속용 로그인 역할을 만들고 cosmoa_app 권한을 상속(SET 불가)하게 합니다. 만들었으면 True.
    이미 같은 역할이 맞게 있으면 False (비밀번호를 바꾸지 않음). 비밀번호는 출력·예외 메시지에 넣지 않습니다."""
    name = validate_app_login_name(name)
    if len(password or "") < APP_PASSWORD_MIN:
        raise ValueError(f"로그인 역할 비밀번호는 {APP_PASSWORD_MIN}자 이상이어야 합니다.")
    conn, url = open_target(target)
    with conn:
        _server_version(conn)
        _require_app_grants_ready(conn)
        try:
            with conn.transaction():
                role = _role(conn, name)
                if role is None:
                    ident = sql.Identifier(name)
                    # Neon 은 비밀번호 강도(엔트로피) 확인을 위해 평문을 받습니다 (해시 미지원). TLS 연결로 한 번만 보냅니다.
                    conn.execute(sql.SQL("CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION "
                                         "NOBYPASSRLS PASSWORD {}").format(ident, sql.Literal(password)))
                    conn.execute(sql.SQL("COMMENT ON ROLE {} IS {}").format(ident, sql.Literal(APP_LOGIN_MARK)))
                    conn.execute(sql.SQL("GRANT {} TO {} WITH INHERIT TRUE, SET FALSE").format(
                        sql.Identifier(APP_GROUP), ident))
                problems = _role_problems(conn, _role(conn, name), login=True)
                if problems:
                    raise GuardError("로그인 역할이 예상과 달라 바꾸지 않았습니다:\n  - " + "\n  - ".join(problems))
        except psycopg.Error as e:   # 서버 기본 메시지만 (문장 본문·위치 정보 제외), 비밀번호는 원문·따옴표 처리 형태 모두 가림
            message = e.diag.message_primary or type(e).__name__
            for secret in (password, password.replace("'", "''")):
                message = message.replace(secret, "***")
            raise GuardError(f"로그인 역할을 만들지 못했습니다 (변경 없음): {mask_secrets(message, url)}") from None
    return role is None


def app_role_report(target: str, login: str | None = None) -> tuple[list[str], list[str]]:
    """앱 역할 확인 (읽기만). (문제 목록, 참고 목록). 문제가 없어야 적용 완료입니다."""
    if login is not None:
        login = validate_app_login_name(login)
    conn, _ = open_target(target)
    with conn:
        version = _server_version(conn)
        problems = _app_group_problems(conn)
        if APP_GRANTS_MIGRATION not in inspect_state(conn)["applied"]:
            problems.append(f"{APP_GRANTS_MIGRATION} 미적용")
        subjects = [APP_GROUP]
        if login:
            role = _role(conn, login)
            if role is None:
                problems.append(f"{login} 역할이 없습니다")
            else:
                problems += _role_problems(conn, role, login=True)
                subjects.append(login)
        if _role(conn, APP_GROUP) is None:
            return problems, []
        info = []
        table_privs = ["SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"]
        if version >= 170000:
            table_privs.append("MAINTAIN")
        for subject in subjects:
            problems += _privilege_problems(conn, subject, table_privs)
        if login and login in subjects:
            info += _app_login_info(conn, login)
    return problems, info


def _privilege_problems(conn, subject: str, table_privs: list[str]) -> list[str]:
    """실제 유효 권한(직접 GRANT·PUBLIC·상속 포함)을 0004 기준과 비교합니다."""
    problems = []
    rows = conn.execute(
        """SELECT c.relname, c.relkind,
                  array(SELECT p FROM unnest(CASE WHEN c.relkind = 'S' THEN ARRAY['USAGE', 'SELECT', 'UPDATE'] ELSE %s::text[] END) p
                        WHERE CASE WHEN c.relkind = 'S' THEN has_sequence_privilege(%s, c.oid, p)
                                   ELSE has_table_privilege(%s, c.oid, p) END) AS granted
           FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S') ORDER BY c.relname""",
        (table_privs, subject, subject)).fetchall()
    for row in rows:
        expected = set() if row["relkind"] == "S" else APP_TABLE_PRIVILEGES.get(row["relname"], set())
        if set(row["granted"]) != expected:
            problems.append(f"{subject}: {row['relname']} 권한 {sorted(row['granted']) or '(없음)'} "
                            f"≠ 기준 {sorted(expected) or '(없음)'}")
    columns = conn.execute(
        """SELECT c.relname, a.attname, has_column_privilege(%s, c.oid, a.attnum, 'UPDATE') AS upd,
                  has_column_privilege(%s, c.oid, a.attnum, 'REFERENCES') AS ref
           FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace JOIN pg_attribute a ON a.attrelid = c.oid
           WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND a.attnum > 0 AND NOT a.attisdropped""",
        (subject, subject)).fetchall()
    actual_update = {(c["relname"], c["attname"]) for c in columns if c["upd"]}
    expected_update = {(t, col) for t, cols in APP_UPDATE_COLUMNS.items() for col in cols}
    if actual_update != expected_update:
        problems.append(f"{subject}: 수정 가능 열 {sorted(actual_update)} ≠ 기준 {sorted(expected_update)}")
    if any(c["ref"] for c in columns):
        problems.append(f"{subject}: REFERENCES 권한이 있습니다")
    schema_create = conn.execute(
        """SELECT nspname FROM pg_namespace WHERE has_schema_privilege(%s, oid, 'CREATE')""", (subject,)).fetchall()
    if schema_create:
        problems.append(f"{subject}: 스키마 CREATE 권한: {[s['nspname'] for s in schema_create]}")
    if conn.execute("SELECT has_database_privilege(%s, current_database(), 'CREATE') AS ok", (subject,)).fetchone()["ok"]:
        problems.append(f"{subject}: DB CREATE 권한이 있습니다")
    definer = conn.execute(
        """SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
           WHERE n.nspname = 'public' AND p.prosecdef AND has_function_privilege(%s, p.oid, 'EXECUTE')""",
        (subject,)).fetchall()
    if definer:
        problems.append(f"{subject}: 실행 가능한 SECURITY DEFINER 함수: {[d['proname'] for d in definer]}")
    # 다른 역할의 권한을 쓰거나(USAGE) 그 역할로 전환(SET)할 수 있는지. 자기 자신·cosmoa_app 상속만 허용
    reach = conn.execute(
        """SELECT r.rolname, pg_has_role(%s, r.oid, 'USAGE') AS usage, pg_has_role(%s, r.oid, 'SET') AS can_set
           FROM pg_roles r WHERE r.rolname <> %s
             AND (pg_has_role(%s, r.oid, 'USAGE') OR pg_has_role(%s, r.oid, 'SET'))""",
        (subject, subject, subject, subject, subject)).fetchall()
    for r in reach:
        if r["can_set"] or r["rolname"] != APP_GROUP:
            problems.append(f"{subject}: {r['rolname']} 역할 {'전환(SET ROLE)' if r['can_set'] else '권한 상속'} 가능")
    return problems


def _app_login_info(conn, login: str) -> list[str]:
    """문제는 아니지만 알아야 할 PUBLIC 기본 권한 (docs/db_rules.md 8장 한계)."""
    row = conn.execute(
        """SELECT has_database_privilege(%s, current_database(), 'CONNECT') AS can_connect,
                  has_database_privilege(%s, current_database(), 'TEMP') AS can_temp,
                  (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                    WHERE n.nspname = 'public' AND has_function_privilege(%s, p.oid, 'EXECUTE')
                      AND p.prorettype = 'trigger'::regtype) AS trigger_funcs,
                  (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                    WHERE n.nspname = 'public' AND has_function_privilege(%s, p.oid, 'EXECUTE')
                      AND p.prorettype <> 'trigger'::regtype) AS other_funcs""",
        (login, login, login, login)).fetchone()
    return [f"DB 접속(CONNECT): {'가능' if row['can_connect'] else '불가'}",
            f"임시 테이블(TEMP, PUBLIC 기본값): {'가능' if row['can_temp'] else '불가'}",
            f"public 트리거 함수 실행 권한(PUBLIC 기본값, 직접 호출은 불가): {row['trigger_funcs']}개",
            f"public 일반 함수 실행 권한: {row['other_funcs']}개"]


def app_connection_report(target: str) -> tuple[list[str], list[str]]:
    """앱이 실제로 쓰는 주소(dev: DATABASE_URL, test: TEST_APP_DATABASE_URL)로 접속해 접속 역할을 확인합니다 (읽기만).
    관리 주소로 대체하지 않습니다. 팀원처럼 관리용 변수가 없어도 동작합니다. (문제 목록, 결과 목록)"""
    refuse_production_env()
    var = {"dev": "DATABASE_URL", "test": TEST_APP_URL_VAR}.get(target)
    if var is None:
        raise GuardError(f"알 수 없는 대상: {target}")
    url = env_url(var)
    pin = (os.getenv(DEV_ENDPOINT_VAR if target == "dev" else TEST_ENDPOINT_VAR) or "").strip()
    problems, lines = [], [f"확인한 변수: {var} ({'풀링' if is_pooled_url(url) else '직접'} 연결)"]
    if not is_pooled_url(url):
        problems.append(f"{var} 가 풀링(-pooler) 주소가 아닙니다.")
    with connect(url, prepare_threshold=None) as conn:
        ident = server_identity(conn)
        who = conn.execute(
            """SELECT current_user AS cur, session_user AS ses, r.rolsuper OR r.rolcreaterole OR r.rolcreatedb
                      OR r.rolreplication OR r.rolbypassrls AS admin_attr,
                      CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s)
                           THEN pg_has_role(current_user, %s, 'USAGE') ELSE false END AS app_member,
                      (SELECT count(*) FROM pg_tables WHERE schemaname = 'public'
                        AND pg_has_role(current_user, tableowner, 'USAGE')) AS owned_tables
               FROM pg_roles r WHERE r.rolname = current_user""", (APP_GROUP, APP_GROUP)).fetchone()
        conn.rollback()
    lines.append(f"접속 역할: {who['cur']}")
    if pin:
        lines.append(f"endpoint 고정값과 일치: {'예' if ident['endpoint'] == pin else '아니오'}")
        if ident["endpoint"] != pin:
            problems.append(f"DB 가 보고한 endpoint 가 고정값({DEV_ENDPOINT_VAR if target == 'dev' else TEST_ENDPOINT_VAR})과 다릅니다.")
    else:
        lines.append("endpoint 고정값 없음 — 비교 생략")
    marker = parse_marker(ident.get("comment"))
    lines.append(f"테스트 DB 표식: {'있음' if marker else '없음'}")
    if (target == "dev") == bool(marker):
        problems.append("대상과 테스트 표식이 맞지 않습니다 (dev 는 표식 없음, test 는 표식 있음).")
    if not APP_LOGIN_RE.match(who["cur"]) or who["cur"] != who["ses"]:
        problems.append("앱 로그인 역할(cosmoa_app_…)이 아닙니다 — 관리 역할 주소일 수 있습니다.")
    if who["admin_attr"] or who["owned_tables"]:
        problems.append("접속 역할에 관리 속성이나 소유 테이블이 있습니다.")
    if not who["app_member"]:
        problems.append(f"접속 역할이 {APP_GROUP} 권한을 받지 않습니다.")
    return problems, lines


def check_test_app_config() -> tuple[str, str, str]:
    """앱 역할 검증용 주소(TEST_APP_DATABASE_URL): TEST_DATABASE_URL 과 같은 test endpoint·DB 의 풀링 주소이고
    사용자가 앱 로그인 역할(관리 역할 아님)인지. 접속 전 확인. (주소, 역할 이름, 허용 endpoint)"""
    admin_url, allowed = check_test_config()
    url = env_url(TEST_APP_URL_VAR)
    if neon_endpoint_id(url) != allowed:
        raise GuardError(f"{TEST_APP_URL_VAR} 의 endpoint 가 {TEST_ENDPOINT_VAR} 와 다릅니다.")
    if not is_pooled_url(url):
        raise GuardError(f"{TEST_APP_URL_VAR} 는 풀링(-pooler) 주소여야 합니다.")
    if urlsplit(url).path != urlsplit(admin_url).path:
        raise GuardError(f"{TEST_APP_URL_VAR} 와 TEST_DATABASE_URL 의 DB 이름이 다릅니다.")
    user = unquote(urlsplit(url).username or "")
    if not APP_LOGIN_RE.match(user) or user == unquote(urlsplit(admin_url).username or ""):
        raise GuardError(f"{TEST_APP_URL_VAR} 의 사용자는 앱 로그인 역할(cosmoa_app_...)이어야 합니다.")
    return url, user, allowed


def open_verified_test_app_db(**kwargs):
    """앱 역할 풀링 연결. test 식별(endpoint·branch·표식)과 접속 사용자(current_user·session_user)를 확인합니다."""
    url, user, allowed = check_test_app_config()
    kwargs.setdefault("prepare_threshold", None)   # PgBouncer 트랜잭션 모드
    conn = connect(url, **kwargs)
    try:
        verify_test_identity(server_identity(conn), allowed)
        who = conn.execute("SELECT current_user AS cur, session_user AS ses").fetchone()
        if who != {"cur": user, "ses": user}:
            raise GuardError("앱 역할 연결의 접속 사용자가 예상과 다릅니다.")
        conn.rollback()
    except BaseException:
        conn.close()
        raise
    return conn, url, user


# --- CLI --------------------------------------------------------------------

def _load_env() -> None:
    if os.getenv("COSMOA_ENV") == "production" or os.getenv("RENDER"):
        return   # 운영 모드는 .env 를 읽지 않음 (app.py 와 같은 기준)
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)


def _print_state(state: dict) -> None:
    print(f"  적용됨: {', '.join(state['applied']) or '(없음)'}")
    print(f"  대기:   {', '.join(state['pending']) or '(없음)'}")
    print(f"  public 테이블: {', '.join(state['tables']) or '(없음)'}")
    for p in state["problems"]:
        print(f"  ! {p}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.common.db_admin", description="업무 DB 관리 명령")
    sub = parser.add_subparsers(dest="cmd", required=True)
    marker = sub.add_parser("test-marker", help="테스트 DB 표식")
    marker.add_argument("action", choices=["check", "init"])
    for name in ("status", "migrate", "rollback-last", "create-first-user", "set-password", "create-user"):
        p = sub.add_parser(name)
        p.add_argument("--target", required=True, choices=sorted(TARGETS))
        if name == "migrate":
            p.add_argument("--dry-run", action="store_true")
        if name in ("create-first-user", "set-password", "create-user"):
            p.add_argument("--email", required=True)
        if name in ("create-first-user", "create-user"):
            p.add_argument("--name", required=True)
            p.add_argument("--team", default="")
        if name == "create-user":
            p.add_argument("--by", required=True, help="계정 생성 담당자(이미 있는 계정)의 이메일 — created_by 에 기록")
    app_role = sub.add_parser("app-role", help="앱용 PostgreSQL 접속 역할 (대시보드 계정과 별개, docs/db_rules.md 8장)")
    app_role.add_argument("action", choices=["init-group", "create-login", "check", "whoami"])
    app_role.add_argument("--target", required=True, choices=sorted(TARGETS))
    app_role.add_argument("--role", help="로그인 역할 이름 cosmoa_app_<이름> (create-login 필수, check 선택)")
    args = parser.parse_args(argv)
    _load_env()

    try:
        refuse_production_env()

        if args.cmd == "test-marker":
            if args.action == "init":
                print(init_test_marker())
            else:
                conn, _ = open_verified_test_db()
                conn.close()
                print("테스트 DB 식별 확인 통과 (허용 endpoint + DB 표식 일치).")
        elif args.cmd == "status":
            conn, _ = open_target(args.target)
            with conn:
                print(f"[{args.target}] 마이그레이션 상태")
                _print_state(inspect_state(conn))
        elif args.cmd == "migrate":
            result = migrate(args.target, dry_run=args.dry_run)
            print(f"[{args.target}] 적용 전")
            _print_state(result["before"])
            if args.dry_run:
                print("  (--dry-run: 적용하지 않음)")
            elif result["applied_now"]:
                print(f"[{args.target}] 이번에 적용: {', '.join(result['applied_now'])}")
                _print_state(result["after"])
            else:
                print(f"[{args.target}] 적용할 마이그레이션이 없습니다.")
        elif args.cmd == "rollback-last":
            done = rollback_last(args.target)
            print(f"[{args.target}] 되돌림: {', '.join(done) or '(없음)'}")
        elif args.cmd == "create-first-user":
            check_first_user_possible(args.target)
            password = _ask_password()
            if password is None:
                print("비밀번호가 8자 미만이거나 확인 값과 다릅니다. 만들지 않았습니다.", file=sys.stderr)
                return 1
            user_id = create_first_user(args.target, args.email, args.name, args.team, password)
            print(f"[{args.target}] 최초 계정을 만들었습니다. (id={user_id})")
        elif args.cmd == "create-user":
            check_create_user_possible(args.target, args.email, args.name, args.team, args.by)
            creator_password = getpass.getpass("계정 생성 담당자(--by) 본인 비밀번호 (화면에 표시되지 않음): ")
            password = _ask_password()
            if password is None:
                print("새 계정 비밀번호가 8자 미만이거나 확인 값과 다릅니다. 만들지 않았습니다.", file=sys.stderr)
                return 1
            user_id = create_user(args.target, email=args.email, name=args.name, team=args.team, password=password,
                                  created_by_email=args.by, created_by_password=creator_password)
            print(f"[{args.target}] 계정을 만들었습니다. (id={user_id}) 첫 비밀번호는 별도 경로로 전달하고, "
                  "본인이 로그인 후 '비밀번호 변경' 화면에서 바꾸게 하세요.")
        elif args.cmd == "set-password":
            check_user_exists(args.target, args.email)
            password = _ask_password()
            if password is None:
                print("비밀번호가 8자 미만이거나 확인 값과 다릅니다. 변경하지 않았습니다.", file=sys.stderr)
                return 1
            set_password(args.target, args.email, password)
            print(f"[{args.target}] 비밀번호를 변경했습니다.")
        elif args.cmd == "app-role":
            return _app_role_command(args)
    except (GuardError, DatabaseConfigError, DatabaseConnectionError, ValueError) as e:
        print(f"거부/실패: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"실패: {mask_secrets(e, *(os.getenv(v) for v in (*TARGETS.values(), 'DATABASE_URL', TEST_APP_URL_VAR)))}",
              file=sys.stderr)
        return 1
    return 0


def _app_role_command(args) -> int:
    if args.action == "whoami":
        problems, lines = app_connection_report(args.target)
        print(f"[{args.target}] 앱 DB 연결 확인")
        for line in lines:
            print(f"  · {line}")
        for p in problems:
            print(f"  ! {p}")
        print("  결과: " + ("앱 역할로 접속 중" if not problems else f"문제 {len(problems)}건"))
        return 0 if not problems else 3
    if args.action == "init-group":
        print(f"[{args.target}] {init_app_group(args.target)}")
        return 0
    if args.action == "create-login":
        if not args.role:
            raise ValueError("--role 이 필요합니다 (예: cosmoa_app_test).")
        if check_create_app_login_possible(args.target, args.role):
            print(f"[{args.target}] {args.role} 역할이 이미 있습니다 (확인 통과, 변경 없음 — 비밀번호를 바꾸지 않음).")
            return 0
        print(f"{args.role} 의 DB 접속 비밀번호를 입력합니다 ({APP_PASSWORD_MIN}자 이상, Neon 강도 기준 60비트 이상).")
        password = _ask_password(APP_PASSWORD_MIN)
        if password is None:
            print(f"비밀번호가 {APP_PASSWORD_MIN}자 미만이거나 확인 값과 다릅니다. 만들지 않았습니다.", file=sys.stderr)
            return 1
        created = create_app_login(args.target, args.role, password)
        print(f"[{args.target}] {args.role} 역할을 {'만들었습니다' if created else '확인했습니다 (이미 있음, 변경 없음)'}. "
              "접속 주소는 별도 경로로 전달하세요.")
    problems, info = app_role_report(args.target, args.role)
    print(f"[{args.target}] 앱 역할 확인{' — ' + args.role if args.role else ''}")
    for line in info:
        print(f"  · {line}")
    for p in problems:
        print(f"  ! {p}")
    print("  결과: " + ("통과" if not problems else f"문제 {len(problems)}건"))
    return 0 if not problems else 3


if __name__ == "__main__":
    sys.exit(main())
