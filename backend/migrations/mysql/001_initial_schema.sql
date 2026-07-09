-- =============================================================================
-- MemoryEngine MySQL 全量建库脚本
-- Version: 0.5.0
-- 设计文档: backend/migrations/mysql/schema-design-v0.5.md
--
-- 表数: 26（merge_rule 见 004_merge_rule.sql，全库共 27 张表）
-- 全局标准字段: deleted, create_time, update_time, created_by, updated_by
--   (permission / role_permission 省略 updated_by)
--
-- MySQL 8.0.16+：参与 FK 且含 ON DELETE SET NULL 的列不可再建 CHECK（Error 3823），
--   相关规则由应用层保证（如 retrieve_rule 显式/隐式成对、dreaming_job owner）。
-- =============================================================================

SET NAMES utf8mb4;
SET CHARACTER SET utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- 在目标库执行（如 memory_engine）：mysql -D <database> < 001_initial_schema.sql
-- 勿在此脚本内 USE/CREATE 其它库名，避免与连接库不一致。

DROP TABLE IF EXISTS idempotency_record;
DROP TABLE IF EXISTS schema_changelog;
DROP TABLE IF EXISTS writeback_audit;
DROP TABLE IF EXISTS memory_lock;
DROP TABLE IF EXISTS proposal_approval;
DROP TABLE IF EXISTS governance_proposal;
DROP TABLE IF EXISTS dreaming_job_run;
DROP TABLE IF EXISTS dreaming_job;
DROP TABLE IF EXISTS billing_invoice;
DROP TABLE IF EXISTS usage_quota;
DROP TABLE IF EXISTS billing_event;
DROP TABLE IF EXISTS api_key;
DROP TABLE IF EXISTS user_role;
DROP TABLE IF EXISTS role_permission;
DROP TABLE IF EXISTS role;
DROP TABLE IF EXISTS permission;
DROP TABLE IF EXISTS call_rule;
DROP TABLE IF EXISTS retrieve_rule;
DROP TABLE IF EXISTS parse_rule;
DROP TABLE IF EXISTS capability_registry;
DROP TABLE IF EXISTS merge_rule;
DROP TABLE IF EXISTS memory_field;
DROP TABLE IF EXISTS llm_provider;
DROP TABLE IF EXISTS secret_ref;
DROP TABLE IF EXISTS app_user;
DROP TABLE IF EXISTS organization;
DROP TABLE IF EXISTS tenant;

