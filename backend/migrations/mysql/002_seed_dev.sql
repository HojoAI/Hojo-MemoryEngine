-- =============================================================================
-- MemoryEngine dev seed (tenant_id = 1)
-- Re-runnable via ON DUPLICATE KEY UPDATE.
--
-- Dev API Key (Bearer): mos_devtest00001ab
--   key_prefix (first 16 chars): mos_devtest00001
-- =============================================================================

SET NAMES utf8mb4;

INSERT INTO tenant (
    id, tenant_code, name, status, deleted, create_time, update_time
) VALUES (
    1, 'default', 'Default Tenant', 'active', 0, NOW(3), NOW(3)
)
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    status = VALUES(status),
    deleted = 0,
    update_time = NOW(3);

INSERT INTO organization (
    id, tenant_id, org_code, name, status, deleted, create_time, update_time
) VALUES (
    1, 1, 'default', 'Default Organization', 'active', 0, NOW(3), NOW(3)
)
ON DUPLICATE KEY UPDATE
    name = VALUES(name),
    status = VALUES(status),
    deleted = 0,
    update_time = NOW(3);

INSERT INTO app_user (
    id, tenant_id, org_id, email, display_name, status, deleted, create_time, update_time
) VALUES (
    1, 1, 1, 'dev@memory_engine.local', 'Dev User', 'active', 0, NOW(3), NOW(3)
)
ON DUPLICATE KEY UPDATE
    display_name = VALUES(display_name),
    org_id = VALUES(org_id),
    status = VALUES(status),
    deleted = 0,
    update_time = NOW(3);

INSERT INTO api_key (
    id,
    tenant_id,
    org_id,
    user_id,
    key_prefix,
    key_hash,
    name,
    permissions_json,
    deleted,
    create_time,
    update_time
) VALUES (
    1,
    1,
    1,
    1,
    'mos_devtest00001',
    '$2b$12$K11SnR7EahZivglSeJWj1.a.ll54xVR73HE3J5m/cJrax9OKVL1CW',
    'dev-default',
    JSON_OBJECT(
        'allow',
        JSON_ARRAY('schema:*', 'data:*', 'governance:*', 'billing:read', 'billing:write')
    ),
    0,
    NOW(3),
    NOW(3)
)
ON DUPLICATE KEY UPDATE
    key_hash = VALUES(key_hash),
    permissions_json = VALUES(permissions_json),
    revoked_at = NULL,
    deleted = 0,
    update_time = NOW(3);
