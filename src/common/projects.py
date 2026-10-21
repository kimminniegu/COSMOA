"""고객사·프로젝트 생성·조회 SQL, 프로젝트 단계·상태·납기일 변경 (PM 관리)

생성·조회 업무 규칙과 API 는 projects_service.py / projects_api.py (docs/api_contract.md 5장).

projects 수정과 project_history 추가를 같은 트랜잭션에서 합니다. (docs/db_rules.md 2-2)
호출하는 쪽이 Database.transaction() 의 커서를 넘기면, 둘 중 하나라도 실패할 때 함께 롤백됩니다.
DB 도 커밋 시점에 같은 트랜잭션(project_history.xact_id)의 이력이 없는 변경을 거부합니다 (0002_project_rules).

    with db.transaction() as cur:
        change_project(cur, project_id, actor_id=session_user_id, state="hold", reason="바이어 예산 재검토")
"""

from __future__ import annotations

from datetime import date

STAGES = ("proposal", "development", "order", "production", "shipping", "completed")
STATES = ("active", "hold", "drop")
REASON_REQUIRED_STATES = ("hold", "drop")

_UNSET = object()


class ProjectNotFound(LookupError):
    pass


def _as_text(value) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, date) else str(value)


def create_customer(cur, *, name: str, actor_id: int) -> dict:
    """새 고객사. 작성자는 서버 로그인 사용자입니다."""
    if actor_id is None:
        raise PermissionError("로그인 사용자 없이 고객사를 만들 수 없습니다.")
    if not (name or "").strip():
        raise ValueError("고객사명이 필요합니다.")
    cur.execute("INSERT INTO customers (name, created_by) VALUES (%s, %s) RETURNING id",
                (name.strip(), actor_id))
    return cur.fetchone()


# --- 조회 (고객사·프로젝트 API, src/common/projects_api.py) --------------------------

_CUSTOMER_COLUMNS = "c.id, c.name, c.archived_at, c.created_by, u.name AS created_by_name, c.created_at"
_PROJECT_COLUMNS = """p.id, p.customer_id, c.name AS customer_name, p.name, p.stage, p.state, p.due_date, p.archived_at,
                      p.created_by, u.name AS created_by_name, p.created_at"""


def lock_customer(cur, customer_id: int) -> dict | None:
    """프로젝트 생성 중 고객사가 보관되지 않도록 공유 잠금."""
    cur.execute("SELECT id, archived_at FROM customers WHERE id = %s FOR SHARE", (customer_id,))
    return cur.fetchone()


def get_customer(cur, customer_id: int) -> dict | None:
    cur.execute(f"SELECT {_CUSTOMER_COLUMNS} FROM customers c JOIN users u ON u.id = c.created_by WHERE c.id = %s",
                (customer_id,))
    return cur.fetchone()


def list_customers(cur, *, search: str | None, limit: int, after_id: int | None) -> list[dict]:
    """사용 중(보관 안 됨)인 고객사를 이름순으로. 다음 페이지는 마지막 항목 id(after_id) 다음부터."""
    pattern = None if not search else "%" + search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    cur.execute(
        f"""SELECT {_CUSTOMER_COLUMNS} FROM customers c JOIN users u ON u.id = c.created_by
            WHERE c.archived_at IS NULL
              AND (%s::text IS NULL OR c.name ILIKE %s::text)
              AND (%s::bigint IS NULL OR (lower(c.name), c.id) > (SELECT lower(name), id FROM customers WHERE id = %s::bigint))
            ORDER BY lower(c.name), c.id LIMIT %s""",
        (pattern, pattern, after_id, after_id, limit))
    return cur.fetchall()


def get_project(cur, project_id: int) -> dict | None:
    cur.execute(f"""SELECT {_PROJECT_COLUMNS} FROM projects p
                    JOIN customers c ON c.id = p.customer_id JOIN users u ON u.id = p.created_by
                    WHERE p.id = %s""", (project_id,))
    return cur.fetchone()


