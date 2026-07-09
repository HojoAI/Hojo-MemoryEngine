package com.memoryengine.internal;

import com.memoryengine.model.ParseRule;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;

/** Parse-rule helpers (aligned with Python {@code _parse_rule_create_body} / config match). */
public final class ParseRuleSupport {

  private ParseRuleSupport() {}

  @SuppressWarnings("unchecked")
  public static boolean llmParseConfigMatches(Map<String, Object> existing, ParseRule desired) {
    if (existing == null || existing.isEmpty()) {
      return false;
    }
    Object storedObj = existing.get("rule_config_json");
    if (!(storedObj instanceof Map<?, ?> storedMap)) {
      return false;
    }
    Map<String, Object> stored = (Map<String, Object>) storedMap;
    Map<String, Object> want =
        desired.ruleConfigJson() != null ? desired.ruleConfigJson() : Map.of();
    return Objects.equals(stored.get("prompt"), want.get("prompt"))
        && Objects.equals(stored.get("llm"), want.get("llm"))
        && Objects.equals(
            stored.getOrDefault("llm_params", Map.of()),
            want.getOrDefault("llm_params", Map.of()))
        && Objects.equals(stored.getOrDefault("system", ""), want.getOrDefault("system", ""))
        && Objects.equals(
            stored.getOrDefault("output_format", "json"),
            want.getOrDefault("output_format", "json"));
  }

  public static Map<String, Object> parseRuleCreateBody(String memoryFieldName, ParseRule parseRule) {
    Map<String, Object> body = new LinkedHashMap<>();
    body.put("memory_field_name", memoryFieldName);
    body.put("rule_name", parseRule.ruleName());
    if (parseRule.ruleConfigJson() != null) {
      body.put("rule_config_json", parseRule.ruleConfigJson());
    }
    if (parseRule.capabilityName() != null) {
      body.put("capability_name", parseRule.capabilityName());
    }
    if (parseRule.moduleName() != null) {
      body.put("module_name", parseRule.moduleName());
    }
    if (parseRule.serviceName() != null) {
      body.put("service_name", parseRule.serviceName());
    }
    return body;
  }
}
