"""HTTP client for Memory Engine API."""

import os
from typing import Any

import httpx

from memory_engine_sdk.changelog import SchemaChangelogWatcher, watch_schema_changes
from memory_engine_sdk.credentials import (
    ensure_write_context,
    memory_user_id,
    validate_prefix_for_read,
)
from memory_engine_sdk.enums import RETRIEVEENUM, SEARCHENUM, WRITERULE
from memory_engine_sdk.models import LLM, MemoryData, MergeRule, ParseInput, ParseRule, RetrieveRule, SchemaModel
from memory_engine_sdk.transport import base_url, headers

_schema_local_cache: dict[str, SchemaModel | None] = {}
_active_schema_catalog: dict[str, SchemaModel] | None = None
_changelog_watcher: SchemaChangelogWatcher | None = None


def _http_timeout(default: float = 30.0) -> float:
  """Default HTTP timeout (seconds) for non-LLM calls."""
  raw = os.environ.get("MEMORY_ENGINE_HTTP_TIMEOUT")
  return float(raw) if raw else default


def _parse_timeout() -> float:
  """Timeout for ``Data.parse`` (sync LLM on server). Default 180s."""
  raw = os.environ.get("MEMORY_ENGINE_PARSE_TIMEOUT")
  if raw:
    return float(raw)
  return max(_http_timeout(), 180.0)


def _rule_to_body(rule: RetrieveRule) -> dict[str, Any]:
  body: dict[str, Any] = {"method": rule.method.value}
  if rule.prompt is not None:
    body["prompt"] = rule.prompt.text
  if rule.llm is not None:
    body["llm"] = {
      "base_url": rule.llm.base_url or None,
      "api_key": rule.llm.api_key or None,
      "model_name": rule.llm.model_name or None,
    }
  return body


def _llm_to_body(llm: LLM | None) -> dict[str, Any] | None:
  if llm is None:
    return None
  return {
    "base_url": llm.base_url or None,
    "api_key": llm.api_key or None,
    "model_name": llm.model_name or None,
  }


def _llm_parse_config_matches(
    existing: dict[str, Any] | None,
    desired: ParseRule,
) -> bool:
  """True when active rule has same prompt, model, params, system, and output_format."""
  if not existing:
    return False
  stored = existing.get("rule_config_json") or {}
  want = desired.rule_config_json or {}
  return (
    stored.get("prompt") == want.get("prompt")
    and stored.get("llm") == want.get("llm")
    and (stored.get("llm_params") or {}) == (want.get("llm_params") or {})
    and (stored.get("system") or "") == (want.get("system") or "")
    and stored.get("output_format", "json") == want.get("output_format", "json")
  )


def _merge_rule_create_body(memory_field_name: str, merge_rule: MergeRule) -> dict[str, Any]:
  body: dict[str, Any] = {
    "memory_field_name": memory_field_name,
    "rule_name": merge_rule.rule_name,
  }
  if merge_rule.rule_config_json is not None:
    body["rule_config_json"] = merge_rule.rule_config_json
  return body


def _llm_merge_config_matches(
    existing: dict[str, Any] | None,
    desired: MergeRule,
) -> bool:
  if not existing:
    return False
  stored = existing.get("rule_config_json") or {}
  want = desired.rule_config_json or {}
  return (
    stored.get("prompt") == want.get("prompt")
    and stored.get("llm") == want.get("llm")
    and (stored.get("llm_params") or {}) == (want.get("llm_params") or {})
    and (stored.get("system") or "") == (want.get("system") or "")
    and stored.get("output_format", "text") == want.get("output_format", "text")
  )


