-- P0/P1: structured memory schema policies and permissions.
-- MongoDB collections (memory_source_event, memory_claim, memory_bundle_audit)
-- are created lazily by the application and therefore need no DDL here.

ALTER TABLE memory_field
    ADD COLUMN json_schema JSON NULL AFTER source,
    ADD COLUMN schema_version VARCHAR(32) NOT NULL DEFAULT '1.0' AFTER json_schema,
    ADD COLUMN update_policy_json JSON NULL AFTER schema_version,
    ADD COLUMN access_policy_json JSON NULL AFTER update_policy_json,
    ADD COLUMN retrieval_policy_json JSON NULL AFTER access_policy_json;

INSERT INTO permission (permission_code, permission_name, category, description)
VALUES
    ('memory:claim:write', '写入原子记忆', 'data', '写入结构化 Memory Claim'),
    ('memory:claim:review', '审核原子记忆', 'data', '审核、撤回或解决冲突 Claim'),
    ('memory:retrieve:self', '检索同场记忆', 'data', '使用 self 范围检索'),
    ('memory:retrieve:cross', '检索跨场记忆', 'data', '使用 cross/all 范围检索'),
    ('memory:retrieve:sensitive', '检索敏感记忆', 'data', '允许敏感 Claim 进入候选集'),
    ('memory:policy:manage', '管理记忆策略', 'data', '管理 Claim 使用权限及更新策略')
ON DUPLICATE KEY UPDATE
    permission_name = VALUES(permission_name),
    description = VALUES(description),
    deleted = 0,
    update_time = NOW(3);
