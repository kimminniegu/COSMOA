-- 0006_regulatory_notes 되돌리기 — 테스트 DB 확인용.
-- 메모가 하나라도 있거나, 메모를 출처로 한 반영 기록(version_links.source_note_id)이 있으면 **아무것도 바꾸지 않고 중단**한다.
--   데이터를 조용히 지우지 않는다. version_links 는 추가만 표라 메모 출처 행을 지울 수도 없다
--   → 메모 출처 반영 기록이 생긴 DB 는 이 파일로 되돌릴 수 없다 (DB 담당이 별도로 판단).
--   메모만 있고 반영 기록이 없으면, 남길지 지울지 사람이 정한 뒤(삭제는 앱의 확인 절차 또는 관리자 판단) 다시 실행한다.
-- 되돌린 뒤 version_links.source_version_id 는 다시 NOT NULL 이 된다 (위 조건 덕분에 NULL 행이 없음).
--
-- 동시 저장 보호 (2026-11-13 R2-1 보완):
--   yoyo 는 이 파일 전체를 **한 트랜잭션**으로 실행한다. 데이터 확인 **전에** 두 표를 ACCESS EXCLUSIVE 로 잠그고
--   확인부터 DROP·커밋까지 잠금을 놓지 않는다 → 확인과 DROP 사이에 새 메모·반영 기록이 끼어들 수 없다.
--   잠금 순서: version_links → regulatory_notes (한 LOCK 문, 적힌 순서대로 얻음).
--   - 먼저 시작해 아직 커밋하지 않은 저장(INSERT)이 있으면 그 트랜잭션이 끝날 때까지 기다린다.
--     그 저장이 커밋되면 확인에서 발견되어 되돌리기가 중단되고(데이터·구조 그대로), 롤백되면 되돌리기가 진행된다.
--   - 되돌리기가 잠금을 잡은 뒤 들어온 저장은 커밋까지 기다렸다가 표가 없어져 **오류로 실패**한다 (성공한 것처럼 사라지지 않음).
--   - 잠금을 lock_timeout(5초) 안에 얻지 못하면 되돌리기가 실패하고 아무것도 바뀌지 않는다 (앱 요청이 오래 막히지 않게).
--   - 교착 상태가 생기면 PostgreSQL 이 한쪽 트랜잭션을 취소한다 (40P01). 어느 쪽이 취소되어도 커밋된 데이터는 사라지지 않는다.
--   대기 중에는 두 표의 읽기도 잠깐 막힌다 — 앱 사용이 없는 시간에 실행한다.
-- depends:

SET LOCAL lock_timeout = '5s';
LOCK TABLE version_links, regulatory_notes IN ACCESS EXCLUSIVE MODE;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM version_links WHERE source_note_id IS NOT NULL) THEN
        RAISE EXCEPTION '메모를 출처로 한 반영 기록(version_links.source_note_id)이 있어 되돌리지 않습니다 (변경 없음)';
    END IF;
    IF EXISTS (SELECT 1 FROM regulatory_notes) THEN
        RAISE EXCEPTION 'regulatory_notes 에 메모가 있어 되돌리지 않습니다 (데이터를 지우지 않음, 변경 없음)';
    END IF;
END;
$$;

REVOKE UPDATE (memo, target_country, target_region, revision, updated_by, updated_at) ON regulatory_notes FROM cosmoa_app;
REVOKE SELECT, INSERT, DELETE ON regulatory_notes FROM cosmoa_app;

DROP INDEX version_links_note_idx;
ALTER TABLE version_links
    DROP CONSTRAINT version_links_note_fk,
    DROP CONSTRAINT version_links_version_note_key,
    DROP CONSTRAINT version_links_note_source_tab,
    DROP CONSTRAINT version_links_one_source;
ALTER TABLE version_links DROP COLUMN source_note_id;
ALTER TABLE version_links ALTER COLUMN source_version_id SET NOT NULL;

DROP TABLE regulatory_notes;
DROP FUNCTION regulatory_notes_stamp();
