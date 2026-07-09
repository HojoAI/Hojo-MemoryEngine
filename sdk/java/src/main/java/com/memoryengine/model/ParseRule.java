package com.memoryengine.model;

import com.fasterxml.jackson.annotation.JsonInclude;
import java.util.LinkedHashMap;
import java.util.Map;

/** Parse rule with optional capability binding (aligned with Python {@code ParseRule}). */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ParseRule(
    String ruleName,
    String capabilityName,
    String moduleName,
    String serviceName,
    Map<String, Object> ruleConfigJson) {

  /** Build parse rule config locally (no HTTP). */
  public static ParseRule llmParse(
      String ruleName,
      String prompt,
      String model,
      Map<String, Object> llmParams,
      String system,
      String outputFormat) {
    Map<String, Object> cfg = new LinkedHashMap<>();
    cfg.put("prompt", prompt);
    cfg.put("system", system != null ? system : "");
    cfg.put("output_format", outputFormat != null ? outputFormat : "text");
    if (model != null && !model.isBlank()) {
      cfg.put("llm", model);
    }
    if (llmParams != null && !llmParams.isEmpty()) {
      cfg.put("llm_params", llmParams);
    }
    return new ParseRule(ruleName, null, null, null, cfg);
  }

  public static ParseRule llmParse(String ruleName, String prompt) {
    return llmParse(ruleName, prompt, null, null, null, "text");
  }

  public static ParseRule llmParse(
      String ruleName, String prompt, String model, Map<String, Object> llmParams) {
    return llmParse(ruleName, prompt, model, llmParams, null, "text");
  }

  /** Convenience wrapper with default JSON extraction prompt. */
  public static ParseRule llmFieldExtract(
      String ruleName,
      LLM llm,
      String model,
      String valueKey,
      String extraPrompt,
      Map<String, Object> llmParams) {
    String effectiveModel = model;
    if (llm != null && (effectiveModel == null || effectiveModel.isBlank())) {
      effectiveModel = llm.modelName();
    }
    String key = valueKey != null ? valueKey : "value";
    String prompt =
        extraPrompt != null
            ? extraPrompt
            : "从用户输入中抽取字段「{field}」，只输出 JSON，格式："
                + "{\"" + key + "\": \"简短中文值\"}。"
                + "无法判断则 " + key + " 为 null。\n\n用户输入：{text}";
    return llmParse(ruleName, prompt, effectiveModel, llmParams, null, "json");
  }
}
