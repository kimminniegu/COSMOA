-- 4단계 규제 확인사항 메모: regulatory_notes + version_links 메모 출처(source_note_id) + 앱 역할 권한
-- 근거: src/02_regulatory/regulatory.md 17장(R1), docs/data_contract.md 1-5·6장, docs/db_rules.md 2-2·5-1·8-9, docs/api_contract.md 7장
-- 번호: 0005 는 문서에 임시저장 제안 이름(0005_tab_drafts.sql)으로 잡혀 있어 비워 둔다. 이 파일은 tab_drafts 에 의존하지 않는다 (0004 다음).
-- 규제 탭 저장본(tab_versions, tab='regulatory')·임시저장(tab_drafts)과 별개다. 메모 저장에 둘 다 필요 없다.
-- 삭제 주체(작성자만 등)는 미정이라 DB 에 넣지 않는다 — 서버(R3)가 확인한다. 반영된 메모 보호는 FK(ON DELETE RESTRICT)가 한다.
-- depends: 0004_app_role_grants

-- regulatory_notes (프로젝트별 규제 확인사항 메모 1건, 메모·대상만 수정, 반영 전이면 삭제 가능) ----------------
-- note_type
--   market_lookup    성분 후보 1개 × 조회 시장 1개의 조회 기록 (상태 + 사용자가 체크한 규제 행 사본)
--   search_no_result 검색어로 두 식약처 DB 를 검색해 후보 0건 (시장별 조회가 아니므로 lookup_market·lookup_status NULL)
--   memo_only        조회 첨부 없이 메모만
-- 조회 근거 열(note_type·origin·ingredient_*·lookup_*·regulation_text)과 project_id·created_* 는 만든 뒤 바꾸지 않는다
--   (앱 역할에 UPDATE 권한 없음 + 아래 트리거가 관리 역할의 변경도 거부).
-- CHECK 는 NULL 이 섞여도 통과하지 않도록 IS [NOT] NULL·IS NOT DISTINCT FROM 으로 쓴다 (CHECK 는 NULL 결과를 통과시킴).
CREATE TABLE regulatory_notes (
    id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_id             bigint NOT NULL REFERENCES projects (id) ON DELETE RESTRICT,
    note_type              text NOT NULL,
    origin                 text,
    ingredient_name        text,
    ingredient_name_source text,
    ingredient_eng_name    text,
    ingredient_cas         text,
    lookup_market          text,
    lookup_status          text,
    lookup_source          text,
    looked_up_at           timestamptz,
    regulation_text        text,
    lookup_snapshot        jsonb,
    target_country         text,
    target_region          text,
    memo                   text,
    revision               integer NOT NULL DEFAULT 1,
    created_by             bigint NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_by             bigint NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    updated_at             timestamptz NOT NULL DEFAULT now(),

    -- 값 목록·형식
    CONSTRAINT regulatory_notes_note_type_check CHECK (note_type IN ('market_lookup', 'search_no_result', 'memo_only')),
    CONSTRAINT regulatory_notes_origin_check CHECK (origin IS NULL OR origin IN ('direct', 'file_batch')),
    CONSTRAINT regulatory_notes_name_source_check CHECK (
        ingredient_name_source IS NULL OR ingredient_name_source IN ('mfds_ingredients', 'mfds_restriction', 'user')),
    CONSTRAINT regulatory_notes_lookup_market_check CHECK (
        lookup_market IS NULL OR lookup_market IN ('KR', 'EU', 'US', 'CN', 'JP', 'ASEAN')),
    CONSTRAINT regulatory_notes_lookup_status_check CHECK (
        lookup_status IS NULL OR lookup_status IN ('found', 'no_market_record', 'not_linked')),
    -- 성분명: 1~200자, 공백만·제어 문자 불가 (원문 후보명이든 직접 입력이든)
    CONSTRAINT regulatory_notes_ingredient_name_check CHECK (
        ingredient_name IS NULL OR (ingredient_name ~ '[^[:space:]]' AND char_length(ingredient_name) <= 200
                                    AND ingredient_name !~ '[[:cntrl:]]')),
    CONSTRAINT regulatory_notes_name_pair CHECK ((ingredient_name IS NULL) = (ingredient_name_source IS NULL)),
    CONSTRAINT regulatory_notes_lookup_source_check CHECK (lookup_source IS NULL OR lookup_source ~ '[^[:space:]]'),
    CONSTRAINT regulatory_notes_regulation_text_check CHECK (regulation_text IS NULL OR regulation_text ~ '[^[:space:]]'),
    -- 원문·출처 사본: 객체, 32 KiB 이하 (DB 표현 기준의 최종 상한 — 정확한 요청 크기 검사는 서버)
    CONSTRAINT regulatory_notes_snapshot_check CHECK (
        lookup_snapshot IS NULL
        OR (jsonb_typeof(lookup_snapshot) = 'object' AND octet_length(lookup_snapshot::text) <= 32768)),
    -- 업무 대상: 국가(ISO 3166-1 alpha-2 형식 — 실제 국가 코드 목록 확인은 서버) 또는 권역 중 하나, 미지정 허용
    CONSTRAINT regulatory_notes_target_country_check CHECK (target_country IS NULL OR target_country ~ '^[A-Z]{2}$'),
    CONSTRAINT regulatory_notes_target_region_check CHECK (target_region IS NULL OR target_region IN ('EU', 'ASEAN')),
    CONSTRAINT regulatory_notes_one_target CHECK (num_nonnulls(target_country, target_region) <= 1),
    -- 담당자 메모: 0~5,000자. 저장할 때는 NULL 또는 공백 아닌 글자가 있는 값 (빈 값은 서버가 NULL 로).
    -- 제어 문자는 줄바꿈(\n·\r)·탭만 허용
    CONSTRAINT regulatory_notes_memo_check CHECK (
        memo IS NULL OR (memo ~ '[^[:space:]]' AND char_length(memo) <= 5000
                         AND memo !~ '[\x01-\x08\x0B\x0C\x0E-\x1F\x7F]')),
    CONSTRAINT regulatory_notes_revision_positive CHECK (revision >= 1),

    -- 기록 유형별 필수값·NULL (data_contract.md 1-5 유형표, regulatory.md 17-5)
    CONSTRAINT regulatory_notes_type_fields CHECK (
        (note_type = 'market_lookup'
         AND origin IS NOT NULL
         AND ingredient_name IS NOT NULL
         AND ingredient_name_source IS NOT NULL AND ingredient_name_source IN ('mfds_ingredients', 'mfds_restriction')
         AND lookup_market IS NOT NULL AND lookup_status IS NOT NULL
         AND lookup_source IS NOT NULL AND looked_up_at IS NOT NULL AND lookup_snapshot IS NOT NULL)
        OR
        (note_type = 'search_no_result'
         AND origin IS NOT NULL
         AND (ingredient_name_source IS NULL OR ingredient_name_source = 'user')
         AND ingredient_eng_name IS NULL AND ingredient_cas IS NULL
         AND lookup_market IS NULL AND lookup_status IS NULL AND regulation_text IS NULL
         AND lookup_source IS NOT NULL AND looked_up_at IS NOT NULL AND lookup_snapshot IS NOT NULL)
        OR
        (note_type = 'memo_only'
         AND origin IS NULL
         AND (ingredient_name_source IS NULL OR ingredient_name_source = 'user')
         AND ingredient_eng_name IS NULL AND ingredient_cas IS NULL
         AND lookup_market IS NULL AND lookup_status IS NULL AND regulation_text IS NULL
         AND lookup_source IS NULL AND looked_up_at IS NULL AND lookup_snapshot IS NULL
         AND memo IS NOT NULL)),
    -- 체크한 규제 행 사본은 found 일 때만 (그 외 상태·유형은 행 없이 상태만 남긴다)
    CONSTRAINT regulatory_notes_regulation_text_status CHECK (
        (regulation_text IS NOT NULL) = (lookup_status IS NOT DISTINCT FROM 'found')),
    -- 사본의 최소 구조: 시장별 조회 = selection·market·entries(배열, found 면 1개 이상·그 외 0개)·sources,
    -- 검색 0건 = search·sources (entries 없음)
    CONSTRAINT regulatory_notes_snapshot_shape CHECK (
        lookup_snapshot IS NULL
        OR (note_type = 'market_lookup'
            AND lookup_snapshot ?& ARRAY['selection', 'market', 'entries', 'sources']
            AND jsonb_typeof(lookup_snapshot -> 'sources') = 'object'
            AND CASE WHEN jsonb_typeof(lookup_snapshot -> 'entries') = 'array'
                     THEN (jsonb_array_length(lookup_snapshot -> 'entries') >= 1) = (lookup_status IS NOT DISTINCT FROM 'found')
                     ELSE false END)
        OR (note_type = 'search_no_result'
            AND lookup_snapshot ?& ARRAY['search', 'sources']
            AND NOT (lookup_snapshot ? 'entries')
            AND jsonb_typeof(lookup_snapshot -> 'sources') = 'object')),

    -- version_links 가 "같은 프로젝트 메모" 조건으로 참조하는 키
    CONSTRAINT regulatory_notes_scope_key UNIQUE (id, project_id)
);
CREATE INDEX regulatory_notes_project_idx ON regulatory_notes (project_id, updated_at DESC, id DESC);

