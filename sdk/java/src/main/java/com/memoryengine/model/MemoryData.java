package com.memoryengine.model;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.JsonNode;

/** User memory data document. */
@JsonIgnoreProperties(ignoreUnknown = true)
public record MemoryData(
    String userId, JsonNode value, String memoryFieldName, String retrieveResult) {

  public Object data() {
    if (value == null || value.isNull()) {
      return null;
    }
    if (value.isTextual()) {
      return value.asText();
    }
    if (value.isNumber()) {
      return value.numberValue();
    }
    if (value.isBoolean()) {
      return value.asBoolean();
    }
    return value;
  }
}
