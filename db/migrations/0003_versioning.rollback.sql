-- 0003_versioning 되돌리기 — 테스트 DB 확인용. 저장본·최종본 이력·반영 출처를 지우므로 데이터가 있는 개발·운영 DB 에는 쓰지 않는다.
-- depends:

DROP TABLE version_links;
DROP FUNCTION version_links_same_transaction();
DROP TABLE final_history;
DROP FUNCTION final_history_check_order();
DROP TABLE tab_versions;
DROP FUNCTION tab_versions_assign();
