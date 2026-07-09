package com.memoryengine;

import java.util.Objects;

/** Client configuration (env vars or programmatic). */
public final class MemoryEngineConfig {

  private final String baseUrl;
  private final String apiKey;
  private final String apiKeyPrefixExplicit;
  private final long tenantId;
  private final long orgId;
  private final Long userId;

  private MemoryEngineConfig(Builder builder) {
    this.baseUrl = normalizeBaseUrl(builder.baseUrl);
    this.apiKey = builder.apiKey;
    this.apiKeyPrefixExplicit = builder.apiKeyPrefix;
    this.tenantId = builder.tenantId;
    this.orgId = builder.orgId;
    this.userId = builder.userId;
  }

  public static MemoryEngineConfig fromEnvironment() {
    return builder()
        .baseUrl(env("MEMORY_ENGINE_API_BASE", "http://127.0.0.1:6030/api/v1"))
        .apiKey(env("MEMORY_ENGINE_API_KEY", ""))
        .apiKeyPrefix(env("MEMORY_ENGINE_API_KEY_PREFIX", null))
        .tenantId(Long.parseLong(env("MEMORY_ENGINE_TENANT_ID", "1")))
        .orgId(Long.parseLong(env("MEMORY_ENGINE_ORG_ID", "0")))
        .userId(parseLongOrNull(env("MEMORY_ENGINE_USER_ID", null)))
        .build();
  }

  public static Builder builder() {
    return new Builder();
  }

  private static String env(String key, String defaultValue) {
    String v = System.getenv(key);
    return v != null && !v.isBlank() ? v : defaultValue;
  }

  private static Long parseLongOrNull(String v) {
    if (v == null || v.isBlank()) {
      return null;
    }
    return Long.parseLong(v);
  }

  private static String normalizeBaseUrl(String url) {
    String u = url.endsWith("/") ? url.substring(0, url.length() - 1) : url;
    if (!u.endsWith("/api/v1")) {
      if (u.endsWith("/api")) {
        return u + "/v1";
      }
      if (!u.contains("/api/v1")) {
        return u + (u.matches("https?://[^/]+$") ? "/api/v1" : "");
      }
    }
    return u;
  }

  public String getBaseUrl() {
    return baseUrl;
  }

  public String getApiKey() {
    return apiKey;
  }

  /** Explicit {@code MEMORY_ENGINE_API_KEY_PREFIX} (may be null). */
  public String getApiKeyPrefixExplicit() {
    return apiKeyPrefixExplicit;
  }

  public long getTenantId() {
    return tenantId;
  }

  public long getOrgId() {
    return orgId;
  }

  public Long getUserId() {
    return userId;
  }

  public String healthUrl() {
    return baseUrl.replace("/api/v1", "") + "/health";
  }

  public static final class Builder {
    private String baseUrl = "http://127.0.0.1:6030/api/v1";
    private String apiKey = "";
    private String apiKeyPrefix;
    private long tenantId = 1L;
    private long orgId = 0L;
    private Long userId;

    public Builder baseUrl(String baseUrl) {
      this.baseUrl = baseUrl;
      return this;
    }

    public Builder apiKey(String apiKey) {
      this.apiKey = apiKey;
      return this;
    }

    public Builder apiKeyPrefix(String apiKeyPrefix) {
      this.apiKeyPrefix = apiKeyPrefix;
      return this;
    }

    public Builder tenantId(long tenantId) {
      this.tenantId = tenantId;
      return this;
    }

    public Builder orgId(long orgId) {
      this.orgId = orgId;
      return this;
    }

    public Builder userId(Long userId) {
      this.userId = userId;
      return this;
    }

    public MemoryEngineConfig build() {
      return new MemoryEngineConfig(this);
    }
  }

  @Override
  public boolean equals(Object o) {
    if (this == o) {
      return true;
    }
    if (!(o instanceof MemoryEngineConfig that)) {
      return false;
    }
    return tenantId == that.tenantId
        && orgId == that.orgId
        && Objects.equals(baseUrl, that.baseUrl)
        && Objects.equals(apiKey, that.apiKey)
        && Objects.equals(apiKeyPrefixExplicit, that.apiKeyPrefixExplicit)
        && Objects.equals(userId, that.userId);
  }

  @Override
  public int hashCode() {
    return Objects.hash(baseUrl, apiKey, apiKeyPrefixExplicit, tenantId, orgId, userId);
  }
}