-- 만들 때: revision = 1, 마지막 수정자 = 작성자, 시각은 DB 시각 (요청 값 무시)
-- 고칠 때: 조회 근거·프로젝트·작성자 변경 거부, revision + 1, updated_at = now()
--   (updated_by 는 서버가 세션 사용자로 넣는다 — 앱 역할이 팀 공용이라 DB 는 사람을 구분하지 못함)
CREATE FUNCTION regulatory_notes_stamp() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        NEW.revision := 1;
        NEW.updated_by := NEW.created_by;
        NEW.created_at := now();
        NEW.updated_at := NEW.created_at;
        RETURN NEW;
    END IF;
    IF (NEW.project_id, NEW.note_type, NEW.origin, NEW.ingredient_name, NEW.ingredient_name_source,
        NEW.ingredient_eng_name, NEW.ingredient_cas, NEW.lookup_market, NEW.lookup_status, NEW.lookup_source,
        NEW.looked_up_at, NEW.regulation_text, NEW.lookup_snapshot, NEW.created_by, NEW.created_at)
       IS DISTINCT FROM
       (OLD.project_id, OLD.note_type, OLD.origin, OLD.ingredient_name, OLD.ingredient_name_source,
        OLD.ingredient_eng_name, OLD.ingredient_cas, OLD.lookup_market, OLD.lookup_status, OLD.lookup_source,
        OLD.looked_up_at, OLD.regulation_text, OLD.lookup_snapshot, OLD.created_by, OLD.created_at) THEN
        RAISE EXCEPTION 'regulatory_notes 의 조회 근거·프로젝트·작성자는 바꿀 수 없습니다. 새 메모를 만드세요 (id=%)', OLD.id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    NEW.revision := OLD.revision + 1;
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER regulatory_notes_stamp BEFORE INSERT OR UPDATE ON regulatory_notes
    FOR EACH ROW EXECUTE FUNCTION regulatory_notes_stamp();

