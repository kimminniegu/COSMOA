-- 앱용 접속 역할(cosmoa_app) 업무 표 권한 — 현재 앱 코드가 쓰는 표·열·동작만
-- 근거: docs/db_rules.md 8장. 권한 기준은 src/common/db_admin.py APP_TABLE_PRIVILEGES·APP_UPDATE_COLUMNS 와 같다 (app-role check 가 비교).
-- 역할 자체는 이 파일이 만들지 않는다 (역할은 DB 전체 객체이고 Neon 브랜치마다 따로 있음). 대상마다 먼저
--   python -m src.common.db_admin app-role init-group --target <test|dev>
-- 를 실행한다. 역할이 없거나 예상과 다르면 이 파일은 실패하고 아무 권한도 주지 않는다 (순서 확인 장치).
-- 주지 않는 것: DELETE·TRUNCATE·REFERENCES·TRIGGER 전부, users INSERT(계정 추가는 관리 명령), project_history INSERT·
-- projects 단계 열 UPDATE(단계 변경 API 미연결), customer_contacts 쓰기, yoyo 표, 스키마 CREATE. 기능을 연결하는 PR 에서 새 파일로 추가한다.
-- depends: 0003_versioning

DO $$
DECLARE
    r record;
BEGIN
    SELECT oid, rolcanlogin, rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls
      INTO r FROM pg_roles WHERE rolname = 'cosmoa_app';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'cosmoa_app 역할이 없습니다. 먼저 app-role init-group 을 실행하세요 (권한을 주지 않음)';
    END IF;
    IF r.rolcanlogin OR r.rolsuper OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication OR r.rolbypassrls
       OR shobj_description(r.oid, 'pg_authid') IS DISTINCT FROM 'cosmoa-app-group v1' THEN
        RAISE EXCEPTION 'cosmoa_app 역할이 예상(NOLOGIN, 관리 속성 없음, db_admin 표식)과 다릅니다 (권한을 주지 않음)';
    END IF;
END;
$$;

GRANT USAGE ON SCHEMA public TO cosmoa_app;

-- 조회: 로그인·세션 확인, 고객사·프로젝트·저장본·최종본·반영 출처 조회
GRANT SELECT ON users, customers, customer_contacts, projects, project_history,
                tab_versions, final_history, version_links TO cosmoa_app;

-- 생성: 고객사·프로젝트·저장본·최종본 기록·반영 출처 (id 는 IDENTITY 라 시퀀스 권한 불필요)
GRANT INSERT ON customers, projects, tab_versions, final_history, version_links TO cosmoa_app;

-- 본인 비밀번호 변경 (열 단위). email·name 등 다른 열은 바꿀 수 없다. "본인 행만" 은 서버 세션이 막는다 (DB 는 행 구분 없음)
GRANT UPDATE (password_hash) ON users TO cosmoa_app;

-- 행 잠금(FOR SHARE·FOR UPDATE, 트리거 안의 프로젝트 잠금 포함)에 필요한 최소 UPDATE 열.
-- updated_at 은 BEFORE UPDATE 트리거가 now() 로 다시 덮어써서 업무 값을 바꿀 수 없다.
GRANT UPDATE (updated_at) ON customers, projects TO cosmoa_app;
