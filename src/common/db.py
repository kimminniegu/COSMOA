"""업무 DB(Neon PostgreSQL) 연결 (PM 관리)

- psycopg 3 연결 풀 + dict_row. SQL 은 직접 작성하고 값은 항상 %s 매개변수로 넘깁니다.
- import 만으로는 접속하지 않습니다. 첫 사용(connection/transaction) 시 풀을 엽니다.
- 접속 주소는 생성자로 주입합니다. 앱은 Database.from_env("DATABASE_URL"),
  테스트는 Database.from_env("TEST_DATABASE_URL") 처럼 서로 다른 설정을 씁니다. 다른 변수로 자동 대체하지 않습니다.
- 접속 오류 메시지에서 비밀번호·접속 주소·Neon 호스트를 가립니다.

사용 예
    db = Database.from_env("DATABASE_URL")
    with db.transaction() as cur:          # 정상 종료 → 커밋, 예외 → 롤백
        cur.execute("SELECT id, name FROM projects WHERE id = %s", (project_id,))
        row = cur.fetchone()               # {"id": ..., "name": ...}
"""

from __future__ import annotations

import os
import re
import threading
from contextlib import contextmanager
from typing import Iterator
from urllib.parse import unquote, urlsplit

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_ENDPOINT_RE = re.compile(r"^(ep-[a-z0-9-]+?)(-pooler)?\.")
_URL_RE = re.compile(r"postgres(?:ql)?(?:\+\w+)?://\S+", re.I)
_NEON_HOST_RE = re.compile(r"\bep-[a-z0-9-]+(?:\.[a-z0-9.-]+)?", re.I)


class DatabaseConfigError(RuntimeError):
    """접속 설정이 없거나 형식이 잘못됨."""


class DatabaseConnectionError(RuntimeError):
    """접속 실패. 메시지에는 비밀값이 들어 있지 않습니다."""


def mask_secrets(text: str, *urls: str | None) -> str:
    """오류 메시지에서 접속 주소 전체·비밀번호·Neon 호스트를 가립니다."""
    text = str(text)
    for url in urls:
        if not url:
            continue
        parts = urlsplit(url)
        for secret in (url, parts.password, unquote(parts.password or "")):
            if secret:
                text = text.replace(secret, "***")
    text = _URL_RE.sub("<접속 주소>", text)
    return _NEON_HOST_RE.sub("<호스트>", text)


def neon_endpoint_id(url: str) -> str | None:
    """Neon 주소의 endpoint id (ep-...). 풀링 주소의 -pooler 는 뗍니다. Neon 주소가 아니면 None."""
    m = _ENDPOINT_RE.match(urlsplit(url).hostname or "")
    return m.group(1) if m else None


def is_pooled_url(url: str) -> bool:
    m = _ENDPOINT_RE.match(urlsplit(url).hostname or "")
    return bool(m and m.group(2))


def env_url(var_name: str) -> str:
    """환경변수에서 접속 주소를 읽습니다. 비어 있으면 오류 (다른 변수로 대체하지 않음)."""
    url = (os.getenv(var_name) or "").strip()
    if not url:
        raise DatabaseConfigError(f"{var_name} 가 설정되지 않았습니다.")
    if urlsplit(url).scheme not in ("postgres", "postgresql"):
        raise DatabaseConfigError(f"{var_name} 는 postgresql:// 주소여야 합니다.")
    return url


def connect(url: str, **kwargs) -> psycopg.Connection:
    """단일 연결 (관리 명령·검사용). dict_row 기본, 오류 메시지는 비밀값을 가립니다."""
    kwargs.setdefault("row_factory", dict_row)
    kwargs.setdefault("connect_timeout", 15)
    try:
        return psycopg.connect(url, **kwargs)
    except psycopg.Error as e:
        raise DatabaseConnectionError(mask_secrets(e, url)) from None


class Database:
    """연결 풀 하나. 앱용·테스트용을 따로 만들어 주입합니다."""

    def __init__(self, url: str, *, min_size: int = 1, max_size: int = 5, name: str = "cosmoa",
                 timeout: float = 20) -> None:
        if not url:
            raise DatabaseConfigError("접속 주소가 비어 있습니다.")
        self._url = url
        self._min_size = min_size
        self._max_size = max_size
        self._timeout = timeout
        self._name = name
        self._pool: ConnectionPool | None = None
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls, var_name: str, **kwargs) -> "Database":
        kwargs.setdefault("name", var_name.lower())
        return cls(env_url(var_name), **kwargs)

    def __repr__(self) -> str:   # 주소를 노출하지 않음
        return f"<Database {self._name} open={self._pool is not None}>"

    def _get_pool(self) -> ConnectionPool:
        with self._lock:
            if self._pool is None:
                conn_kwargs = {"row_factory": dict_row, "connect_timeout": 15}
                if is_pooled_url(self._url):
                    conn_kwargs["prepare_threshold"] = None   # PgBouncer(트랜잭션 모드)에서 서버측 prepared statement 미사용
                pool = ConnectionPool(
                    self._url, min_size=self._min_size, max_size=self._max_size, kwargs=conn_kwargs,
                    check=ConnectionPool.check_connection,      # Neon 컴퓨트가 쉬는 동안 끊긴 연결을 걸러냄
                    name=self._name, open=False,
                )
                try:
                    pool.open(wait=True, timeout=self._timeout)
                except Exception as e:
                    pool.close(timeout=1)
                    raise DatabaseConnectionError(mask_secrets(f"DB 연결 풀을 열지 못했습니다: {e}", self._url)) from None
                self._pool = pool
            return self._pool

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        """풀에서 연결 하나. 블록이 정상 종료하면 커밋, 예외면 롤백 후 반환됩니다."""
        try:
            cm = self._get_pool().connection(timeout=self._timeout)
            conn = cm.__enter__()
        except DatabaseConnectionError:
            raise
        except psycopg.Error as e:
            raise DatabaseConnectionError(mask_secrets(e, self._url)) from None
        except Exception as e:   # PoolTimeout 등
            raise DatabaseConnectionError(mask_secrets(f"DB 연결을 얻지 못했습니다: {e}", self._url)) from None
        exc_info = (None, None, None)
        try:
            yield conn
        except BaseException as e:
            exc_info = (type(e), e, e.__traceback__)
            raise
        finally:
            cm.__exit__(*exc_info)

    @contextmanager
    def transaction(self) -> Iterator[psycopg.Cursor]:
        """한 트랜잭션의 커서(dict_row). 정상 종료 → 커밋, 예외 → 롤백 후 예외를 다시 올립니다."""
        with self.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    yield cur

    def close(self) -> None:
        with self._lock:
            if self._pool is not None:
                self._pool.close()
                self._pool = None
