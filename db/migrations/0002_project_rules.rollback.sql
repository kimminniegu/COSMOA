-- 0002_project_rules 되돌리기 — 테스트 DB 확인용. xact_id 열을 지우므로 데이터가 있는 개발·운영 DB 에는 쓰지 않는다.
-- depends:

DROP TRIGGER projects_new_defaults ON projects;
DROP FUNCTION projects_check_new();
CREATE OR REPLACE FUNCTION projects_require_history() RETURNS trigger
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
DROP TRIGGER project_history_set_xact_id ON project_history;
DROP FUNCTION project_history_set_xact_id();
ALTER TABLE project_history DROP CONSTRAINT project_history_xact_id_required;
ALTER TABLE project_history DROP COLUMN xact_id;
