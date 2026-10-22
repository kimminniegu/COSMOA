-- 공통 기반 1단계: users, customers, customer_contacts, projects, project_history
-- 근거: docs/db_rules.md 2·3장, docs/data_contract.md 1장
-- 이미 어느 DB 에든 적용한 뒤에는 이 파일을 수정하지 않는다. 바꿀 내용은 새 파일로 추가한다.
-- depends:

-- 공통 트리거 함수 ---------------------------------------------------------

-- 수정 가능한 테이블의 updated_at 갱신
CREATE FUNCTION set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

-- "추가만" 테이블의 UPDATE/DELETE/TRUNCATE 거부
CREATE FUNCTION forbid_append_only_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% 은(는) 추가만 허용합니다 (% 거부)', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$;

-- 삭제하지 않고 보관하는 테이블의 DELETE/TRUNCATE 거부 (archived_at 으로 보관)
CREATE FUNCTION forbid_delete_archive_instead() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% 은(는) 삭제하지 않고 archived_at 으로 보관합니다', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END;
$$;

-- users -------------------------------------------------------------------
-- created_by NULL = 시스템 작업(최초 계정 생성). 그런 행은 하나만 허용한다.
-- 비밀번호는 werkzeug generate_password_hash 형식(scrypt / pbkdf2)만 저장한다.
CREATE TABLE users (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email         text NOT NULL,
    name          text NOT NULL,
    team          text NOT NULL DEFAULT '',
    password_hash text NOT NULL,
    created_by    bigint REFERENCES users (id) ON DELETE RESTRICT,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT users_email_key UNIQUE (email),
    CONSTRAINT users_email_normalized CHECK (email = lower(btrim(email)) AND email LIKE '%_@_%'),
    CONSTRAINT users_name_not_blank CHECK (btrim(name) <> ''),
    CONSTRAINT users_password_hash_format
        CHECK (password_hash ~ '^(scrypt|pbkdf2):[^$]+\$[^$]+\$[0-9a-f]+$')
);
CREATE UNIQUE INDEX users_single_system_created ON users ((true)) WHERE created_by IS NULL;
CREATE TRIGGER users_set_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- customers ---------------------------------------------------------------
CREATE TABLE customers (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        text NOT NULL,
    archived_at timestamptz,
    created_by  bigint NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT customers_name_not_blank CHECK (btrim(name) <> '')
);
CREATE TRIGGER customers_set_updated_at BEFORE UPDATE ON customers
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER customers_no_delete BEFORE DELETE ON customers
    FOR EACH ROW EXECUTE FUNCTION forbid_delete_archive_instead();
CREATE TRIGGER customers_no_truncate BEFORE TRUNCATE ON customers
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_delete_archive_instead();

-- customer_contacts -------------------------------------------------------
CREATE TABLE customer_contacts (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id bigint NOT NULL REFERENCES customers (id) ON DELETE RESTRICT,
    name        text NOT NULL,
    created_by  bigint NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT customer_contacts_name_not_blank CHECK (btrim(name) <> '')
);
CREATE INDEX customer_contacts_customer_id_idx ON customer_contacts (customer_id);
CREATE TRIGGER customer_contacts_set_updated_at BEFORE UPDATE ON customer_contacts
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- projects (프로젝트 = 단일 제품) -----------------------------------------
-- 단계(stage)와 상태(state)는 따로 관리한다. 납기일 미정이면 due_date NULL.
CREATE TABLE projects (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id bigint NOT NULL REFERENCES customers (id) ON DELETE RESTRICT,
    name        text NOT NULL,
    stage       text NOT NULL DEFAULT 'proposal',
    state       text NOT NULL DEFAULT 'active',
    due_date    date,
    archived_at timestamptz,
    created_by  bigint NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT projects_name_not_blank CHECK (btrim(name) <> ''),
    CONSTRAINT projects_stage_check
        CHECK (stage IN ('proposal', 'development', 'order', 'production', 'shipping', 'completed')),
    CONSTRAINT projects_state_check CHECK (state IN ('active', 'hold', 'drop'))
);
CREATE INDEX projects_customer_id_idx ON projects (customer_id);
CREATE TRIGGER projects_set_updated_at BEFORE UPDATE ON projects
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER projects_no_delete BEFORE DELETE ON projects
    FOR EACH ROW EXECUTE FUNCTION forbid_delete_archive_instead();
