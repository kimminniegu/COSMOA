-- 0001_core 되돌리기 — 테스트 DB 에서 되돌리기·재적용 확인용. 데이터가 있는 개발·운영 DB 에는 쓰지 않는다.
-- depends:

DROP TABLE project_history;
DROP TABLE projects;
DROP TABLE customer_contacts;
DROP TABLE customers;
DROP TABLE users;
DROP FUNCTION projects_require_history();
DROP FUNCTION forbid_delete_archive_instead();
DROP FUNCTION forbid_append_only_change();
DROP FUNCTION set_updated_at();
