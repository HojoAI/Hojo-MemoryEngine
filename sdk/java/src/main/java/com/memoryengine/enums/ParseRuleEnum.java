package com.memoryengine.enums;

/** Parse rule kinds (aligned with Python {@code PARSERULEENUM}). */
public enum ParseRuleEnum {
  LLM("llm"),
  BUILTIN("builtin"),
  CUSTOM("custom");

  private final String value;

  ParseRuleEnum(String value) {
    this.value = value;
  }

  public String value() {
    return value;
  }
}
