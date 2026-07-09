package com.memoryengine.model;

import com.fasterxml.jackson.annotation.JsonInclude;
import java.util.Map;

/** Raw text input for parse pipeline. */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ParseInput(String query, Map<String, Object> extra) {

  public ParseInput(String query) {
    this(query, null);
  }
}