CREATE TRIGGER projects_no_truncate BEFORE TRUNCATE ON projects
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_delete_archive_instead();

-- project_history (단계·상태·납기일 변경 1번, 추가만) ----------------------
-- old_value / new_value 는 NULL 허용 (납기일 최초 지정·해제). 홀드·드롭으로 바꿀 때 reason 필수.
CREATE TABLE project_history (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id bigint NOT NULL REFERENCES projects (id) ON DELETE RESTRICT,
    field      text NOT NULL,
    old_value  text,
    new_value  text,
    reason     text,
    created_by bigint NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT project_history_field_check CHECK (field IN ('stage', 'state', 'due_date')),
    CONSTRAINT project_history_changed CHECK (old_value IS DISTINCT FROM new_value),
    CONSTRAINT project_history_stage_values CHECK (
        field <> 'stage' OR (
            old_value IN ('proposal', 'development', 'order', 'production', 'shipping', 'completed')
            AND new_value IN ('proposal', 'development', 'order', 'production', 'shipping', 'completed'))),
    CONSTRAINT project_history_state_values CHECK (
        field <> 'state' OR (
            old_value IN ('active', 'hold', 'drop') AND new_value IN ('active', 'hold', 'drop'))),
    CONSTRAINT project_history_due_date_values CHECK (
        field <> 'due_date' OR (
            (old_value IS NULL OR old_value ~ '^\d{4}-\d{2}-\d{2}$')
            AND (new_value IS NULL OR new_value ~ '^\d{4}-\d{2}-\d{2}$'))),
    CONSTRAINT project_history_reason_required CHECK (
        field <> 'state' OR new_value NOT IN ('hold', 'drop')
        OR (reason IS NOT NULL AND btrim(reason) <> ''))
);
CREATE INDEX project_history_project_id_idx ON project_history (project_id, id);
CREATE TRIGGER project_history_append_only BEFORE UPDATE OR DELETE ON project_history
    FOR EACH ROW EXECUTE FUNCTION forbid_append_only_change();
CREATE TRIGGER project_history_no_truncate BEFORE TRUNCATE ON project_history
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_append_only_change();

-- 프로젝트의 단계·상태·납기일 변경에는 같은 트랜잭션의 project_history 행이 있어야 한다.
-- 커밋 시점(DEFERRED)에 검사하므로 UPDATE 와 이력 INSERT 의 순서는 상관없다.
-- 같은 트랜잭션 판단: 이력 created_at 기본값 now() = 트랜잭션 시작 시각.
CREATE FUNCTION projects_require_history() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.stage IS DISTINCT FROM OLD.stage AND NOT EXISTS (
        SELECT 1 FROM project_history h
        WHERE h.project_id = NEW.id AND h.field = 'stage' AND h.created_at = now()
          AND h.old_value IS NOT DISTINCT FROM OLD.stage AND h.new_value IS NOT DISTINCT FROM NEW.stage
    ) THEN
        RAISE EXCEPTION 'projects.stage 변경에는 같은 트랜잭션의 project_history 기록이 필요합니다 (project_id=%)', NEW.id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.state IS DISTINCT FROM OLD.state AND NOT EXISTS (
        SELECT 1 FROM project_history h
        WHERE h.project_id = NEW.id AND h.field = 'state' AND h.created_at = now()
          AND h.old_value IS NOT DISTINCT FROM OLD.state AND h.new_value IS NOT DISTINCT FROM NEW.state
    ) THEN
        RAISE EXCEPTION 'projects.state 변경에는 같은 트랜잭션의 project_history 기록이 필요합니다 (project_id=%)', NEW.id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.due_date IS DISTINCT FROM OLD.due_date AND NOT EXISTS (
        SELECT 1 FROM project_history h
        WHERE h.project_id = NEW.id AND h.field = 'due_date' AND h.created_at = now()
          AND h.old_value IS NOT DISTINCT FROM to_char(OLD.due_date, 'YYYY-MM-DD')
          AND h.new_value IS NOT DISTINCT FROM to_char(NEW.due_date, 'YYYY-MM-DD')
    ) THEN
        RAISE EXCEPTION 'projects.due_date 변경에는 같은 트랜잭션의 project_history 기록이 필요합니다 (project_id=%)', NEW.id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER projects_change_has_history
    AFTER UPDATE OF stage, state, due_date ON projects
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION projects_require_history();
