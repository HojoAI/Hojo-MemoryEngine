"""Public enums."""

from enum import StrEnum


class SEARCHENUM(StrEnum):
  EXACT = "EXACT"
  REGEX = "REGEX"
  SEMANTIC = "SEMANTIC"
  LLM = "LLM"
  FUZZY = "SEMANTIC"


class WRITERULE(StrEnum):
  OVERWRITE = "OVERWRITE"
  APPEND = "APPEND"
  MERGE = "MERGE"


class RETRIEVEENUM(StrEnum):
  EXACT = "EXACT"
  REGEX = "REGEX"
  SEMANTIC = "SEMANTIC"
  LLM = "LLM"


class PARSERULEENUM(StrEnum):
  """Parse rule kinds (runtime registration)."""

  LLM = "llm"
  BUILTIN = "builtin"
  CUSTOM = "custom"