def _parse_rule_create_body(memory_field_name: str, parse_rule: ParseRule) -> dict[str, Any]:
  """API body for ``POST /schema/parse/create``."""
  body: dict[str, Any] = {
    "memory_field_name": memory_field_name,
    "rule_name": parse_rule.rule_name,
  }
  if parse_rule.rule_config_json is not None:
    body["rule_config_json"] = parse_rule.rule_config_json
  if parse_rule.capability_name is not None:
    body["capability_name"] = parse_rule.capability_name
  if parse_rule.module_name is not None:
    body["module_name"] = parse_rule.module_name
  if parse_rule.service_name is not None:
    body["service_name"] = parse_rule.service_name
  return body


def _resolve_user_id(explicit: str | None) -> str:
  """Use explicit partition id when non-empty; else API key ``memory_user_id``."""
  if explicit is not None and str(explicit).strip():
    return str(explicit).strip()
  return memory_user_id()


def _memory_from_response(d: dict[str, Any] | None) -> MemoryData | None:
  if not d:
    return None
  return MemoryData(
    user_id=d["user_id"],
    data=d.get("value"),
    memory_field_name=d.get("memory_field_name"),
    retrieve_result=d.get("retrieve_result"),
  )


def _invalidate_schema_cache(event: dict[str, Any]) -> None:
  global _active_schema_catalog
  table = event.get("table", "memory_field")
  if table != "memory_field":
    return
  payload = event.get("payload") or {}
  name = event.get("memory_field_name") or payload.get("name")
  if name and name in _schema_local_cache:
    del _schema_local_cache[name]
  _active_schema_catalog = None