-- version_links 메모 출처 ------------------------------------------------------------------------------
-- 기존 행(저장본 출처)은 그대로: source_version_id 값이 모두 있고 source_note_id 는 NULL 로 추가되므로 아래 CHECK 를 만족한다.
-- 기존 version_links_source_fk·version_links_source_earlier 는 source_version_id 가 NULL 이면 검사하지 않는다 (MATCH SIMPLE / NULL).
-- 추가만 트리거(UPDATE·DELETE·TRUNCATE 거부)와 같은 트랜잭션 트리거는 그대로 둔다.
ALTER TABLE version_links ALTER COLUMN source_version_id DROP NOT NULL;
ALTER TABLE version_links ADD COLUMN source_note_id bigint;
ALTER TABLE version_links
    ADD CONSTRAINT version_links_one_source CHECK (num_nonnulls(source_version_id, source_note_id) = 1),
    ADD CONSTRAINT version_links_note_source_tab CHECK (source_note_id IS NULL OR source_tab = 'regulatory'),
    ADD CONSTRAINT version_links_version_note_key UNIQUE (version_id, source_note_id),
    -- 같은 프로젝트 메모만, 반영 출처로 참조된 메모는 삭제 불가
    ADD CONSTRAINT version_links_note_fk FOREIGN KEY (source_note_id, project_id)
        REFERENCES regulatory_notes (id, project_id) ON DELETE RESTRICT;
CREATE INDEX version_links_note_idx ON version_links (source_note_id) WHERE source_note_id IS NOT NULL;

-- 앱 역할(cosmoa_app) 권한 — docs/db_rules.md 8-9 "규제 메모 권한", db_admin.APP_TABLE_PRIVILEGES·APP_UPDATE_COLUMNS 와 같다 ---
-- DELETE: 반영 전 메모 실제 삭제 (R1). tab_drafts 와 함께 제한된 예외이며 다른 표에는 넓히지 않는다.
-- UPDATE: 메모·대상·revision·마지막 수정자/시각만. 조회 근거·project_id·note_type·origin·created_* 는 주지 않는다.
-- REFERENCES·TRUNCATE·TRIGGER·MAINTAIN 은 주지 않는다. version_links 권한(SELECT·INSERT, 0004)은 바꾸지 않는다.
GRANT SELECT, INSERT, DELETE ON regulatory_notes TO cosmoa_app;
GRANT UPDATE (memo, target_country, target_region, revision, updated_by, updated_at) ON regulatory_notes TO cosmoa_app;
