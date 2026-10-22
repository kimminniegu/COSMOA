-- 1단계 보완: 프로젝트 이력의 트랜잭션 식별, 신규 프로젝트 생성 규칙
-- 0001_core 는 test·dev 에 적용되어 수정하지 않는다. 바꿀 내용은 이 파일에 둔다.
-- depends: 0001_core

-- project_history.xact_id: 이력을 기록한 최상위 트랜잭션 id (PostgreSQL pg_current_xact_id(), xid8)
-- 기존 행은 값을 알 수 없으므로 NULL 로 두고 고치지 않는다. (NOT VALID: 기존 행은 검사하지 않음)
-- 새 행은 아래 BEFORE INSERT 트리거가 서버에서 채운다. 클라이언트가 보낸 값은 쓰지 않는다.
-- created_at 은 표시용 시각으로 유지한다.
ALTER TABLE project_history ADD COLUMN xact_id xid8;

ALTER TABLE project_history
    ADD CONSTRAINT project_history_xact_id_required CHECK (xact_id IS NOT NULL) NOT VALID;

CREATE FUNCTION project_history_set_xact_id() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.xact_id := pg_current_xact_id();
    RETURN NEW;
END;
$$;

CREATE TRIGGER project_history_set_xact_id BEFORE INSERT ON project_history
    FOR EACH ROW EXECUTE FUNCTION project_history_set_xact_id();

-- 프로젝트의 단계·상태·납기일 변경에는 같은 트랜잭션(xact_id)의 project_history 행이 있어야 한다.
-- 커밋 시점(DEFERRED)에 변경 1건마다 같은 전후 값의 이력을 찾는다. 과거 트랜잭션의 이력으로는 통과할 수 없다.
CREATE OR REPLACE FUNCTION projects_require_history() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.stage IS DISTINCT FROM OLD.stage AND NOT EXISTS (
        SELECT 1 FROM project_history h
        WHERE h.project_id = NEW.id AND h.field = 'stage' AND h.xact_id = pg_current_xact_id()
          AND h.old_value IS NOT DISTINCT FROM OLD.stage AND h.new_value IS NOT DISTINCT FROM NEW.stage
    ) THEN
        RAISE EXCEPTION 'projects.stage 변경에는 같은 트랜잭션의 project_history 기록이 필요합니다 (project_id=%)', NEW.id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.state IS DISTINCT FROM OLD.state AND NOT EXISTS (
        SELECT 1 FROM project_history h
        WHERE h.project_id = NEW.id AND h.field = 'state' AND h.xact_id = pg_current_xact_id()
          AND h.old_value IS NOT DISTINCT FROM OLD.state AND h.new_value IS NOT DISTINCT FROM NEW.state
    ) THEN
        RAISE EXCEPTION 'projects.state 변경에는 같은 트랜잭션의 project_history 기록이 필요합니다 (project_id=%)', NEW.id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.due_date IS DISTINCT FROM OLD.due_date AND NOT EXISTS (
        SELECT 1 FROM project_history h
        WHERE h.project_id = NEW.id AND h.field = 'due_date' AND h.xact_id = pg_current_xact_id()
          AND h.old_value IS NOT DISTINCT FROM to_char(OLD.due_date, 'YYYY-MM-DD')
          AND h.new_value IS NOT DISTINCT FROM to_char(NEW.due_date, 'YYYY-MM-DD')
    ) THEN
        RAISE EXCEPTION 'projects.due_date 변경에는 같은 트랜잭션의 project_history 기록이 필요합니다 (project_id=%)', NEW.id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NULL;
END;
$$;

-- 신규 프로젝트는 stage=proposal, state=active 로만 만든다. (납기일은 생성 시 입력 가능)
-- 이후 단계·상태 변경은 이력과 함께 한다 (src/common/projects.py change_project).
CREATE FUNCTION projects_check_new() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.stage <> 'proposal' OR NEW.state <> 'active' THEN
        RAISE EXCEPTION '신규 프로젝트는 stage=proposal, state=active 로만 생성합니다 (이후 변경은 이력과 함께)'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER projects_new_defaults BEFORE INSERT ON projects
    FOR EACH ROW EXECUTE FUNCTION projects_check_new();
