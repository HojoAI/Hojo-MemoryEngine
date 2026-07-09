package com.memoryengine;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.memoryengine.enums.RetrieveEnum;
import com.memoryengine.enums.WriteRule;
import com.memoryengine.internal.HttpTransport;
import com.memoryengine.model.LLM;
import com.memoryengine.model.MemoryData;
import com.memoryengine.model.ParseInput;
import com.memoryengine.model.Prompt;
import com.memoryengine.model.RetrieveRule;
import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

/** High-level memory data API (aligned with Python {@code Data}). */
public final class Data {

  private final HttpTransport http;
  private final ObjectMapper mapper;

  Data(HttpTransport http) {
    this.http = http;
    this.mapper = http.mapper();
  }

  public MemoryData parse(String schemaName, ParseInput parseInput)
      throws IOException, InterruptedException {
    return parse(schemaName, parseInput, null, null, null);
  }

  public MemoryData parse(String schemaName, ParseInput parseInput, WriteRule writeRule)
      throws IOException, InterruptedException {
    return parse(schemaName, parseInput, writeRule, null, null);
  }

  public MemoryData parse(
      String schemaName, ParseInput parseInput, WriteRule writeRule, String parseRuleName)
      throws IOException, InterruptedException {
    return parse(schemaName, parseInput, writeRule, parseRuleName, null);
  }

  public MemoryData parse(
      String schemaName,
      ParseInput parseInput,
      WriteRule writeRule,
      String parseRuleName,
      String userId)
      throws IOException, InterruptedException {
    String uid = resolveUserId(userId);
    Map<String, Object> payload = new LinkedHashMap<>();
    payload.put("user_id", uid);
    payload.put("memory_field_name", schemaName);
    payload.put("query", parseInput.query());
    if (parseInput.extra() != null) {
      payload.put("extra", parseInput.extra());
    }
    if (writeRule != null) {
      payload.put("write_rule", writeRule.name());
    }
    if (parseRuleName != null && !parseRuleName.isBlank()) {
      payload.put("parse_rule_name", parseRuleName);
    }
    JsonNode root = http.postJson("/data/create", payload, SdkTimeouts.parseTimeout());
    MemoryData data = http.parseData(root, new TypeReference<MemoryData>() {});
    if (data == null) {
      throw new MemoryEngineException("data create returned empty data");
    }
    return data;
  }

  /** {@code get(schema)} — default {@code memory_user_id}. */
  public Optional<MemoryData> get(String schemaName) throws IOException, InterruptedException {
    return getExact(schemaName, null);
  }

  /** {@code get(schema, user_id)}. */
  public Optional<MemoryData> get(String schemaName, String userId)
      throws IOException, InterruptedException {
    return getExact(schemaName, userId);
  }

  /**
   * {@code get(schema, rule=...)} in Python — field retrieve with default {@code memory_user_id}.
   */
  public Optional<MemoryData> get(String schemaName, RetrieveRule rule)
      throws IOException, InterruptedException {
    return get(schemaName, null, rule);
  }

  /** {@code get(schema, user_id, rule)}. */
  public Optional<MemoryData> get(String schemaName, String userId, RetrieveRule rule)
      throws IOException, InterruptedException {
    if (rule == null) {
      return getExact(schemaName, userId);
    }
    return retrieve(resolveUserId(userId), Optional.of(schemaName), rule);
  }

  /**
   * {@code get(user_id, RetrieveRule)} — cross-field retrieve (Python legacy overload).
   *
   * <p>Not named {@code get(String, RetrieveRule)} to avoid ambiguity with schema+rule.
   */
  public Optional<MemoryData> getByUser(String userId, RetrieveRule rule)
      throws IOException, InterruptedException {
    return retrieve(userId, Optional.empty(), rule);
  }

  public String call(
      String schemaName,
      String promptTemplate,
      String slot,
      Object memData,
      LLM llm,
      boolean useLlm)
      throws IOException, InterruptedException {
    MemoryEngineCredentials.validatePrefixForRead(http);
    if (!useLlm && llm == null) {
      return promptTemplate.replace(slot, String.valueOf(memData));
    }
    Map<String, Object> body = new LinkedHashMap<>();
    body.put("memory_field_name", schemaName);
    body.put("prompt_template", promptTemplate);
    body.put("slot", slot);
    body.put("mem_data", memData);
    body.put("use_llm", useLlm);
    if (llm != null) {
      body.put("llm", llmToBody(llm));
    }
    JsonNode root = http.postJson("/data/call", body, SdkTimeouts.retrieveTimeout());
    JsonNode data = http.dataNode(root);
    if (data != null && data.has("result")) {
      return data.get("result").asText();
    }
    return "";
  }

  public String call(String schemaName, String promptTemplate, String slot, Object memData)
      throws IOException, InterruptedException {
    return call(schemaName, promptTemplate, slot, memData, null, true);
  }

  private Optional<MemoryData> getExact(String schemaName, String userId)
      throws IOException, InterruptedException {
    MemoryEngineCredentials.validatePrefixForRead(http);
    String uid = resolveUserId(userId);
    JsonNode root =
        http.get(
            "/data/get",
            HttpTransport.queryOf("user_id", uid, "memory_field_name", schemaName),
            SdkTimeouts.httpTimeout());
    if (root == null || root.isNull()) {
      return Optional.empty();
    }
    return Optional.ofNullable(http.parseData(root, new TypeReference<MemoryData>() {}));
  }

  private Optional<MemoryData> retrieve(
      String userId, Optional<String> memoryFieldName, RetrieveRule rule)
      throws IOException, InterruptedException {
    MemoryEngineCredentials.validatePrefixForRead(http);
    RetrieveRule effective = rule != null ? rule : new RetrieveRule(RetrieveEnum.EXACT);
    ObjectNode payload = mapper.createObjectNode();
    payload.put("user_id", userId);
    payload.set("rule", ruleToJson(effective));
    memoryFieldName.ifPresent(n -> payload.put("memory_field_name", n));
    JsonNode root = http.postJson("/data/retrieve", payload, SdkTimeouts.retrieveTimeout());
    return Optional.ofNullable(http.parseData(root, new TypeReference<MemoryData>() {}));
  }

  private ObjectNode ruleToJson(RetrieveRule rule) {
    ObjectNode node = mapper.createObjectNode();
    node.put("method", rule.method().name());
    if (rule.prompt() != null) {
      node.put("prompt", rule.prompt().text());
    }
    if (rule.llm() != null) {
      node.set("llm", mapper.valueToTree(llmToBody(rule.llm())));
    }
    return node;
  }

  private String resolveUserId(String userId) throws IOException, InterruptedException {
    if (userId != null && !userId.isBlank()) {
      return userId.trim();
    }
    return MemoryEngineCredentials.memoryUserId(http);
  }

  private static Map<String, Object> llmToBody(LLM llm) {
    Map<String, Object> body = new LinkedHashMap<>();
    body.put("base_url", llm.baseUrl());
    body.put("api_key", llm.apiKey());
    body.put("model_name", llm.modelName());
    return body;
  }
}
