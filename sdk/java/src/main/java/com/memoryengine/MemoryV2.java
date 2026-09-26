package com.memoryengine;

import com.fasterxml.jackson.databind.JsonNode;
import com.memoryengine.internal.HttpTransport;
import java.io.IOException;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** MemoryEngine V2 client for atomic claims and permission-aware retrieval. */
public final class MemoryV2 {

  private static final Duration TIMEOUT = Duration.ofSeconds(120);
  private final HttpTransport http;

  MemoryV2(HttpTransport http) {
    this.http = http;
  }

  public JsonNode ingest(
      String userId,
      Map<String, Object> namespace,
      Map<String, Object> sourceEvent,
      List<?> claims)
      throws IOException, InterruptedException {
    Map<String, Object> body = new LinkedHashMap<>();
    body.put("user_id", userId);
    body.put("namespace", namespace);
    body.put("source_event", sourceEvent);
    body.put("claims", claims);
    return post("/memory/ingest", body);
  }

  public JsonNode retrieve(
      String userId,
      String query,
      Map<String, Object> usageContext,
      List<String> requiredDimensions,
      String method)
      throws IOException, InterruptedException {
    return retrieve(userId, query, usageContext, requiredDimensions, method, null, null);
  }

  /** Retrieve with an optional server-side policy profile and current-context guard. */
  public JsonNode retrieve(
      String userId,
      String query,
      Map<String, Object> usageContext,
      List<String> requiredDimensions,
      String method,
      String ruleName,
      Map<String, Object> currentContext)
      throws IOException, InterruptedException {
    Map<String, Object> body = new LinkedHashMap<>();
    body.put("user_id", userId);
    body.put("query", query);
    body.put("usage_context", usageContext);
    body.put("required_dimensions", requiredDimensions == null ? List.of() : requiredDimensions);
    body.put("method", method == null ? "SEMANTIC" : method);
    if (ruleName != null && !ruleName.isBlank()) body.put("rule_name", ruleName);
    if (currentContext != null) body.put("current_context", currentContext);
    return post("/memory/retrieve", body);
  }

  public JsonNode call(
      String bundleId,
      String moduleId,
      String promptTemplate,
      Map<String, Object> llm,
      String slot,
      boolean useLlm)
      throws IOException, InterruptedException {
    Map<String, Object> body = new LinkedHashMap<>();
    body.put("bundle_id", bundleId);
    body.put("module_id", moduleId);
    body.put("prompt_template", promptTemplate);
    body.put("slot", slot == null ? "<memory_context>" : slot);
    body.put("use_llm", useLlm);
    if (llm != null) body.put("llm", llm);
    return post("/memory/call", body);
  }

  public JsonNode history(String claimId) throws IOException, InterruptedException {
    return http.getAtBase(
        http.config().v2BaseUrl(), "/memory/claims/" + claimId + "/history", TIMEOUT);
  }

  public JsonNode revoke(String claimId, String reason) throws IOException, InterruptedException {
    return post("/memory/claims/" + claimId + "/revoke", Map.of("reason", reason));
  }

  public JsonNode resolve(String claimId, String resolution, String reason)
      throws IOException, InterruptedException {
    Map<String, Object> body = new LinkedHashMap<>();
    body.put("resolution", resolution);
    body.put("reason", reason);
    return post("/memory/claims/" + claimId + "/resolve", body);
  }

  private JsonNode post(String path, Object body) throws IOException, InterruptedException {
    return http.postJsonAtBase(http.config().v2BaseUrl(), path, body, TIMEOUT);
  }
}
