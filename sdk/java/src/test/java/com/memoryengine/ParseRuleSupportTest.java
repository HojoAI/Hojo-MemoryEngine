package com.memoryengine;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.memoryengine.internal.ParseRuleSupport;
import com.memoryengine.model.ParseRule;
import java.util.Map;
import org.junit.jupiter.api.Test;

class ParseRuleSupportTest {

  @Test
  void llmParseStoresModelAndParams() {
    ParseRule rule =
        ParseRule.llmParse(
            "extract_gender",
            "prompt {field} {text}",
            "qwen-max-2025-01-25",
            Map.of("temperature", 0.1, "top_p", 0.9),
            null,
            "text");
    assertEquals("qwen-max-2025-01-25", rule.ruleConfigJson().get("llm"));
    assertEquals(0.1, ((Map<?, ?>) rule.ruleConfigJson().get("llm_params")).get("temperature"));
    assertEquals("text", rule.ruleConfigJson().get("output_format"));
    assertFalse(rule.ruleConfigJson().toString().contains("api_key"));
  }

  @Test
  void llmFieldExtractDelegatesToLlmParse() {
    ParseRule rule =
        ParseRule.llmFieldExtract("r1", null, "qwen-max", "value", null, Map.of("temperature", 0));
    assertEquals("qwen-max", rule.ruleConfigJson().get("llm"));
    assertEquals("json", rule.ruleConfigJson().get("output_format"));
    assertTrue(rule.ruleConfigJson().get("prompt").toString().contains("{field}"));
  }

  @Test
  void llmParseConfigMatchesSame() {
    ParseRule desired =
        ParseRule.llmParse(
            "extract_gender",
            "prompt {field}",
            "qwen-max",
            Map.of("temperature", 0.1),
            null,
            "text");
    Map<String, Object> existing =
        Map.of("rule_config_json", desired.ruleConfigJson(), "version", 1);
    assertTrue(ParseRuleSupport.llmParseConfigMatches(existing, desired));
  }

  @Test
  void llmParseConfigMatchesPromptDiff() {
    ParseRule desired = ParseRule.llmParse("r", "new prompt", "qwen-max", null, null, "text");
    Map<String, Object> existing =
        Map.of("rule_config_json", Map.of("prompt", "old prompt", "llm", "qwen-max"));
    assertFalse(ParseRuleSupport.llmParseConfigMatches(existing, desired));
  }

  @Test
  void parseRuleCreateBody() {
    Map<String, Object> body =
        ParseRuleSupport.parseRuleCreateBody(
            "用户性别",
            new ParseRule(
                "extract_gender",
                null,
                null,
                null,
                Map.of(
                    "prompt", "hi {text}",
                    "llm", "qwen-max",
                    "llm_params", Map.of("top_k", 40))));
    assertEquals("用户性别", body.get("memory_field_name"));
    assertEquals("qwen-max", ((Map<?, ?>) body.get("rule_config_json")).get("llm"));
  }
}