class Schema:
  @staticmethod
  def enable_hot_reload(*, poll_interval_ms: int | None = None) -> SchemaChangelogWatcher:
    """Subscribe to Canal-driven changelog (long-poll). Idempotent."""
    global _changelog_watcher
    if _changelog_watcher is None:
      _changelog_watcher = watch_schema_changes(
        _invalidate_schema_cache,
        auto_start=False,
      )
      if poll_interval_ms is not None:
        _changelog_watcher._poll_interval_ms = poll_interval_ms
      _changelog_watcher.start()
    return _changelog_watcher

  @staticmethod
  def disable_hot_reload() -> None:
    global _changelog_watcher
    if _changelog_watcher:
      _changelog_watcher.stop()
      _changelog_watcher = None

  @staticmethod
  def invalidate_cache(name: str | None = None) -> None:
    """Drop local schema cache entries (and list catalog when clearing all)."""
    global _active_schema_catalog
    if name is None:
      _schema_local_cache.clear()
      _active_schema_catalog = None
      return
    _schema_local_cache.pop(name, None)
    if _active_schema_catalog is not None:
      _active_schema_catalog.pop(name, None)

  @staticmethod
  def list_active_by_name(*, refresh: bool = False) -> dict[str, SchemaModel]:
    """Return active memory fields keyed by name (paginated ``GET /schema/list``)."""
    global _active_schema_catalog
    if _active_schema_catalog is not None and not refresh:
      return _active_schema_catalog
    validate_prefix_for_read()
    catalog: dict[str, SchemaModel] = {}
    offset = 0
    page_size = 200
    while True:
      r = httpx.get(
        f"{base_url()}/schema/list",
        params={"offset": offset, "limit": page_size},
        headers=headers(),
        timeout=_http_timeout(),
      )
      r.raise_for_status()
      rows = r.json().get("data") or []
      for row in rows:
        field_name = row.get("name")
        if not field_name:
          continue
        row_id = row.get("id")
        prev = catalog.get(field_name)
        if prev is None:
          catalog[field_name] = SchemaModel(name=field_name, id=row_id)
        elif row_id is not None and (prev.id is None or row_id > prev.id):
          catalog[field_name] = SchemaModel(name=field_name, id=row_id)
      if len(rows) < page_size:
        break
      offset += page_size
    _active_schema_catalog = catalog
    return catalog

  @staticmethod
  def get(name: str, mode: SEARCHENUM = SEARCHENUM.EXACT) -> SchemaModel | None:
    validate_prefix_for_read()
    if name in _schema_local_cache:
      cached = _schema_local_cache[name]
      if cached is not None:
        return cached
      del _schema_local_cache[name]
    r = httpx.get(
      f"{base_url()}/schema/get",
      params={"name": name, "mode": mode.value},
      headers=headers(),
      timeout=_http_timeout(),
    )
    r.raise_for_status()
    data = r.json().get("data")
    if not data:
      return None
    model = SchemaModel(name=data["name"], id=data.get("id"))
    _schema_local_cache[name] = model
    return model

  @staticmethod
  def getOrCreate(
    name: str,
    mode: SEARCHENUM = SEARCHENUM.EXACT,
    parse_rule: ParseRule | None = None,
    merge_rule: MergeRule | None = None,
    **kwargs: Any,
  ) -> SchemaModel:
    ensure_write_context()
    existing = Schema.get(name, mode)
    if not existing:
      existing = Schema.list_active_by_name(refresh=True).get(name)
      if existing:
        _schema_local_cache[name] = existing
    if existing:
      if merge_rule:
        Schema.ensure_merge_rule(name, merge_rule)
      return existing
    body = {"name": name, **kwargs}
    r = httpx.post(
      f"{base_url()}/schema/create",
      json=body,
      params={"dedup_mode": mode.value},
      headers=headers(),
      timeout=_http_timeout(),
    )
    if r.status_code == 409:
      Schema.invalidate_cache(name)
      existing = Schema.get(name, mode)
      if existing is None:
        existing = Schema.list_active_by_name(refresh=True).get(name)
      if existing is None:
        r.raise_for_status()
      _schema_local_cache[name] = existing
      if merge_rule:
        Schema.ensure_merge_rule(name, merge_rule)
      return existing
    r.raise_for_status()
    data = r.json()["data"]
    schema = SchemaModel(name=data["name"], id=data.get("id"))
    _schema_local_cache[name] = schema
    if _active_schema_catalog is not None:
      _active_schema_catalog[name] = schema
    if parse_rule:
      Schema.create_parse_rule(name, parse_rule)
    if merge_rule:
      Schema.ensure_merge_rule(name, merge_rule)
    return schema

  @staticmethod
  def create_parse_rule(memory_field_name: str, parse_rule: ParseRule) -> None:
    """Register an LLM parse rule for a memory field."""
    ensure_write_context()
    r = httpx.post(
      f"{base_url()}/schema/parse/create",
      json=_parse_rule_create_body(memory_field_name, parse_rule),
      headers=headers(),
      timeout=_http_timeout(),
    )
    r.raise_for_status()

  @staticmethod
  def get_parse_rule(memory_field_name: str, rule_name: str) -> dict[str, Any] | None:
    """Return active parse rule metadata, or ``None`` if missing."""
    validate_prefix_for_read()
    r = httpx.get(
      f"{base_url()}/schema/parse/get",
      params={"memory_field_name": memory_field_name, "rule_name": rule_name},
      headers=headers(),
      timeout=_http_timeout(),
    )
    r.raise_for_status()
    return r.json().get("data")

  @staticmethod
  def ensure_parse_rule(memory_field_name: str, parse_rule: ParseRule) -> str:
    """Upsert parse rule by ``rule_name`` with versioning.

    - No row for ``rule_name`` → ``POST /schema/parse/create`` (version 1).
    - Same ``prompt`` / ``llm`` / ``llm_params`` as active row → skip.
    - Any of those differ → new row with version + 1 (via create).

    Returns:
        ``"skipped"`` | ``"created"`` | ``"versioned"``.
    """
    ensure_write_context()
    existing = Schema.get_parse_rule(memory_field_name, parse_rule.rule_name)
    if existing and _llm_parse_config_matches(existing, parse_rule):
      return "skipped"
    Schema.create_parse_rule(memory_field_name, parse_rule)
    return "versioned" if existing else "created"

  @staticmethod
  def llm_parse(
    memory_field_name: str,
    rule_name: str,
    prompt: str,
    *,
    model: str | None = None,
    llm_params: dict[str, Any] | None = None,
    system: str | None = None,
    output_format: str = "text",
    ensure: bool = True,
  ) -> ParseRule:
    """Build parse rule config and optionally register it for a Schema (field).

    When ``ensure=True`` (default), calls :meth:`ensure_parse_rule`: creates
    version 1 if ``rule_name`` is new; skips when config matches; otherwise
    inserts a new row with version + 1.
    """
    ensure_write_context()
    parse_rule = ParseRule.llm_parse(
      rule_name,
      prompt,
      model=model,
      llm_params=llm_params,
      system=system,
      output_format=output_format,
    )
    if ensure:
      Schema.ensure_parse_rule(memory_field_name, parse_rule)
    return parse_rule

  @staticmethod
  def create_merge_rule(memory_field_name: str, merge_rule: MergeRule) -> None:
    """Register merge rule for ``match_method=MERGE`` (LLM fusion via merge_rule)."""
    ensure_write_context()
    r = httpx.post(
      f"{base_url()}/schema/merge/create",
      json=_merge_rule_create_body(memory_field_name, merge_rule),
      headers=headers(),
      timeout=_http_timeout(),
    )
    r.raise_for_status()

  @staticmethod
  def get_merge_rule(memory_field_name: str, rule_name: str) -> dict[str, Any] | None:
    validate_prefix_for_read()
    r = httpx.get(
      f"{base_url()}/schema/merge/get",
      params={"memory_field_name": memory_field_name, "rule_name": rule_name},
      headers=headers(),
      timeout=_http_timeout(),
    )
    r.raise_for_status()
    return r.json().get("data")

  @staticmethod
  def ensure_merge_rule(memory_field_name: str, merge_rule: MergeRule) -> str:
    """Upsert merge rule by ``rule_name`` with versioning."""
    ensure_write_context()
    existing = Schema.get_merge_rule(memory_field_name, merge_rule.rule_name)
    if existing and _llm_merge_config_matches(existing, merge_rule):
      return "skipped"
    Schema.create_merge_rule(memory_field_name, merge_rule)
    return "versioned" if existing else "created"

  @staticmethod
  def llm_merge(
    rule_name: str,
    prompt: str,
    *,
    model: str | None = None,
    llm_params: dict[str, Any] | None = None,
    system: str | None = None,
    output_format: str = "text",
    ensure: bool = False,
    memory_field_name: str | None = None,
  ) -> MergeRule:
    """Build merge rule (``{old_value}`` + ``{new_value}`` slots). Register via ``ensure=True``."""
    merge_rule = MergeRule.llm_merge(
      rule_name,
      prompt,
      model=model,
      llm_params=llm_params,
      system=system,
      output_format=output_format,
    )
    if ensure and memory_field_name:
      Schema.ensure_merge_rule(memory_field_name, merge_rule)
    return merge_rule