def list_projects(cur, customer_id: int, *, limit: int, before_id: int | None) -> list[dict]:
    """고객사의 사용 중인 프로젝트를 최신순으로. 다음 페이지는 마지막 항목 id(before_id) 이전부터."""
    cur.execute(f"""SELECT {_PROJECT_COLUMNS} FROM projects p
                    JOIN customers c ON c.id = p.customer_id JOIN users u ON u.id = p.created_by
                    WHERE p.customer_id = %s AND p.archived_at IS NULL AND (%s::bigint IS NULL OR p.id < %s::bigint)
                    ORDER BY p.id DESC LIMIT %s""", (customer_id, before_id, before_id, limit))
    return cur.fetchall()


def create_project(cur, *, customer_id: int, name: str, actor_id: int, due_date=None) -> dict:
    """새 프로젝트. 단계·상태는 항상 proposal / active 로 시작합니다 (DB 도 다른 값을 거부, 0002).
    납기일은 생성 시 넣을 수 있습니다 (None = 미정). 이후 변경은 change_project() 로 합니다."""
    if actor_id is None:
        raise PermissionError("로그인 사용자 없이 프로젝트를 만들 수 없습니다.")
    if not (name or "").strip():
        raise ValueError("프로젝트(제품)명이 필요합니다.")
    if isinstance(due_date, str):
        due_date = date.fromisoformat(due_date)
    cur.execute(
        """INSERT INTO projects (customer_id, name, due_date, created_by)
           VALUES (%s, %s, %s, %s)
           RETURNING id, customer_id, name, stage, state, due_date, created_by, created_at""",
        (customer_id, name.strip(), due_date, actor_id),
    )
    return cur.fetchone()


def change_project(cur, project_id: int, *, actor_id: int, stage=_UNSET, state=_UNSET,
                   due_date=_UNSET, reason: str | None = None) -> list[dict]:
    """바뀐 항목만 수정하고 항목마다 이력 1행을 추가합니다. 추가한 이력 행 목록을 돌려줍니다.

    actor_id 는 서버 로그인 세션 사용자 id 입니다. 요청 본문 값을 쓰지 않습니다.
    due_date=None 은 납기일 해제(미정)입니다.
    """
    if actor_id is None:
        raise PermissionError("로그인 사용자 없이 프로젝트를 변경할 수 없습니다.")
    if stage is not _UNSET and stage not in STAGES:
        raise ValueError(f"알 수 없는 단계: {stage}")
    if state is not _UNSET and state not in STATES:
        raise ValueError(f"알 수 없는 상태: {state}")
    if state in REASON_REQUIRED_STATES and not (reason or "").strip():
        raise ValueError("홀드·드롭으로 바꿀 때는 사유가 필요합니다.")
    if isinstance(due_date, str):
        due_date = date.fromisoformat(due_date)

    cur.execute("SELECT id, stage, state, due_date FROM projects WHERE id = %s FOR UPDATE", (project_id,))
    current = cur.fetchone()
    if current is None:
        raise ProjectNotFound(project_id)

    changes = [(field, current[field], new) for field, new in
               (("stage", stage), ("state", state), ("due_date", due_date))
               if new is not _UNSET and new != current[field]]
    if not changes:
        return []

    sets = ", ".join(f"{field} = %s" for field, _, _ in changes)   # 열 이름은 위 고정 목록에서만 옴
    cur.execute(f"UPDATE projects SET {sets} WHERE id = %s", [new for _, _, new in changes] + [project_id])

    history = []
    for field, old, new in changes:
        cur.execute(
            """INSERT INTO project_history (project_id, field, old_value, new_value, reason, created_by)
               VALUES (%s, %s, %s, %s, %s, %s)
               RETURNING id, project_id, field, old_value, new_value, reason, created_by, created_at""",
            (project_id, field, _as_text(old), _as_text(new), (reason or "").strip() or None, actor_id),
        )
        history.append(cur.fetchone())
    return history
