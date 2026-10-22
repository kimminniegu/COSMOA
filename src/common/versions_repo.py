"""탭 저장본·최종본·반영 출처 SQL (PM 관리) — 커서(dict_row)를 받아 SQL 만 실행합니다. 업무 규칙은 versions.py.

모든 값은 %s 매개변수로 넘깁니다. version_no·xact_id 는 DB 트리거가 정합니다 (0003_versioning).
"""

from __future__ import annotations

from psycopg.types.json import Jsonb

_VERSION_COLUMNS = """v.id, v.project_id, v.tab, v.version_no, v.based_on_id, b.version_no AS based_on_version_no,
                      v.schema_version, v.title, v.created_by, u.name AS created_by_name, v.created_at"""


def lock_project(cur, project_id: int) -> dict | None:
    """프로젝트 행 잠금. 저장 계약이 프로젝트에 묶인 탭(개발요청서 v1)은 고객사 id·이름도 씁니다."""
    cur.execute("""SELECT p.id, p.archived_at, p.name, p.customer_id, c.name AS customer_name
                   FROM projects p JOIN customers c ON c.id = p.customer_id
                   WHERE p.id = %s FOR UPDATE OF p""", (project_id,))
    return cur.fetchone()


def project_exists(cur, project_id: int) -> bool:
    cur.execute("SELECT 1 FROM projects WHERE id = %s", (project_id,))
    return cur.fetchone() is not None


def latest_version(cur, project_id: int, tab: str) -> dict | None:
    cur.execute("""SELECT id, version_no FROM tab_versions WHERE project_id = %s AND tab = %s
                   ORDER BY version_no DESC LIMIT 1""", (project_id, tab))
    return cur.fetchone()


def version_scope(cur, version_id: int) -> dict | None:
    """저장본의 프로젝트·탭·번호 (payload 없이)."""
    cur.execute("SELECT id, project_id, tab, version_no FROM tab_versions WHERE id = %s", (version_id,))
    return cur.fetchone()


def insert_version(cur, *, project_id: int, tab: str, based_on_id: int | None, schema_version: int,
                   title: str | None, payload: dict, created_by: int) -> dict:
    cur.execute(
        """INSERT INTO tab_versions (project_id, tab, based_on_id, schema_version, title, payload, created_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           RETURNING id, project_id, tab, version_no, based_on_id, schema_version, title, created_by, created_at""",
        (project_id, tab, based_on_id, schema_version, title, Jsonb(payload), created_by))
    return cur.fetchone()


def insert_link(cur, *, project_id: int, version_id: int, tab: str, source_tab: str, source_version_id: int,
                applied_values: dict, created_by: int) -> dict:
    cur.execute(
        """INSERT INTO version_links (project_id, version_id, tab, source_tab, source_version_id, applied_values, created_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           RETURNING id, source_tab, source_version_id, created_at""",
        (project_id, version_id, tab, source_tab, source_version_id, Jsonb(applied_values), created_by))
    return cur.fetchone()


def list_versions(cur, project_id: int, tab: str, *, limit: int, before_version_no: int | None) -> list[dict]:
    cur.execute(
        f"""SELECT {_VERSION_COLUMNS}, octet_length(v.payload::text) AS payload_bytes
            FROM tab_versions v
            JOIN users u ON u.id = v.created_by
            LEFT JOIN tab_versions b ON b.id = v.based_on_id
            WHERE v.project_id = %s AND v.tab = %s AND (%s::int IS NULL OR v.version_no < %s::int)
            ORDER BY v.version_no DESC LIMIT %s""",
        (project_id, tab, before_version_no, before_version_no, limit))
    return cur.fetchall()


def get_version(cur, version_id: int) -> dict | None:
    cur.execute(
        f"""SELECT {_VERSION_COLUMNS}, v.payload
            FROM tab_versions v
            JOIN users u ON u.id = v.created_by
            LEFT JOIN tab_versions b ON b.id = v.based_on_id
            WHERE v.id = %s""", (version_id,))
    return cur.fetchone()


def links_of(cur, version_id: int) -> list[dict]:
    cur.execute(
        """SELECT l.id, l.source_tab, l.source_version_id, s.version_no AS source_version_no, l.applied_values, l.created_at
           FROM version_links l JOIN tab_versions s ON s.id = l.source_version_id
           WHERE l.version_id = %s ORDER BY l.id""", (version_id,))
    return cur.fetchall()


def last_final(cur, project_id: int, tab: str) -> dict | None:
    """(project_id, tab) 의 가장 큰 id 최종본 기록 = 현재 상태."""
    cur.execute(
        """SELECT f.id, f.action, f.version_id, v.version_no, f.created_by, u.name AS created_by_name, f.created_at
           FROM final_history f
           JOIN users u ON u.id = f.created_by
           LEFT JOIN tab_versions v ON v.id = f.version_id
           WHERE f.project_id = %s AND f.tab = %s
           ORDER BY f.id DESC LIMIT 1""", (project_id, tab))
    return cur.fetchone()


def current_final_version_id(cur, project_id: int, tab: str) -> int | None:
    row = last_final(cur, project_id, tab)
    return row["version_id"] if row and row["action"] == "set" else None


def insert_final(cur, *, project_id: int, tab: str, action: str, version_id: int | None, created_by: int) -> dict:
    cur.execute(
        """INSERT INTO final_history (project_id, tab, action, version_id, created_by)
           VALUES (%s, %s, %s, %s, %s) RETURNING id""",
        (project_id, tab, action, version_id, created_by))
    return cur.fetchone()


def list_final_history(cur, project_id: int, tab: str, *, limit: int, before_id: int | None) -> list[dict]:
    cur.execute(
        """SELECT f.id, f.action, f.version_id, v.version_no, f.created_by, u.name AS created_by_name, f.created_at
           FROM final_history f
           JOIN users u ON u.id = f.created_by
           LEFT JOIN tab_versions v ON v.id = f.version_id
           WHERE f.project_id = %s AND f.tab = %s AND (%s::bigint IS NULL OR f.id < %s::bigint)
           ORDER BY f.id DESC LIMIT %s""",
        (project_id, tab, before_id, before_id, limit))
    return cur.fetchall()
