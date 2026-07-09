package com.memoryengine;

import com.fasterxml.jackson.databind.JsonNode;
import com.memoryengine.internal.HttpTransport;
import java.io.IOException;
import java.time.Duration;
import java.util.Map;

/** API key prefix + secret validation (aligned with Python {@code credentials}). */
public final class MemoryEngineCredentials {

  private static volatile SessionInfo sessionCache;

  private MemoryEngineCredentials() {}

  public record SessionInfo(
      String keyPrefix,
      long appUserId,
      String memoryUserId,
      long tenantId,
      long orgId,
      boolean valid) {}

  /** Match server lookup: first 16 chars of the full API key (or 8 if shorter). */
  public static String derivePrefixFromSecret(String rawKey) {
    String key = rawKey.strip();
    return key.length() >= 16 ? key.substring(0, 16) : key.substring(0, Math.min(8, key.length()));
  }

  public static String requireApiKeyPrefix(MemoryEngineConfig config) {
    String prefix = config.getApiKeyPrefixExplicit();
    if (prefix == null || prefix.isBlank()) {
      throw new MemoryEngineConfigError(
          "未设置 MEMORY_ENGINE_API_KEY_PREFIX，且无法从 MEMORY_ENGINE_API_KEY 推导。");
    }
    return prefix.strip();
  }

  /** Prefix from env, or derived from full {@code MEMORY_ENGINE_API_KEY}. */
  public static String resolveKeyPrefix(MemoryEngineConfig config) {
    String explicit = config.getApiKeyPrefixExplicit();
    if (explicit != null && !explicit.isBlank()) {
      return explicit.strip();
    }
    return derivePrefixFromSecret(requireApiKeySecret(config));
  }

  public static String requireApiKeySecret(MemoryEngineConfig config) {
    String key = config.getApiKey();
    if (key == null || key.isBlank()) {
      throw new MemoryEngineConfigError(
          "未设置 MEMORY_ENGINE_API_KEY。"
              + "请使用申请 Key 时一次性展示的完整密钥（非仅前缀）。");
    }
    return key.strip();
  }

  public static void clearSessionCache() {
    sessionCache = null;
  }

  /** Validate API key via {@code GET /onboarding/session}; return authoritative prefix. */
  public static String validatePrefixForRead(HttpTransport http)
      throws IOException, InterruptedException {
    requireApiKeySecret(http.config());
    SessionInfo session = fetchSession(http);
    if (!session.valid()) {
      throw new MemoryEngineConfigError(
          "API Key 无效或已吊销（前缀 '" + session.keyPrefix() + "'）。请在 Dashboard 重新申请 Key。");
    }
    String expected = resolveKeyPrefix(http.config());
    if (!session.keyPrefix().equals(expected)) {
      throw new MemoryEngineConfigError(
          "MEMORY_ENGINE_API_KEY 与 MEMORY_ENGINE_API_KEY_PREFIX 不一致："
              + "env 前缀="
              + expected
              + "，服务端="
              + session.keyPrefix()
              + "。可删除 MEMORY_ENGINE_API_KEY_PREFIX，仅保留完整 MEMORY_ENGINE_API_KEY。");
    }
    return session.keyPrefix();
  }

  public static String ensureWriteContext(HttpTransport http)
      throws IOException, InterruptedException {
    return validatePrefixForRead(http);
  }

  /** Mongo {@code user_id} partition for the current API key. */
  public static String memoryUserId(HttpTransport http) throws IOException, InterruptedException {
    ensureWriteContext(http);
    return fetchSession(http).memoryUserId();
  }

  private static SessionInfo fetchSession(HttpTransport http)
      throws IOException, InterruptedException {
    if (sessionCache != null) {
      return sessionCache;
    }
    requireApiKeySecret(http.config());
    JsonNode root =
        http.get("/onboarding/session", Map.of(), Duration.ofSeconds(30), false);
    if (root == null || root.isNull()) {
      throw new MemoryEngineConfigError("无法验证 API Key：空响应。");
    }
    JsonNode data = root.get("data");
    if (data == null || data.isNull()) {
      throw new MemoryEngineConfigError("无法验证 API Key：缺少 data。");
    }
    String keyPrefix = data.get("key_prefix").asText();
    String memoryUserId =
        data.hasNonNull("memory_user_id")
            ? data.get("memory_user_id").asText()
            : keyPrefix;
    sessionCache =
        new SessionInfo(
            keyPrefix,
            data.get("app_user_id").asLong(),
            memoryUserId,
            data.get("tenant_id").asLong(),
            data.get("org_id").asLong(),
            !data.has("valid") || data.get("valid").asBoolean(true));
    return sessionCache;
  }

  public static void raiseSessionHttpError(int status, String detail, MemoryEngineConfig config) {
    String apiBase =
        config.getBaseUrl().isBlank() ? "(未设置 MEMORY_ENGINE_API_BASE)" : config.getBaseUrl();

    if (status == 401 || status == 403) {
      if (detail != null
          && (detail.contains("Missing Bearer") || detail.contains("Bearer API key required"))) {
        throw new MemoryEngineConfigError(
            "未提供有效的 MEMORY_ENGINE_API_KEY（Bearer）。\n"
                + "请 export MEMORY_ENGINE_API_KEY=申请时一次性展示的完整密钥（以 mos_ 开头）。");
      }
      if (detail != null
          && (detail.contains("Invalid API key") || detail.contains("API key not found"))) {
        throw new MemoryEngineConfigError(
            "MEMORY_ENGINE_API_KEY 无效或错误：服务端拒绝了当前密钥。\n"
                + "请确认使用的是完整密钥（非仅前缀、非占位符、非他人 Key）。\n"
                + "当前 API: "
                + apiBase
                + "\n"
                + "服务端说明: "
                + (detail.isBlank() ? "Invalid API key" : detail));
      }
      if (detail != null && detail.contains("API key revoked")) {
        throw new MemoryEngineConfigError(
            "MEMORY_ENGINE_API_KEY 已吊销。请在 Dashboard 重新申请 Key 并更新环境变量。");
      }
      if (detail != null && detail.contains("API key expired")) {
        throw new MemoryEngineConfigError(
            "MEMORY_ENGINE_API_KEY 已过期。请在 Dashboard 重新申请 Key 并更新环境变量。");
      }
      if (detail != null && detail.contains("X-Tenant-Id does not match")) {
        throw new MemoryEngineConfigError(
            "MEMORY_ENGINE_TENANT_ID 与当前 API Key 所属租户不一致。\n服务端说明: " + detail);
      }
      if (detail != null && detail.contains("X-Org-Id does not match")) {
        throw new MemoryEngineConfigError(
            "MEMORY_ENGINE_ORG_ID 与当前 API Key 所属组织不一致。\n服务端说明: " + detail);
      }
    }

    throw new MemoryEngineConfigError(
        "无法验证 API Key（HTTP " + status + "）。\n"
            + "请检查 MEMORY_ENGINE_API_KEY、MEMORY_ENGINE_API_BASE、MEMORY_ENGINE_TENANT_ID、MEMORY_ENGINE_ORG_ID。\n"
            + "API: "
            + apiBase
            + "\n"
            + "服务端说明: "
            + (detail == null || detail.isBlank() ? "unknown" : detail));
  }
}
