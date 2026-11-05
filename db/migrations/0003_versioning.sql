-- 2단계 공통 저장 엔진: tab_versions, final_history, version_links
-- 근거: docs/db_rules.md 2-2·3·4·5장, docs/data_contract.md 2·6장
-- 규제 메모 출처(source_note_id)와 regulatory_notes 는 4단계 마이그레이션에서 추가한다. 이 파일은 저장본 출처만 다룬다.
-- depends: 0002_project_rules

-- tab_versions (탭 저장본 1개, 추가만) --------------------------------------
-- version_no: BEFORE INSERT 트리거가 프로젝트 행을 잠근 뒤 (project_id, tab) 의 max + 1 로 부여한다. 클라이언트 값은 쓰지 않는다.
-- xact_id: 저장한 트랜잭션 id (서버 기록). version_links 가 "같은 트랜잭션에서 저장한 저장본" 인지 확인하는 데 쓴다.
-- based_on_id: 같은 프로젝트·같은 탭에서 편집을 시작한 이전 저장본. 새로 작성하면 NULL.
CREATE TABLE tab_versions (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id     bigint NOT NULL REFERENCES projects (id) ON DELETE RESTRICT,
    tab            text NOT NULL,
    version_no     integer NOT NULL,
    based_on_id    bigint,
    schema_version integer NOT NULL,
    title          text,
    payload        jsonb NOT NULL,
    xact_id        xid8 NOT NULL,
    created_by     bigint NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    created_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT tab_versions_tab_check CHECK (tab IN ('regulatory', 'margin', 'simulation', 'requisition')),
    CONSTRAINT tab_versions_version_no_positive CHECK (version_no >= 1),
    CONSTRAINT tab_versions_schema_version_positive CHECK (schema_version >= 1),
    CONSTRAINT tab_versions_title_check CHECK (title IS NULL OR (btrim(title) <> '' AND char_length(title) <= 200)),
    CONSTRAINT tab_versions_payload_sections CHECK (
        jsonb_typeof(payload) = 'object'
        AND payload ?& ARRAY['context', 'inputs', 'outputs', 'meta']
        AND jsonb_typeof(payload -> 'context') = 'object' AND jsonb_typeof(payload -> 'inputs') = 'object'
        AND jsonb_typeof(payload -> 'outputs') = 'object' AND jsonb_typeof(payload -> 'meta') = 'object'),
    CONSTRAINT tab_versions_based_on_earlier CHECK (based_on_id IS NULL OR based_on_id < id),
    CONSTRAINT tab_versions_version_key UNIQUE (project_id, tab, version_no),
    CONSTRAINT tab_versions_scope_key UNIQUE (id, project_id, tab),
    CONSTRAINT tab_versions_based_on_fk FOREIGN KEY (based_on_id, project_id, tab)
        REFERENCES tab_versions (id, project_id, tab) ON DELETE RESTRICT
);

CREATE FUNCTION tab_versions_assign() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    -- 같은 프로젝트의 저장을 한 번에 하나씩 (호출 쪽이 이미 잠갔어도 같은 트랜잭션이면 그대로 통과)
    PERFORM 1 FROM projects WHERE id = NEW.project_id FOR UPDATE;
    SELECT coalesce(max(v.version_no), 0) + 1 INTO NEW.version_no
    FROM tab_versions v WHERE v.project_id = NEW.project_id AND v.tab = NEW.tab;
    NEW.xact_id := pg_current_xact_id();
    RETURN NEW;
END;
$$;

CREATE TRIGGER tab_versions_assign BEFORE INSERT ON tab_versions
    FOR EACH ROW EXECUTE FUNCTION tab_versions_assign();
CREATE TRIGGER tab_versions_append_only BEFORE UPDATE OR DELETE ON tab_versions
    FOR EACH ROW EXECUTE FUNCTION forbid_append_only_change();
CREATE TRIGGER tab_versions_no_truncate BEFORE TRUNCATE ON tab_versions
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_append_only_change();

-- final_history (최종본 지정·해제 1번, 추가만) ------------------------------
-- 현재 최종본 = (project_id, tab) 의 가장 큰 id 기록. set → 그 version_id, unset·기록 없음 → 최종본 없음.
-- set 은 version_id 필수, unset 은 NULL. 같은 프로젝트·같은 탭 저장본만 (복합 FK).
CREATE TABLE final_history (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id bigint NOT NULL REFERENCES projects (id) ON DELETE RESTRICT,
    tab        text NOT NULL,
    action     text NOT NULL,
    version_id bigint,
    created_by bigint NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT final_history_tab_check CHECK (tab IN ('regulatory', 'margin', 'simulation', 'requisition')),
    CONSTRAINT final_history_action_check CHECK (action IN ('set', 'unset')),
    CONSTRAINT final_history_action_version CHECK (
        (action = 'set' AND version_id IS NOT NULL) OR (action = 'unset' AND version_id IS NULL)),
    CONSTRAINT final_history_version_fk FOREIGN KEY (version_id, project_id, tab)
        REFERENCES tab_versions (id, project_id, tab) ON DELETE RESTRICT
);
CREATE INDEX final_history_current_idx ON final_history (project_id, tab, id DESC);