-- =============================================================================
-- 1. tenant
-- =============================================================================
CREATE TABLE tenant (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    tenant_code     VARCHAR(64)     NOT NULL,
    name            VARCHAR(255)    NOT NULL,
    status          ENUM('active', 'suspended', 'archived') NOT NULL DEFAULT 'active',
    settings_json   JSON            NULL,
    deleted         TINYINT(1)      NOT NULL DEFAULT 0,
    create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    created_by      BIGINT UNSIGNED NULL,
    updated_by      BIGINT UNSIGNED NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_tenant_code (tenant_code),
    KEY idx_tenant_status (status, deleted),
    KEY idx_tenant_update_time (update_time),
    CONSTRAINT chk_tenant_deleted CHECK (deleted IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='租户';

-- =============================================================================
-- 2. organization
-- =============================================================================
CREATE TABLE organization (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    org_code        VARCHAR(64)     NOT NULL,
    name            VARCHAR(255)    NOT NULL,
    status          ENUM('active', 'suspended', 'archived') NOT NULL DEFAULT 'active',
    deleted         TINYINT(1)      NOT NULL DEFAULT 0,
    create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    created_by      BIGINT UNSIGNED NULL,
    updated_by      BIGINT UNSIGNED NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_org_tenant_code (tenant_id, org_code, deleted),
    KEY idx_org_tenant_active (tenant_id, deleted, update_time),
    CONSTRAINT fk_organization_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenant (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT chk_organization_deleted CHECK (deleted IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='组织';

-- =============================================================================
-- 3. app_user
-- =============================================================================
CREATE TABLE app_user (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    tenant_id           BIGINT UNSIGNED NOT NULL,
    org_id              BIGINT UNSIGNED NOT NULL DEFAULT 0,
    supabase_user_id    VARCHAR(128)    NULL,
    email               VARCHAR(320)    NOT NULL,
    display_name        VARCHAR(255)    NULL,
    status              ENUM('active', 'disabled') NOT NULL DEFAULT 'active',
    metadata_json       JSON            NULL,
    deleted             TINYINT(1)      NOT NULL DEFAULT 0,
    create_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    update_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    created_by          BIGINT UNSIGNED NULL,
    updated_by          BIGINT UNSIGNED NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_user_tenant_email (tenant_id, email, deleted),
    KEY idx_user_supabase (supabase_user_id),
    KEY idx_user_tenant_org (tenant_id, org_id, deleted),
    KEY idx_user_update_time (update_time),
    CONSTRAINT fk_app_user_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenant (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT chk_app_user_org_id CHECK (org_id >= 0),
    CONSTRAINT chk_app_user_deleted CHECK (deleted IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='业务用户';

-- =============================================================================
-- 4. secret_ref（须在 llm_provider 之前）
-- =============================================================================
CREATE TABLE secret_ref (
    id                      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    tenant_id               BIGINT UNSIGNED NOT NULL,
    org_id                  BIGINT UNSIGNED NOT NULL DEFAULT 0,
    secret_name             VARCHAR(128)    NOT NULL,
    vault_path              VARCHAR(512)    NOT NULL,
    secret_type             ENUM('llm_api_key', 'db_password', 'webhook_token', 'other') NOT NULL,
    last_rotated_at         DATETIME(3)     NULL,
    rotation_interval_days  INT             NULL,
    deleted                 TINYINT(1)      NOT NULL DEFAULT 0,
    create_time             DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    update_time             DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    created_by              BIGINT UNSIGNED NULL,
    updated_by              BIGINT UNSIGNED NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_secret_ref_name (tenant_id, org_id, secret_name, deleted),
    KEY idx_secret_ref_tenant (tenant_id, org_id, deleted),
    KEY idx_secret_ref_update_time (update_time),
    CONSTRAINT fk_secret_ref_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenant (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT chk_secret_ref_org_id CHECK (org_id >= 0),
    CONSTRAINT chk_secret_ref_deleted CHECK (deleted IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='密钥引用元数据';

-- =============================================================================
-- 5. llm_provider
-- =============================================================================
CREATE TABLE llm_provider (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    tenant_id           BIGINT UNSIGNED NOT NULL,
    org_id              BIGINT UNSIGNED NOT NULL DEFAULT 0,
    provider_code       VARCHAR(64)     NOT NULL,
    provider_type       ENUM('openai', 'anthropic', 'volcengine', 'azure', 'custom') NOT NULL,
    base_url            VARCHAR(512)    NOT NULL,
    default_model       VARCHAR(128)    NOT NULL,
    api_key_secret_ref  BIGINT UNSIGNED NULL,
    extra_config_json   JSON            NULL,
    status              ENUM('active', 'disabled') NOT NULL DEFAULT 'active',
    deleted             TINYINT(1)      NOT NULL DEFAULT 0,
    create_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    update_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    created_by          BIGINT UNSIGNED NULL,
    updated_by          BIGINT UNSIGNED NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_llm_provider_code (tenant_id, org_id, provider_code, deleted),
    KEY idx_llm_provider_tenant (tenant_id, org_id, status, deleted),
    KEY idx_llm_provider_canal (update_time),
    CONSTRAINT fk_llm_provider_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenant (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_llm_provider_secret_ref
        FOREIGN KEY (api_key_secret_ref) REFERENCES secret_ref (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT chk_llm_provider_org_id CHECK (org_id >= 0),
    CONSTRAINT chk_llm_provider_deleted CHECK (deleted IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='LLM接入点';

-- =============================================================================
-- 6. memory_field
-- =============================================================================
CREATE TABLE memory_field (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    org_id          BIGINT UNSIGNED NOT NULL DEFAULT 0,
    name            VARCHAR(255)    NOT NULL,
    description     VARCHAR(1024)   NULL,
    value_type      ENUM('string', 'number', 'boolean', 'json', 'array', 'text') NOT NULL DEFAULT 'string',
    match_method    ENUM('OVERWRITE', 'APPEND', 'MERGE') NOT NULL DEFAULT 'OVERWRITE',
    storage_type    ENUM('KV', 'VECTOR', 'KV_AND_VECTOR') NOT NULL DEFAULT 'KV',
    version         INT UNSIGNED    NOT NULL DEFAULT 1,
    status          ENUM('active', 'deprecated') NOT NULL DEFAULT 'active',
    source          ENUM('dashboard', 'sdk', 'dreaming', 'api') NOT NULL DEFAULT 'api',
    deleted         TINYINT(1)      NOT NULL DEFAULT 0,
    create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    created_by      BIGINT UNSIGNED NULL,
    updated_by      BIGINT UNSIGNED NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_memory_field_version (tenant_id, org_id, name, version),
    KEY idx_mf_lookup (tenant_id, org_id, name, deleted, version),
    KEY idx_mf_list (tenant_id, org_id, deleted, update_time),
    KEY idx_mf_canal (update_time),
    CONSTRAINT fk_memory_field_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenant (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_memory_field_created_by
        FOREIGN KEY (created_by) REFERENCES app_user (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_memory_field_updated_by
        FOREIGN KEY (updated_by) REFERENCES app_user (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT chk_memory_field_org_id CHECK (org_id >= 0),
    CONSTRAINT chk_memory_field_deleted CHECK (deleted IN (0, 1)),
    CONSTRAINT chk_memory_field_version CHECK (version > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='记忆Schema';

-- =============================================================================
-- 7. capability_registry
-- =============================================================================
CREATE TABLE capability_registry (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    tenant_id           BIGINT UNSIGNED NOT NULL,
    org_id              BIGINT UNSIGNED NOT NULL DEFAULT 0,
    capability_name     VARCHAR(128)    NOT NULL,
    module_name         VARCHAR(255)    NOT NULL,
    service_name        VARCHAR(128)    NOT NULL,
    rule_kind           ENUM('parse', 'retrieve', 'call') NOT NULL,
    slot_name           VARCHAR(128)    NULL,
    config_json         JSON            NULL,
    llm_provider_id     BIGINT UNSIGNED NULL,
    enabled             TINYINT(1)      NOT NULL DEFAULT 1,
    last_seen_time      DATETIME(3)     NULL,
    heartbeat_version   BIGINT UNSIGNED NOT NULL DEFAULT 0,
    code_fingerprint    VARCHAR(64)     NULL,
    version             INT UNSIGNED    NOT NULL DEFAULT 1,
    owner_user_id       BIGINT UNSIGNED NULL,
    deleted             TINYINT(1)      NOT NULL DEFAULT 0,
    create_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    update_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    created_by          BIGINT UNSIGNED NULL,
    updated_by          BIGINT UNSIGNED NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_capability_version (tenant_id, org_id, capability_name, rule_kind, version),
    KEY idx_cap_lookup (tenant_id, org_id, capability_name, rule_kind, deleted),
    KEY idx_cap_heartbeat (tenant_id, org_id, deleted, last_seen_time),
    KEY idx_cap_canal (update_time),
    CONSTRAINT fk_capability_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenant (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_capability_llm_provider
        FOREIGN KEY (llm_provider_id) REFERENCES llm_provider (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_capability_owner
        FOREIGN KEY (owner_user_id) REFERENCES app_user (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_capability_created_by
        FOREIGN KEY (created_by) REFERENCES app_user (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_capability_updated_by
        FOREIGN KEY (updated_by) REFERENCES app_user (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT chk_capability_org_id CHECK (org_id >= 0),
    CONSTRAINT chk_capability_deleted CHECK (deleted IN (0, 1)),
    CONSTRAINT chk_capability_version CHECK (version > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='能力注册';

-- =============================================================================
-- 8. parse_rule
-- =============================================================================
CREATE TABLE parse_rule (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    tenant_id           BIGINT UNSIGNED NOT NULL,
    org_id              BIGINT UNSIGNED NOT NULL DEFAULT 0,
    memory_field_id     BIGINT UNSIGNED NOT NULL,
    memory_field_name   VARCHAR(255)    NOT NULL,
    rule_name           VARCHAR(128)    NOT NULL,
    capability_id       BIGINT UNSIGNED NULL,
    rule_type           ENUM('builtin', 'custom') NOT NULL DEFAULT 'custom',
    rule_config_json    JSON            NULL,
    priority            INT             NOT NULL DEFAULT 0,
    version             INT UNSIGNED    NOT NULL DEFAULT 1,
    source              ENUM('dashboard', 'sdk', 'dreaming', 'api') NOT NULL DEFAULT 'api',
    deleted             TINYINT(1)      NOT NULL DEFAULT 0,
    create_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    update_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    created_by          BIGINT UNSIGNED NULL,
    updated_by          BIGINT UNSIGNED NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_parse_rule_version (tenant_id, org_id, memory_field_id, rule_name, version),
    KEY idx_parse_rule_by_name (tenant_id, org_id, memory_field_name, deleted, version),
    KEY idx_parse_rule_capability (capability_id, deleted),
    KEY idx_parse_rule_canal (update_time),
    CONSTRAINT fk_parse_rule_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenant (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_parse_rule_memory_field
        FOREIGN KEY (memory_field_id) REFERENCES memory_field (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_parse_rule_capability
        FOREIGN KEY (capability_id) REFERENCES capability_registry (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_parse_rule_created_by
        FOREIGN KEY (created_by) REFERENCES app_user (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_parse_rule_updated_by
        FOREIGN KEY (updated_by) REFERENCES app_user (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT chk_parse_rule_org_id CHECK (org_id >= 0),
    CONSTRAINT chk_parse_rule_deleted CHECK (deleted IN (0, 1)),
    CONSTRAINT chk_parse_rule_version CHECK (version > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='解析规则';

-- =============================================================================
-- 9. retrieve_rule
-- =============================================================================
CREATE TABLE retrieve_rule (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    tenant_id           BIGINT UNSIGNED NOT NULL,
    org_id              BIGINT UNSIGNED NOT NULL DEFAULT 0,
    memory_field_id     BIGINT UNSIGNED NULL,
    memory_field_name   VARCHAR(255)    NULL,
    rule_name           VARCHAR(128)    NOT NULL,
    retrieve_method     ENUM('EXACT', 'REGEX', 'SEMANTIC', 'LLM') NOT NULL,
    capability_id       BIGINT UNSIGNED NULL,
    rule_type           ENUM('builtin', 'custom') NOT NULL DEFAULT 'custom',
    rule_config_json    JSON            NULL,
    priority            INT             NOT NULL DEFAULT 0,
    version             INT UNSIGNED    NOT NULL DEFAULT 1,
    source              ENUM('dashboard', 'sdk', 'dreaming', 'api') NOT NULL DEFAULT 'api',
    deleted             TINYINT(1)      NOT NULL DEFAULT 0,
    create_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    update_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    created_by          BIGINT UNSIGNED NULL,
    updated_by          BIGINT UNSIGNED NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_retrieve_rule_version (tenant_id, org_id, rule_name, version, memory_field_id),
    KEY idx_retrieve_by_field (tenant_id, org_id, memory_field_id, deleted, priority),
    KEY idx_retrieve_implicit (tenant_id, org_id, deleted, retrieve_method),
    KEY idx_retrieve_canal (update_time),
    CONSTRAINT fk_retrieve_rule_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenant (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_retrieve_rule_memory_field
        FOREIGN KEY (memory_field_id) REFERENCES memory_field (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_retrieve_rule_capability
        FOREIGN KEY (capability_id) REFERENCES capability_registry (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_retrieve_rule_created_by
        FOREIGN KEY (created_by) REFERENCES app_user (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_retrieve_rule_updated_by
        FOREIGN KEY (updated_by) REFERENCES app_user (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT chk_retrieve_rule_org_id CHECK (org_id >= 0),
    CONSTRAINT chk_retrieve_rule_deleted CHECK (deleted IN (0, 1)),
    CONSTRAINT chk_retrieve_rule_version CHECK (version > 0)
    -- 显式/隐式检索成对约束由应用层保证（memory_field_id 参与 FK ON DELETE SET NULL，
    -- MySQL 3823 不允许同列再建 CHECK）
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='检索规则';

-- =============================================================================
-- 10. call_rule
-- =============================================================================
CREATE TABLE call_rule (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    tenant_id           BIGINT UNSIGNED NOT NULL,
    org_id              BIGINT UNSIGNED NOT NULL DEFAULT 0,
    memory_field_id     BIGINT UNSIGNED NOT NULL,
    memory_field_name   VARCHAR(255)    NOT NULL,
    rule_name           VARCHAR(128)    NOT NULL,
    slot_name           VARCHAR(128)    NOT NULL,
    capability_id       BIGINT UNSIGNED NULL,
    rule_type           ENUM('builtin', 'custom') NOT NULL DEFAULT 'custom',
    rule_config_json    JSON            NULL,
    version             INT UNSIGNED    NOT NULL DEFAULT 1,
    source              ENUM('dashboard', 'sdk', 'dreaming', 'api') NOT NULL DEFAULT 'api',
    deleted             TINYINT(1)      NOT NULL DEFAULT 0,
    create_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    update_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    created_by          BIGINT UNSIGNED NULL,
    updated_by          BIGINT UNSIGNED NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_call_rule_version (tenant_id, org_id, memory_field_id, slot_name, version),
    KEY idx_call_rule_by_field (tenant_id, org_id, memory_field_id, deleted),
    KEY idx_call_rule_slot (tenant_id, org_id, slot_name, deleted),
    KEY idx_call_rule_canal (update_time),
    CONSTRAINT fk_call_rule_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenant (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_call_rule_memory_field
        FOREIGN KEY (memory_field_id) REFERENCES memory_field (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_call_rule_capability
        FOREIGN KEY (capability_id) REFERENCES capability_registry (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_call_rule_created_by
        FOREIGN KEY (created_by) REFERENCES app_user (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_call_rule_updated_by
        FOREIGN KEY (updated_by) REFERENCES app_user (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT chk_call_rule_org_id CHECK (org_id >= 0),
    CONSTRAINT chk_call_rule_deleted CHECK (deleted IN (0, 1)),
    CONSTRAINT chk_call_rule_version CHECK (version > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='引用规则';

-- =============================================================================
-- 11. permission（全局字典，无 tenant_id）
-- =============================================================================
CREATE TABLE permission (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    permission_code     VARCHAR(64)     NOT NULL,
    permission_name     VARCHAR(128)    NOT NULL,
    category            ENUM('schema', 'data', 'runtime', 'debug', 'billing', 'governance', 'dashboard') NOT NULL,
    description         VARCHAR(512)    NULL,
    deleted             TINYINT(1)      NOT NULL DEFAULT 0,
    create_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    update_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    created_by          BIGINT UNSIGNED NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_permission_code (permission_code),
    KEY idx_permission_category (category, deleted),
    CONSTRAINT chk_permission_deleted CHECK (deleted IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='权限字典';

-- =============================================================================
-- 12. role（tenant_id=0 为系统角色，不建 FK）
-- =============================================================================
CREATE TABLE role (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    tenant_id       BIGINT UNSIGNED NOT NULL DEFAULT 0,
    role_code       VARCHAR(64)     NOT NULL,
    role_name       VARCHAR(128)    NOT NULL,
    role_type       ENUM('system', 'custom') NOT NULL DEFAULT 'custom',
    description     VARCHAR(512)    NULL,
    deleted         TINYINT(1)      NOT NULL DEFAULT 0,
    create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    created_by      BIGINT UNSIGNED NULL,
    updated_by      BIGINT UNSIGNED NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_role_tenant_code (tenant_id, role_code, deleted),
    KEY idx_role_tenant_active (tenant_id, deleted),
    KEY idx_role_update_time (update_time),
    CONSTRAINT chk_role_deleted CHECK (deleted IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='角色';

-- =============================================================================
-- 13. role_permission
-- =============================================================================
CREATE TABLE role_permission (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    role_id         BIGINT UNSIGNED NOT NULL,
    permission_id   BIGINT UNSIGNED NOT NULL,
    deleted         TINYINT(1)      NOT NULL DEFAULT 0,
    create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    created_by      BIGINT UNSIGNED NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_role_permission (role_id, permission_id, deleted),
    KEY idx_rp_permission (permission_id, deleted),
    KEY idx_rp_update_time (update_time),
    CONSTRAINT fk_role_permission_role
        FOREIGN KEY (role_id) REFERENCES role (id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_role_permission_permission
        FOREIGN KEY (permission_id) REFERENCES permission (id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT chk_role_permission_deleted CHECK (deleted IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='角色权限';

-- =============================================================================
-- 14. user_role
-- =============================================================================
CREATE TABLE user_role (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    org_id          BIGINT UNSIGNED NOT NULL DEFAULT 0,
    user_id         BIGINT UNSIGNED NOT NULL,
    role_id         BIGINT UNSIGNED NOT NULL,
    expires_at      DATETIME(3)     NULL,
    deleted         TINYINT(1)      NOT NULL DEFAULT 0,
    create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    created_by      BIGINT UNSIGNED NULL,
    updated_by      BIGINT UNSIGNED NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_user_role (user_id, org_id, role_id, deleted),
    KEY idx_ur_tenant_org (tenant_id, org_id, deleted),
    KEY idx_ur_role (role_id, deleted),
    KEY idx_ur_update_time (update_time),
    CONSTRAINT fk_user_role_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenant (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_user_role_user
        FOREIGN KEY (user_id) REFERENCES app_user (id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_user_role_role
        FOREIGN KEY (role_id) REFERENCES role (id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT chk_user_role_org_id CHECK (org_id >= 0),
    CONSTRAINT chk_user_role_deleted CHECK (deleted IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户角色';

-- =============================================================================
-- 15. api_key
-- =============================================================================
CREATE TABLE api_key (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    tenant_id           BIGINT UNSIGNED NOT NULL,
    org_id              BIGINT UNSIGNED NOT NULL DEFAULT 0,
    user_id             BIGINT UNSIGNED NOT NULL,
    key_prefix          VARCHAR(16)     NOT NULL,
    key_hash            VARCHAR(128)    NOT NULL,
    name                VARCHAR(128)    NOT NULL DEFAULT 'default',
    scope_org_ids_json  JSON            NULL,
    permissions_json    JSON            NULL,
    expires_at          DATETIME(3)     NULL,
    revoked_at          DATETIME(3)     NULL,
    last_used_at        DATETIME(3)     NULL,
    deleted             TINYINT(1)      NOT NULL DEFAULT 0,
    create_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    update_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    created_by          BIGINT UNSIGNED NULL,
    updated_by          BIGINT UNSIGNED NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_api_key_prefix (key_prefix),
    KEY idx_api_key_user_active (user_id, deleted, revoked_at),
    KEY idx_api_key_tenant (tenant_id, org_id, deleted),
    KEY idx_api_key_update_time (update_time),
    CONSTRAINT fk_api_key_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenant (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_api_key_user
        FOREIGN KEY (user_id) REFERENCES app_user (id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT chk_api_key_org_id CHECK (org_id >= 0),
    CONSTRAINT chk_api_key_deleted CHECK (deleted IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='API Key';

-- =============================================================================
-- 16. billing_event
-- =============================================================================
CREATE TABLE billing_event (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    event_uuid          CHAR(36)        NOT NULL,
    tenant_id           BIGINT UNSIGNED NOT NULL,
    org_id              BIGINT UNSIGNED NOT NULL DEFAULT 0,
    user_id             BIGINT UNSIGNED NOT NULL,
    api_key_id          BIGINT UNSIGNED NULL,
    event_type          ENUM('llm_completion', 'embedding', 'retrieve', 'parse', 'call') NOT NULL,
    llm_provider_id     BIGINT UNSIGNED NULL,
    model_name          VARCHAR(128)    NULL,
    prompt_tokens       INT UNSIGNED    NOT NULL DEFAULT 0,
    completion_tokens   INT UNSIGNED    NOT NULL DEFAULT 0,
    total_tokens        INT UNSIGNED    NOT NULL DEFAULT 0,
    cost_amount         DECIMAL(12, 6)  NOT NULL DEFAULT 0.000000,
    currency            CHAR(3)         NOT NULL DEFAULT 'CNY',
    status              ENUM('pending', 'processed', 'failed') NOT NULL DEFAULT 'pending',
    processed_at        DATETIME(3)     NULL,
    failure_reason      VARCHAR(512)    NULL,
    trace_id            VARCHAR(64)     NULL,
    occurred_at         DATETIME(3)     NOT NULL,
    deleted             TINYINT(1)      NOT NULL DEFAULT 0,
    create_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    update_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    created_by          BIGINT UNSIGNED NULL,
    updated_by          BIGINT UNSIGNED NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_billing_event_uuid (event_uuid),
    KEY idx_billing_pending (status, deleted, create_time),
    KEY idx_billing_tenant_user (tenant_id, org_id, user_id, occurred_at),
    KEY idx_billing_trace (trace_id),
    KEY idx_billing_update_time (update_time),
    CONSTRAINT fk_billing_event_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenant (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_billing_event_user
        FOREIGN KEY (user_id) REFERENCES app_user (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_billing_event_api_key
        FOREIGN KEY (api_key_id) REFERENCES api_key (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_billing_event_llm_provider
        FOREIGN KEY (llm_provider_id) REFERENCES llm_provider (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT chk_billing_event_org_id CHECK (org_id >= 0),
    CONSTRAINT chk_billing_event_deleted CHECK (deleted IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='计费事件';

-- =============================================================================
-- 17. usage_quota
-- =============================================================================
CREATE TABLE usage_quota (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    org_id          BIGINT UNSIGNED NOT NULL DEFAULT 0,
    scope           ENUM('tenant', 'org', 'user') NOT NULL,
    target_id       BIGINT UNSIGNED NOT NULL,
    quota_type      ENUM('tokens', 'cost', 'requests') NOT NULL,
    period          ENUM('daily', 'monthly', 'total') NOT NULL,
    period_tz       VARCHAR(64)     NOT NULL DEFAULT 'Asia/Shanghai',
    quota_limit     DECIMAL(20, 6)  NOT NULL,
    quota_used      DECIMAL(20, 6)  NOT NULL DEFAULT 0.000000,
    period_start    DATETIME(3)     NOT NULL,
    period_end      DATETIME(3)     NOT NULL,
    status          ENUM('active', 'exceeded', 'disabled') NOT NULL DEFAULT 'active',
    deleted         TINYINT(1)      NOT NULL DEFAULT 0,
    create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    created_by      BIGINT UNSIGNED NULL,
    updated_by      BIGINT UNSIGNED NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_usage_quota_scope (tenant_id, scope, target_id, quota_type, period, period_start, deleted),
    KEY idx_usage_quota_tenant (tenant_id, org_id, deleted, update_time),
    CONSTRAINT fk_usage_quota_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenant (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT chk_usage_quota_org_id CHECK (org_id >= 0),
    CONSTRAINT chk_usage_quota_deleted CHECK (deleted IN (0, 1)),
    CONSTRAINT chk_usage_quota_limit CHECK (quota_limit >= 0),
    CONSTRAINT chk_usage_quota_used CHECK (quota_used >= 0),
    CONSTRAINT chk_usage_quota_period CHECK (period_end > period_start)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用量额度';

-- =============================================================================
-- 18. billing_invoice
-- =============================================================================
CREATE TABLE billing_invoice (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    invoice_uuid    CHAR(36)        NOT NULL,
    tenant_id       BIGINT UNSIGNED NOT NULL,
    org_id          BIGINT UNSIGNED NOT NULL DEFAULT 0,
    period_month    CHAR(7)         NOT NULL,
    period_tz       VARCHAR(64)     NOT NULL DEFAULT 'Asia/Shanghai',
    total_tokens    BIGINT UNSIGNED NOT NULL DEFAULT 0,
    total_amount    DECIMAL(20, 6)  NOT NULL DEFAULT 0.000000,
    currency        CHAR(3)         NOT NULL DEFAULT 'CNY',
    status          ENUM('draft', 'issued', 'paid', 'overdue', 'void') NOT NULL DEFAULT 'draft',
    details_json    JSON            NULL,
    issued_at       DATETIME(3)     NULL,
    paid_at         DATETIME(3)     NULL,
    deleted         TINYINT(1)      NOT NULL DEFAULT 0,
    create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    created_by      BIGINT UNSIGNED NULL,
    updated_by      BIGINT UNSIGNED NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_billing_invoice_uuid (invoice_uuid),
    UNIQUE KEY uk_billing_invoice_period (tenant_id, org_id, period_month, deleted),
    KEY idx_invoice_tenant_month (tenant_id, org_id, period_month, deleted),
    KEY idx_invoice_update_time (update_time),
    CONSTRAINT fk_billing_invoice_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenant (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT chk_billing_invoice_org_id CHECK (org_id >= 0),
    CONSTRAINT chk_billing_invoice_deleted CHECK (deleted IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='费用账单';

-- =============================================================================
-- 19. dreaming_job
-- =============================================================================
CREATE TABLE dreaming_job (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    tenant_id           BIGINT UNSIGNED NOT NULL,
    org_id              BIGINT UNSIGNED NOT NULL DEFAULT 0,
    job_name            VARCHAR(255)    NOT NULL,
    tier                ENUM('LIGHT', 'REM', 'DEEP') NOT NULL,
    source              ENUM('system', 'user') NOT NULL DEFAULT 'system',
    owner_user_id       BIGINT UNSIGNED NULL,
    engine              ENUM('spark', 'flink') NOT NULL,
    task_template_code  VARCHAR(64)     NULL,
    config_json         JSON            NULL,
    cron_expr           VARCHAR(64)     NULL,
    status              ENUM('enabled', 'paused', 'disabled') NOT NULL DEFAULT 'enabled',
    deleted             TINYINT(1)      NOT NULL DEFAULT 0,
    create_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    update_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    created_by          BIGINT UNSIGNED NULL,
    updated_by          BIGINT UNSIGNED NULL,
    PRIMARY KEY (id),
    KEY idx_dreaming_job_schedule (tenant_id, org_id, status, deleted, tier),
    KEY idx_dreaming_job_canal (update_time),
    CONSTRAINT fk_dreaming_job_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenant (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_dreaming_job_owner
        FOREIGN KEY (owner_user_id) REFERENCES app_user (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_dreaming_job_created_by
        FOREIGN KEY (created_by) REFERENCES app_user (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_dreaming_job_updated_by
        FOREIGN KEY (updated_by) REFERENCES app_user (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT chk_dreaming_job_org_id CHECK (org_id >= 0),
    CONSTRAINT chk_dreaming_job_deleted CHECK (deleted IN (0, 1))
    -- source=user 时 owner_user_id 必填：应用层校验（owner_user_id 有 FK SET NULL，不可建 CHECK，MySQL 3823）
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Dreaming任务';

-- =============================================================================
-- 20. dreaming_job_run
-- =============================================================================
CREATE TABLE dreaming_job_run (
    id                      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    run_uuid                CHAR(36)        NOT NULL,
    job_id                  BIGINT UNSIGNED NOT NULL,
    tenant_id               BIGINT UNSIGNED NOT NULL,
    org_id                  BIGINT UNSIGNED NOT NULL DEFAULT 0,
    temporal_workflow_id    VARCHAR(255)    NOT NULL,
    temporal_run_id         VARCHAR(255)    NOT NULL,
    trigger_type            ENUM('schedule', 'event', 'manual') NOT NULL,
    triggered_by_user_id    BIGINT UNSIGNED NULL,
    status                  ENUM('queued', 'running', 'succeeded', 'failed', 'cancelled', 'timed_out') NOT NULL DEFAULT 'queued',
    started_at              DATETIME(3)     NULL,
    finished_at             DATETIME(3)     NULL,
    stats_json              JSON            NULL,
    failure_reason          VARCHAR(1024)   NULL,
    deleted                 TINYINT(1)      NOT NULL DEFAULT 0,
    create_time             DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    update_time             DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    created_by              BIGINT UNSIGNED NULL,
    updated_by              BIGINT UNSIGNED NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_dreaming_run_uuid (run_uuid),
    UNIQUE KEY uk_dreaming_run_temporal (temporal_workflow_id, temporal_run_id),
    KEY idx_djr_job_status (job_id, status, started_at),
    KEY idx_djr_tenant (tenant_id, org_id, status, deleted),
    KEY idx_djr_update_time (update_time),
    CONSTRAINT fk_dreaming_job_run_job
        FOREIGN KEY (job_id) REFERENCES dreaming_job (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_dreaming_job_run_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenant (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_dreaming_job_run_triggered_by
        FOREIGN KEY (triggered_by_user_id) REFERENCES app_user (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT chk_dreaming_job_run_org_id CHECK (org_id >= 0),
    CONSTRAINT chk_dreaming_job_run_deleted CHECK (deleted IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Dreaming运行';

-- =============================================================================
-- 21. governance_proposal
-- =============================================================================
CREATE TABLE governance_proposal (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    proposal_uuid       CHAR(36)        NOT NULL,
    tenant_id           BIGINT UNSIGNED NOT NULL,
    org_id              BIGINT UNSIGNED NOT NULL DEFAULT 0,
    job_run_id          BIGINT UNSIGNED NULL,
    target_type         ENUM('memory_field', 'memory_data', 'parse_rule', 'retrieve_rule', 'call_rule') NOT NULL,
    target_ref_json     JSON            NOT NULL,
    action              ENUM('create', 'update', 'delete', 'merge', 'freeze', 'unfreeze') NOT NULL,
    payload_json        JSON            NOT NULL,
    evidence_json       JSON            NULL,
    confidence_score    DECIMAL(5, 4)   NOT NULL DEFAULT 0.0000,
    impact_scope_json   JSON            NULL,
    risk_level          ENUM('low', 'medium', 'high') NOT NULL DEFAULT 'medium',
    status              ENUM('draft', 'pending_review', 'approved', 'rejected', 'applied', 'rolled_back', 'expired') NOT NULL DEFAULT 'draft',
    auto_apply          TINYINT(1)      NOT NULL DEFAULT 0,
    applied_at          DATETIME(3)     NULL,
    rolled_back_at      DATETIME(3)     NULL,
    expires_at          DATETIME(3)     NULL,
    deleted             TINYINT(1)      NOT NULL DEFAULT 0,
    create_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    update_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    created_by          BIGINT UNSIGNED NULL,
    updated_by          BIGINT UNSIGNED NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_governance_proposal_uuid (proposal_uuid),
    KEY idx_proposal_review (tenant_id, org_id, status, risk_level, create_time),
    KEY idx_proposal_auto_apply (tenant_id, org_id, auto_apply, risk_level, status, deleted),
    KEY idx_proposal_job_run (job_run_id),
    KEY idx_proposal_update_time (update_time),
    CONSTRAINT fk_governance_proposal_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenant (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_governance_proposal_job_run
        FOREIGN KEY (job_run_id) REFERENCES dreaming_job_run (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT chk_governance_proposal_org_id CHECK (org_id >= 0),
    CONSTRAINT chk_governance_proposal_deleted CHECK (deleted IN (0, 1)),
    CONSTRAINT chk_governance_proposal_confidence CHECK (confidence_score >= 0 AND confidence_score <= 1),
    CONSTRAINT chk_governance_proposal_auto_apply CHECK (
        (auto_apply = 1 AND risk_level = 'low') OR (auto_apply = 0)
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='治理提案';

-- =============================================================================
-- 22. proposal_approval
-- =============================================================================
CREATE TABLE proposal_approval (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    proposal_id         BIGINT UNSIGNED NOT NULL,
    approval_level      INT             NOT NULL DEFAULT 1,
    approver_user_id    BIGINT UNSIGNED NOT NULL,
    decision            ENUM('approve', 'reject', 'request_changes') NOT NULL,
    comment             VARCHAR(1024)   NULL,
    decided_at          DATETIME(3)     NOT NULL,
    deleted             TINYINT(1)      NOT NULL DEFAULT 0,
    create_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    update_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    created_by          BIGINT UNSIGNED NULL,
    updated_by          BIGINT UNSIGNED NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_proposal_approval (proposal_id, approval_level, approver_user_id, deleted),
    KEY idx_approval_proposal (proposal_id, deleted, create_time),
    KEY idx_approval_update_time (update_time),
    CONSTRAINT fk_proposal_approval_proposal
        FOREIGN KEY (proposal_id) REFERENCES governance_proposal (id)
        ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_proposal_approval_user
        FOREIGN KEY (approver_user_id) REFERENCES app_user (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT chk_proposal_approval_deleted CHECK (deleted IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='提案审批';

-- =============================================================================
-- 23. memory_lock
-- =============================================================================
CREATE TABLE memory_lock (
    id                      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    tenant_id               BIGINT UNSIGNED NOT NULL,
    org_id                  BIGINT UNSIGNED NOT NULL DEFAULT 0,
    lock_type               ENUM('schema_readonly', 'schema_freeze', 'data_readonly', 'data_freeze') NOT NULL,
    target_type             ENUM('memory_field', 'memory_data') NOT NULL,
    target_ref_json         JSON            NOT NULL,
    locked_by_user_id       BIGINT UNSIGNED NOT NULL,
    reason                  VARCHAR(512)    NULL,
    triggered_by_proposal_id BIGINT UNSIGNED NULL,
    expires_at              DATETIME(3)     NULL,
    released_at             DATETIME(3)     NULL,
    deleted                 TINYINT(1)      NOT NULL DEFAULT 0,
    create_time             DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    update_time             DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    created_by              BIGINT UNSIGNED NULL,
    updated_by              BIGINT UNSIGNED NULL,
    PRIMARY KEY (id),
    KEY idx_memory_lock_active (tenant_id, org_id, target_type, deleted, expires_at),
    KEY idx_memory_lock_update_time (update_time),
    CONSTRAINT fk_memory_lock_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenant (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_memory_lock_user
        FOREIGN KEY (locked_by_user_id) REFERENCES app_user (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_memory_lock_proposal
        FOREIGN KEY (triggered_by_proposal_id) REFERENCES governance_proposal (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT chk_memory_lock_org_id CHECK (org_id >= 0),
    CONSTRAINT chk_memory_lock_deleted CHECK (deleted IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='记忆锁';

-- =============================================================================
-- 24. writeback_audit
-- =============================================================================
CREATE TABLE writeback_audit (
    id                      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    proposal_id             BIGINT UNSIGNED NOT NULL,
    tenant_id               BIGINT UNSIGNED NOT NULL,
    org_id                  BIGINT UNSIGNED NOT NULL DEFAULT 0,
    api_endpoint            VARCHAR(255)    NOT NULL,
    target_type             ENUM('memory_field', 'memory_data', 'parse_rule', 'retrieve_rule', 'call_rule') NOT NULL,
    target_id_before        BIGINT UNSIGNED NULL,
    target_id_after         BIGINT UNSIGNED NULL,
    version_before          INT UNSIGNED    NULL,
    version_after           INT UNSIGNED    NULL,
    request_payload_json    JSON            NULL,
    response_payload_json   JSON            NULL,
    status                  ENUM('succeeded', 'failed', 'rolled_back') NOT NULL,
    rollback_deadline       DATETIME(3)     NULL,
    rolled_back_at          DATETIME(3)     NULL,
    rollback_reason         VARCHAR(512)    NULL,
    deleted                 TINYINT(1)      NOT NULL DEFAULT 0,
    create_time             DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    update_time             DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    created_by              BIGINT UNSIGNED NULL,
    updated_by              BIGINT UNSIGNED NULL,
    PRIMARY KEY (id),
    KEY idx_writeback_proposal (proposal_id, deleted),
    KEY idx_writeback_rollback (status, rollback_deadline, deleted),
    KEY idx_writeback_tenant (tenant_id, org_id, status, create_time),
    KEY idx_writeback_update_time (update_time),
    CONSTRAINT fk_writeback_audit_proposal
        FOREIGN KEY (proposal_id) REFERENCES governance_proposal (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_writeback_audit_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenant (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT chk_writeback_audit_org_id CHECK (org_id >= 0),
    CONSTRAINT chk_writeback_audit_deleted CHECK (deleted IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='回写审计';

-- =============================================================================
-- 25. schema_changelog
-- =============================================================================
CREATE TABLE schema_changelog (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    tenant_id           BIGINT UNSIGNED NOT NULL,
    org_id              BIGINT UNSIGNED NOT NULL DEFAULT 0,
    change_uuid         CHAR(36)        NOT NULL,
    target_type         ENUM('memory_field', 'parse_rule', 'retrieve_rule', 'call_rule', 'capability_registry') NOT NULL,
    target_id           BIGINT UNSIGNED NOT NULL,
    target_name         VARCHAR(255)    NULL,
    change_action       ENUM('create', 'update', 'delete', 'version_bump') NOT NULL,
    version_before      INT UNSIGNED    NULL,
    version_after       INT UNSIGNED    NULL,
    diff_json           JSON            NULL,
    source              ENUM('api', 'dashboard', 'sdk', 'dreaming', 'migration') NOT NULL,
    operator_user_id    BIGINT UNSIGNED NULL,
    trace_id            VARCHAR(64)     NULL,
    deleted             TINYINT(1)      NOT NULL DEFAULT 0,
    create_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    update_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    created_by          BIGINT UNSIGNED NULL,
    updated_by          BIGINT UNSIGNED NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_schema_changelog_uuid (change_uuid),
    KEY idx_changelog_target (tenant_id, org_id, target_type, target_id, create_time),
    KEY idx_changelog_update_time (update_time),
    CONSTRAINT fk_schema_changelog_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenant (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_schema_changelog_operator
        FOREIGN KEY (operator_user_id) REFERENCES app_user (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT chk_schema_changelog_org_id CHECK (org_id >= 0),
    CONSTRAINT chk_schema_changelog_deleted CHECK (deleted IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Schema变更审计';

-- =============================================================================
-- 26. idempotency_record
-- =============================================================================
CREATE TABLE idempotency_record (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    tenant_id           BIGINT UNSIGNED NOT NULL,
    org_id              BIGINT UNSIGNED NOT NULL DEFAULT 0,
    idempotency_key     VARCHAR(128)    NOT NULL,
    scope               VARCHAR(64)     NOT NULL,
    request_hash        CHAR(64)        NOT NULL,
    response_status     INT             NOT NULL,
    response_body_json  JSON            NULL,
    expires_at          DATETIME(3)     NOT NULL,
    deleted             TINYINT(1)      NOT NULL DEFAULT 0,
    create_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    update_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
    created_by          BIGINT UNSIGNED NULL,
    updated_by          BIGINT UNSIGNED NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_idempotency (tenant_id, scope, idempotency_key),
    KEY idx_idem_expire (expires_at),
    KEY idx_idem_update_time (update_time),
    CONSTRAINT fk_idempotency_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenant (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT chk_idempotency_org_id CHECK (org_id >= 0),
    CONSTRAINT chk_idempotency_deleted CHECK (deleted IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='写API幂等';

-- =============================================================================
-- Seed: permissions (v0.5)
-- =============================================================================
INSERT INTO permission (permission_code, permission_name, category, description, deleted) VALUES
    ('schema:read',            'Schema读',           'schema',     '查询memory field与规则', 0),
    ('schema:write',           'Schema写',           'schema',     '创建/修改/删除schema', 0),
    ('data:read',              '记忆数据读',         'data',       '查询memory data', 0),
    ('data:write',             '记忆数据写',         'data',       '写入/更新/删除memory data', 0),
    ('parse:execute',          '解析执行',           'runtime',    'Data.parse', 0),
    ('retrieve:execute',       '检索执行',           'runtime',    'Data.get检索', 0),
    ('call:execute',           '引用执行',           'runtime',    'Data.call', 0),
    ('debug:list',             '调试列表',           'debug',      'list类debug API', 0),
    ('billing:read',           '计费查询',           'billing',    'token明细/账单查询', 0),
    ('billing:manage',         '计费管理',           'billing',    '额度与账单管理', 0),
    ('governance:approve',     '治理审批',           'governance', '审批治理提案', 0),
    ('governance:apply',       '治理应用',           'governance', '执行治理回写', 0),
    ('governance:lock',        '治理加锁',           'governance', '记忆锁管理', 0),
    ('dashboard:user_manage',  'Dashboard用户管理',  'dashboard',  '用户增删改查', 0),
    ('dashboard:tenant_manage','Dashboard租户管理',  'dashboard',  '租户配置管理', 0)
AS new_row
ON DUPLICATE KEY UPDATE
    permission_name = new_row.permission_name,
    category = new_row.category,
    description = new_row.description,
    deleted = new_row.deleted,
    update_time = CURRENT_TIMESTAMP(3);

-- =============================================================================
-- Seed: system roles (tenant_id=0)
-- =============================================================================
INSERT INTO role (tenant_id, role_code, role_name, role_type, description, deleted) VALUES
    (0, 'tenant_admin',         '租户管理员',   'system', '租户最高权限', 0),
    (0, 'org_admin',            '组织管理员',   'system', '组织级管理', 0),
    (0, 'developer',            '开发者',       'system', 'Schema与数据读写', 0),
    (0, 'viewer',               '只读用户',     'system', '只读访问', 0),
    (0, 'billing_admin',        '计费管理员',   'system', '计费与账单', 0),
    (0, 'governance_reviewer',  '治理审核员',   'system', '治理提案审批', 0)
AS new_row
ON DUPLICATE KEY UPDATE
    role_name = new_row.role_name,
    description = new_row.description,
    update_time = CURRENT_TIMESTAMP(3);

SET FOREIGN_KEY_CHECKS = 1;

-- =============================================================================
-- v0.5.0: 27 tables (26 + merge_rule) | 64 FK | 26 UNIQUE | 66 indexes | 59 CHECK
-- =============================================================================
