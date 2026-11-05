-- 0004_app_role_grants 되돌리기 — cosmoa_app 의 업무 표 권한만 회수한다. 역할(cosmoa_app·로그인 역할)은 지우지 않는다.
-- 되돌린 뒤에는 앱 역할 주소로 앱이 동작하지 않는다 (권한 없음). 데이터는 바뀌지 않는다.
-- depends:

REVOKE UPDATE (updated_at) ON customers, projects FROM cosmoa_app;
REVOKE UPDATE (password_hash) ON users FROM cosmoa_app;
REVOKE INSERT ON customers, projects, tab_versions, final_history, version_links FROM cosmoa_app;
REVOKE SELECT ON users, customers, customer_contacts, projects, project_history,
                 tab_versions, final_history, version_links FROM cosmoa_app;
REVOKE USAGE ON SCHEMA public FROM cosmoa_app;
