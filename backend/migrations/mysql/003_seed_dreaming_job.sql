-- Default LIGHT dreaming job for tenant_id=1 (dev)

SET NAMES utf8mb4;

INSERT INTO dreaming_job (
    id,
    tenant_id,
    org_id,
    job_name,
    tier,
    source,
    engine,
    task_template_code,
    config_json,
    status,
    deleted,
    create_time,
    update_time,
    created_by,
    updated_by
) VALUES (
    1,
    1,
    1,
    'default-light-scan',
    'LIGHT',
    'system',
    'spark',
    'light_v1',
    JSON_OBJECT('sample', true),
    'enabled',
    0,
    NOW(3),
    NOW(3),
    1,
    1
)
ON DUPLICATE KEY UPDATE
    job_name = VALUES(job_name),
    status = VALUES(status),
    deleted = 0,
    update_time = NOW(3);
