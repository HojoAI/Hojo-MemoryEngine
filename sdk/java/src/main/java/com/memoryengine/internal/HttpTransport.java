package com.memoryengine.internal;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.memoryengine.MemoryEngineConfig;
import com.memoryengine.MemoryEngineCredentials;
import com.memoryengine.MemoryEngineException;
import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.StringJoiner;

/** Low-level HTTP transport for MemoryEngine API (aligned with Python {@code transport}). */
public final class HttpTransport {

  private static final ObjectMapper MAPPER =
      new ObjectMapper().setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE);

  private final MemoryEngineConfig config;
  private final HttpClient http;

  public HttpTransport(MemoryEngineConfig config) {
    this.config = config;
    this.http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(30)).build();
  }

  public MemoryEngineConfig config() {
    return config;
  }

  public JsonNode get(String path, Map<String, String> query, Duration timeout)
      throws IOException, InterruptedException {
    return send("GET", path, query, null, timeout, true);
  }

  public JsonNode get(
      String path, Map<String, String> query, Duration timeout, boolean map404ToNull)
      throws IOException, InterruptedException {
    return send("GET", path, query, null, timeout, map404ToNull);
  }

  public JsonNode post(String path, Map<String, String> query, Object body, Duration timeout)
      throws IOException, InterruptedException {
    return send("POST", path, query, body, timeout, true);
  }

  public JsonNode postJson(String path, Object body, Duration timeout)
      throws IOException, InterruptedException {
    return post(path, Map.of(), body, timeout);
  }

  private JsonNode send(
      String method,
      String path,
      Map<String, String> query,
      Object body,
      Duration timeout,
      boolean map404ToNull)
      throws IOException, InterruptedException {
    String url = config.getBaseUrl() + path + buildQuery(query);
    HttpRequest.Builder builder =
        HttpRequest.newBuilder()
            .uri(URI.create(url))
            .timeout(timeout)
            .header("Content-Type", "application/json")
            .header("Accept", "application/json")
            .header("X-Tenant-Id", String.valueOf(config.getTenantId()))
            .header("X-Org-Id", String.valueOf(config.getOrgId()));
    if (config.getUserId() != null) {
      builder.header("X-User-Id", String.valueOf(config.getUserId()));
    }
    String prefix = resolveHeaderPrefix();
    if (!prefix.isBlank()) {
      builder.header("X-Api-Key-Prefix", prefix);
    }
    if (config.getApiKey() != null && !config.getApiKey().isBlank()) {
      builder.header("Authorization", "Bearer " + config.getApiKey());
    }
    if (body != null) {
      builder.method(method, HttpRequest.BodyPublishers.ofString(MAPPER.writeValueAsString(body)));
    } else {
      builder.method(method, HttpRequest.BodyPublishers.noBody());
    }
    HttpResponse<String> response = http.send(builder.build(), HttpResponse.BodyHandlers.ofString());
    if (response.statusCode() == 404 && map404ToNull) {
      return MAPPER.nullNode();
    }
    if (response.statusCode() < 200 || response.statusCode() >= 300) {
      if ("/onboarding/session".equals(path)) {
        MemoryEngineCredentials.raiseSessionHttpError(
            response.statusCode(), extractDetail(response.body()), config);
      }
      throw new MemoryEngineException(
          "HTTP " + response.statusCode() + ": " + response.body(), response.statusCode());
    }
    if (response.body() == null || response.body().isBlank()) {
      return MAPPER.nullNode();
    }
    return MAPPER.readTree(response.body());
  }

  private String resolveHeaderPrefix() {
    String explicit = config.getApiKeyPrefixExplicit();
    if (explicit != null && !explicit.isBlank()) {
      return explicit.strip();
    }
    String key = config.getApiKey();
    if (key != null && !key.isBlank()) {
      return MemoryEngineCredentials.derivePrefixFromSecret(key);
    }
    return "";
  }

  private static String extractDetail(String body) {
    if (body == null || body.isBlank()) {
      return "";
    }
    try {
      JsonNode root = MAPPER.readTree(body);
      if (root.has("detail")) {
        JsonNode detail = root.get("detail");
        return detail.isTextual() ? detail.asText() : detail.toString();
      }
      if (root.has("message")) {
        return root.get("message").asText();
      }
    } catch (IOException ignored) {
      return body.length() > 300 ? body.substring(0, 300) : body;
    }
    return body.length() > 300 ? body.substring(0, 300) : body;
  }

  public <T> T parseData(JsonNode root, TypeReference<T> typeRef) throws IOException {
    if (root == null || root.isNull()) {
      return null;
    }
    JsonNode data = root.get("data");
    if (data == null || data.isNull()) {
      return null;
    }
    return MAPPER.convertValue(data, typeRef);
  }

  public JsonNode dataNode(JsonNode root) {
    if (root == null || root.isNull()) {
      return null;
    }
    JsonNode data = root.get("data");
    if (data == null || data.isNull()) {
      return null;
    }
    return data;
  }

  public ObjectMapper mapper() {
    return MAPPER;
  }

  private static String buildQuery(Map<String, String> query) {
    if (query == null || query.isEmpty()) {
      return "";
    }
    StringJoiner joiner = new StringJoiner("&", "?", "");
    for (Map.Entry<String, String> e : query.entrySet()) {
      if (e.getValue() != null) {
        joiner.add(
            URLEncoder.encode(e.getKey(), StandardCharsets.UTF_8)
                + "="
                + URLEncoder.encode(e.getValue(), StandardCharsets.UTF_8));
      }
    }
    return joiner.toString();
  }

  public static Map<String, String> queryOf(String... kv) {
    Map<String, String> m = new LinkedHashMap<>();
    for (int i = 0; i + 1 < kv.length; i += 2) {
      m.put(kv[i], kv[i + 1]);
    }
    return m;
  }
}
