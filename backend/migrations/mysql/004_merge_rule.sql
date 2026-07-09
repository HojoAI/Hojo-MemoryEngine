-- merge_rule: LLM config for match_method=MERGE (MERGE is the LLM fusion write strategy).

CREATE TABLE IF NOT EXISTS merge_rule (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    tenant_id           BIGINT UNSIGNED NOT NULL,
    org_id              BIGINT UNSIGNED NOT NULL DEFAULT 0,
    memory_field_id     BIGINT UNSIGNED NOT NULL,
    memory_field_name   VARCHAR(255)    NOT NULL,
    rule_name           VARCHAR(128)    NOT NULL,
    capability_id       BIGINT UNSIGNED NULL,
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
    UNIQUE KEY uk_merge_rule_version (tenant_id, org_id, memory_field_id, rule_name, version),
    KEY idx_merge_rule_by_name (tenant_id, org_id, memory_field_name, deleted, version),
    KEY idx_merge_rule_canal (update_time),
    CONSTRAINT fk_merge_rule_tenant
        FOREIGN KEY (tenant_id) REFERENCES tenant (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_merge_rule_memory_field
        FOREIGN KEY (memory_field_id) REFERENCES memory_field (id)
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_merge_rule_created_by
        FOREIGN KEY (created_by) REFERENCES app_user (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_merge_rule_updated_by
        FOREIGN KEY (updated_by) REFERENCES app_user (id)
        ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT chk_merge_rule_org_id CHECK (org_id >= 0),
    CONSTRAINT chk_merge_rule_deleted CHECK (deleted IN (0, 1)),
    CONSTRAINT chk_merge_rule_version CHECK (version > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='MERGE 模式 LLM 融合规则';
