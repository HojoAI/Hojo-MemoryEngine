package com.memoryengine;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.memoryengine.changelog.SchemaChangelogWatcher;
import com.memoryengine.enums.SearchEnum;
import com.memoryengine.internal.HttpTransport;
import com.memoryengine.internal.ParseRuleSupport;
import com.memoryengine.model.ParseRule;
import com.memoryengine.model.SchemaModel;
import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

/** High-level schema API (aligned with Python {@code Schema}). */
public final class Schema {

  private static final Map<String, SchemaModel> LOCAL_CACHE = new ConcurrentHashMap<>();
  private static volatile SchemaChangelogWatcher changelogWatcher;

  private final HttpTransport http;

  Schema(HttpTransport http) {
    this.http = http;
  }

  public SchemaChangelogWatcher enableHotReload() {
    return enableHotReload(2000);
  }

  public SchemaChangelogWatcher enableHotReload(long pollIntervalMs) {
    if (changelogWatcher == null) {
      changelogWatcher =
          new SchemaChangelogWatcher(
              http,
              event -> {
                String table = event.path("table").asText("");
                if (!"memory_field".equals(table)) {
                  return;
                }
                JsonNode payload = event.get("payload");
                String name =
                    event.hasNonNull("memory_field_name")
                        ? event.get("memory_field_name").asText()
                        : payload != null && payload.has("name")
                            ? payload.get("name").asText()
                            : null;
                if (name != null) {
                  LOCAL_CACHE.remove(name);
                }
              },
              pollIntervalMs);
      changelogWatcher.start();
    }
    return changelogWatcher;
  }

  public void disableHotReload() {
    if (changelogWatcher != null) {
      changelogWatcher.stop();
      changelogWatcher = null;
    }
  }

  public Optional<SchemaModel> get(String name) throws IOException, InterruptedException {
    return get(name, SearchEnum.EXACT);
  }

  public Optional<SchemaModel> get(String name, SearchEnum mode)
      throws IOException, InterruptedException {
    MemoryEngineCredentials.validatePrefixForRead(http);
    if (LOCAL_CACHE.containsKey(name)) {
      return Optional.ofNullable(LOCAL_CACHE.get(name));
    }
    JsonNode root =
        http.get(
            "/schema/get",
            HttpTransport.queryOf("name", name, "mode", mode.name()),
            SdkTimeouts.httpTimeout());
    SchemaModel model = http.parseData(root, new TypeReference<SchemaModel>() {});
    LOCAL_CACHE.put(name, model);
    return Optional.ofNullable(model);
  }

  public SchemaModel getOrCreate(String name) throws IOException, InterruptedException {
    return getOrCreate(name, SearchEnum.EXACT, null, Map.of());
  }

  public SchemaModel getOrCreate(String name, SearchEnum mode, ParseRule parseRule)
      throws IOException, InterruptedException {
    return getOrCreate(name, mode, parseRule, Map.of());
  }

  public SchemaModel getOrCreate(
      String name, SearchEnum mode, ParseRule parseRule, Map<String, Object> createExtras)
      throws IOException, InterruptedException {
    MemoryEngineCredentials.ensureWriteContext(http);
    Optional<SchemaModel> existing = get(name, mode);
    if (existing.isPresent()) {
      return existing.get();
    }
    Map<String, Object> body = new LinkedHashMap<>(createExtras);
    body.put("name", name);
    JsonNode root =
        http.post(
            "/schema/create",
            HttpTransport.queryOf("dedup_mode", mode.name()),
            body,
            SdkTimeouts.httpTimeout());
    SchemaModel schema = http.parseData(root, new TypeReference<SchemaModel>() {});
    if (schema == null) {
      throw new MemoryEngineException("schema create returned empty data");
    }
    LOCAL_CACHE.put(name, schema);
    if (parseRule != null) {
      createParseRule(name, parseRule);
    }
    return schema;
  }

  public void createParseRule(String memoryFieldName, ParseRule parseRule)
      throws IOException, InterruptedException {
    MemoryEngineCredentials.ensureWriteContext(http);
    http.postJson(
        "/schema/parse/create",
        ParseRuleSupport.parseRuleCreateBody(memoryFieldName, parseRule),
        SdkTimeouts.httpTimeout());
  }

  public Map<String, Object> getParseRule(String memoryFieldName, String ruleName)
      throws IOException, InterruptedException {
    MemoryEngineCredentials.validatePrefixForRead(http);
    JsonNode root =
        http.get(
            "/schema/parse/get",
            HttpTransport.queryOf("memory_field_name", memoryFieldName, "rule_name", ruleName),
            SdkTimeouts.httpTimeout());
    return http.parseData(root, new TypeReference<Map<String, Object>>() {});
  }

  /**
   * Upsert parse rule by {@code rule_name} with versioning.
   *
   * @return {@code "skipped"} | {@code "created"} | {@code "versioned"}
   */
  public String ensureParseRule(String memoryFieldName, ParseRule parseRule)
      throws IOException, InterruptedException {
    MemoryEngineCredentials.ensureWriteContext(http);
    Map<String, Object> existing = getParseRule(memoryFieldName, parseRule.ruleName());
    if (existing != null && ParseRuleSupport.llmParseConfigMatches(existing, parseRule)) {
      return "skipped";
    }
    createParseRule(memoryFieldName, parseRule);
    return existing != null ? "versioned" : "created";
  }

  public ParseRule llmParse(
      String memoryFieldName,
      String ruleName,
      String prompt,
      String model,
      Map<String, Object> llmParams,
      String system,
      String outputFormat,
      boolean ensure)
      throws IOException, InterruptedException {
    MemoryEngineCredentials.ensureWriteContext(http);
    ParseRule parseRule =
        ParseRule.llmParse(ruleName, prompt, model, llmParams, system, outputFormat);
    if (ensure) {
      ensureParseRule(memoryFieldName, parseRule);
    }
    return parseRule;
  }

  public ParseRule llmParse(String memoryFieldName, String ruleName, String prompt)
      throws IOException, InterruptedException {
    return llmParse(memoryFieldName, ruleName, prompt, null, null, null, "text", true);
  }

  public ParseRule llmParse(
      String memoryFieldName,
      String ruleName,
      String prompt,
      String model,
      Map<String, Object> llmParams)
      throws IOException, InterruptedException {
    return llmParse(memoryFieldName, ruleName, prompt, model, llmParams, null, "text", true);
  }
}