class Data:
  @staticmethod
  def parse(
    schema_name: str,
    parse_input: ParseInput,
    write_rule: WRITERULE | None = None,
    *,
    parse_rule_name: str | None = None,
    merge_rule_name: str | None = None,
    user_id: str | None = None,
    source: str | None = None,
    language: str | None = None,
  ) -> MemoryData:
    """Parse user text into memory; partition user defaults to ``MEMORY_ENGINE_API_KEY_PREFIX``.

    When ``write_rule`` is omitted, the API uses ``memory_field.match_method`` from MySQL.
    Pass ``WRITERULE`` only to override the field default for this request.
    ``source`` is one of ``dialogue``, ``knowledge`` (UI attribution).
    """
    uid = _resolve_user_id(user_id)
    payload: dict[str, Any] = {
      "user_id": uid,
      "memory_field_name": schema_name,
      "query": parse_input.query,
      "extra": parse_input.extra,
    }
    if language:
      payload["language"] = language
    if write_rule is not None:
      payload["write_rule"] = write_rule.value
    if parse_rule_name:
      payload["parse_rule_name"] = parse_rule_name
    if merge_rule_name:
      payload["merge_rule_name"] = merge_rule_name
    if source:
      payload["source"] = source
    r = httpx.post(
      f"{base_url()}/data/create",
      json=payload,
      headers=headers(),
      timeout=_parse_timeout(),
    )
    r.raise_for_status()
    d = r.json()["data"]
    return MemoryData(
      user_id=d["user_id"],
      data=d["value"],
      memory_field_name=d.get("memory_field_name", schema_name),
    )

  @staticmethod
  def get(
    schema_name_or_user_id: str,
    user_id_or_rule: str | RetrieveRule | None = None,
    *,
    rule: RetrieveRule | None = None,
    user_id: str | None = None,
  ) -> MemoryData | None:
    """Get memory for a field.

    - ``get(schema_name)`` — user partition = Key ``memory_user_id``.
    - ``get(schema_name, user_id=...)`` or ``get(schema_name, uid)`` — explicit partition.
    - ``get(schema_name, rule=..., user_id=...)`` — retrieve with optional partition override.
    - ``get(user_id, retrieve_rule)`` — cross-field retrieve (legacy; first arg is partition id).
    """
    memory_field_name: str | None
    uid: str
    retrieve_rule: RetrieveRule | None

    if isinstance(user_id_or_rule, RetrieveRule):
      memory_field_name = None
      uid = _resolve_user_id(user_id) if user_id else schema_name_or_user_id
      retrieve_rule = user_id_or_rule
    elif user_id_or_rule is None:
      memory_field_name = schema_name_or_user_id
      validate_prefix_for_read()
      uid = _resolve_user_id(user_id)
      retrieve_rule = rule
    else:
      memory_field_name = schema_name_or_user_id
      uid = _resolve_user_id(user_id or user_id_or_rule)
      retrieve_rule = rule

    if retrieve_rule is None and memory_field_name is not None:
      r = httpx.get(
        f"{base_url()}/data/get",
        params={"user_id": uid, "memory_field_name": memory_field_name},
        headers=headers(),
        timeout=_http_timeout(),
      )
      if r.status_code == 404:
        return None
      r.raise_for_status()
      return _memory_from_response(r.json().get("data"))

    validate_prefix_for_read()
    effective_rule = retrieve_rule or RetrieveRule(method=RETRIEVEENUM.EXACT)
    payload: dict[str, Any] = {
      "user_id": uid,
      "rule": _rule_to_body(effective_rule),
    }
    if memory_field_name is not None:
      payload["memory_field_name"] = memory_field_name

    r = httpx.post(
      f"{base_url()}/data/retrieve",
      json=payload,
      headers=headers(),
      timeout=max(_http_timeout(), 120.0),
    )
    r.raise_for_status()
    return _memory_from_response(r.json().get("data"))

  @staticmethod
  def call(
    schema_name: str,
    prompt_template: str,
    slot: str,
    mem_data: Any,
    llm: LLM | None = None,
    *,
    use_llm: bool = True,
  ) -> str:
    """Fill slot with memory data; optionally run LLM on the filled prompt."""
    validate_prefix_for_read()
    if not use_llm and llm is None:
      return prompt_template.replace(slot, str(mem_data))

    body: dict[str, Any] = {
      "memory_field_name": schema_name,
      "prompt_template": prompt_template,
      "slot": slot,
      "mem_data": mem_data,
      "use_llm": use_llm,
    }
    llm_body = _llm_to_body(llm)
    if llm_body is not None:
      body["llm"] = llm_body

    r = httpx.post(
      f"{base_url()}/data/call",
      json=body,
      headers=headers(),
      timeout=max(_http_timeout(), 120.0),
    )
    r.raise_for_status()
    return r.json()["data"]["result"]
