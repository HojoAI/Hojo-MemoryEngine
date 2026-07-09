package com.memoryengine.model;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.memoryengine.enums.RetrieveEnum;

/** Retrieve rule for explicit/implicit search. */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record RetrieveRule(RetrieveEnum method, LLM llm, Prompt prompt) {

  public RetrieveRule(RetrieveEnum method) {
    this(method, null, null);
  }
}