-- id 순서 = 기록 순서를 DB 에서도 보장: 프로젝트 행을 잠근 뒤, 이미 더 큰 id 의 기록이 있으면 거부(40001, 재시도 대상).
-- (프로젝트 잠금 전에 id 를 받은 트랜잭션이 늦게 커밋되는 경우를 막음)
CREATE FUNCTION final_history_check_order() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM 1 FROM projects WHERE id = NEW.project_id FOR UPDATE;
    IF EXISTS (SELECT 1 FROM final_history f
               WHERE f.project_id = NEW.project_id AND f.tab = NEW.tab AND f.id > NEW.id) THEN
        RAISE EXCEPTION 'final_history 기록 순서가 맞지 않습니다. 다시 시도하세요 (project_id=%, tab=%)', NEW.project_id, NEW.tab
            USING ERRCODE = 'serialization_failure';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER final_history_check_order BEFORE INSERT ON final_history
    FOR EACH ROW EXECUTE FUNCTION final_history_check_order();
CREATE TRIGGER final_history_append_only BEFORE UPDATE OR DELETE ON final_history
    FOR EACH ROW EXECUTE FUNCTION forbid_append_only_change();
CREATE TRIGGER final_history_no_truncate BEFORE TRUNCATE ON final_history
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_append_only_change();

-- version_links (다른 탭 저장본 내용을 실제 반영한 출처 1건, 추가만) -------
-- 2단계: 출처는 저장본만 (source_version_id 필수). 메모 출처 열·"정확히 하나" CHECK 는 4단계에서 추가.
-- 모든 FK 가 project_id 를 공유하므로 다른 프로젝트 저장본은 연결할 수 없다. 같은 탭은 based_on_id 로 표현한다.
CREATE TABLE version_links (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id        bigint NOT NULL REFERENCES projects (id) ON DELETE RESTRICT,
    version_id        bigint NOT NULL,
    tab               text NOT NULL,
    source_tab        text NOT NULL,
    source_version_id bigint NOT NULL,
    applied_values    jsonb NOT NULL,
    created_by        bigint NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT version_links_tab_check CHECK (tab IN ('regulatory', 'margin', 'simulation', 'requisition')),
    CONSTRAINT version_links_source_tab_check CHECK (source_tab IN ('regulatory', 'margin', 'simulation', 'requisition')),
    CONSTRAINT version_links_other_tab CHECK (source_tab <> tab),
    CONSTRAINT version_links_source_earlier CHECK (source_version_id < version_id),
    CONSTRAINT version_links_applied_values_object CHECK (jsonb_typeof(applied_values) = 'object'),
    CONSTRAINT version_links_version_source_key UNIQUE (version_id, source_version_id),
    CONSTRAINT version_links_version_fk FOREIGN KEY (version_id, project_id, tab)
        REFERENCES tab_versions (id, project_id, tab) ON DELETE RESTRICT,
    CONSTRAINT version_links_source_fk FOREIGN KEY (source_version_id, project_id, source_tab)
        REFERENCES tab_versions (id, project_id, tab) ON DELETE RESTRICT
);
CREATE INDEX version_links_source_idx ON version_links (source_version_id);

-- 반영 출처는 새 저장본과 같은 트랜잭션에서만 추가한다 (저장본 xact_id = 현재 트랜잭션).
CREATE FUNCTION version_links_same_transaction() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM tab_versions v
                   WHERE v.id = NEW.version_id AND v.xact_id = pg_current_xact_id()) THEN
        RAISE EXCEPTION 'version_links 는 새 저장본과 같은 트랜잭션에서만 추가합니다 (version_id=%)', NEW.version_id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER version_links_same_transaction BEFORE INSERT ON version_links
    FOR EACH ROW EXECUTE FUNCTION version_links_same_transaction();
CREATE TRIGGER version_links_append_only BEFORE UPDATE OR DELETE ON version_links
    FOR EACH ROW EXECUTE FUNCTION forbid_append_only_change();
CREATE TRIGGER version_links_no_truncate BEFORE TRUNCATE ON version_links
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_append_only_change();
