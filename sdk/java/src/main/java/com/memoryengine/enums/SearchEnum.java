package com.memoryengine.enums;

/** Schema search mode (aligned with Python SEARCHENUM). */
public enum SearchEnum {
  EXACT,
  REGEX,
  SEMANTIC,
  LLM;

  /** Alias for semantic fuzzy search. */
  public static final SearchEnum FUZZY = SEMANTIC;
}
