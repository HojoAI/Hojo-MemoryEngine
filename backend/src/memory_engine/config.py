"""Application settings."""

import logging
import re
from functools import cached_property, lru_cache
from urllib.parse import quote_plus, urlparse, urlunparse

from typing import Any

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_PLACEHOLDER_DSN = re.compile(r"<(?:user|password)[^>]*>", re.IGNORECASE)


def _mongodb_strip_userinfo(rest: str) -> str:
    """Remove user:pass@ from URI body while keeping replica-set host list and query."""
    slash = rest.find("/")
    query = rest.find("?")
    end = len(rest)
    if slash >= 0:
        end = min(end, slash)
    if query >= 0:
        end = min(end, query)
    hosts = rest[:end]
    tail = rest[end:]
    if "@" in hosts:
        hosts = hosts.split("@", 1)[1]
    return f"{hosts}{tail}"


class SuppressHealthAccessLogFilter(logging.Filter):
    """Drop uvicorn access log lines for Kubernetes / load-balancer health probes."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "/health" not in record.getMessage()


class Settings(BaseSettings):
    """Environment-backed configuration."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="before")
    @classmethod
    def _ignore_empty_env_strings(cls, data: Any) -> Any:
        """K8s/CI often inject unset template vars as ''; treat as missing."""
        if not isinstance(data, dict):
            return data
        return {key: value for key, value in data.items() if value != ""}

    app_debug: bool = True
    app_disable_auth: bool = False

    # Connection params: no in-code defaults — set via K8s env / .env (see .env.example).
    mysql_host: str = ""
    mysql_port: int = 3306
    mysql_user: str = ""
    mysql_password: str = ""
    mysql_database: str = ""

    redis_url: str = ""
    redis_port: int = 6379
    redis_password: str = ""
    redis_database: int = 0
    redis_key_prefix: str = "memory_engine"
    redis_socket_timeout_ms: int = 3000

    # Paste full MongoDB URI (env MONGODB_DSN); overrides URI + user/password.
    mongodb_dsn_override: str = Field(default="", validation_alias="MONGODB_DSN")
    mongodb_uri: str = ""
    mongodb_port: int = 27017
    mongodb_user: str = ""
    mongodb_password: str = ""
    mongodb_auth_source: str = Field(
        default="admin",
        validation_alias=AliasChoices(
            "MONGODB_AUTH_SOURCE",
            "MONGODB_AUTH_DB",
            "MONGODB_AUTH",
        ),
    )
    mongodb_database: str = ""

    @field_validator(
        "mongodb_user",
        "mongodb_password",
        "mongodb_uri",
        "mongodb_dsn_override",
        "mongodb_auth_source",
        mode="before",
    )
    @classmethod
    def _strip_mongo_env(cls, value: object) -> object:
        """Trim whitespace/quotes from CI-injected Mongo env vars."""
        if isinstance(value, str):
            return value.strip().strip('"').strip("'")
        return value

    qdrant_url: str = ""
    qdrant_api_key: str = Field(default="", validation_alias="QDRANT_API_KEY")
    qdrant_timeout_seconds: float = Field(default=5.0, validation_alias="QDRANT_TIMEOUT_SECONDS")
    qdrant_circuit_breaker_seconds: float = Field(
        default=60.0,
        validation_alias="QDRANT_CIRCUIT_BREAKER_SECONDS",
    )

    mysql_pool_size: int = Field(default=10, validation_alias="MYSQL_POOL_SIZE")
    mysql_max_overflow: int = Field(default=20, validation_alias="MYSQL_MAX_OVERFLOW")
    mysql_pool_timeout_seconds: float = Field(
        default=30.0,
        validation_alias="MYSQL_POOL_TIMEOUT_SECONDS",
    )

    @field_validator("qdrant_url", mode="before")
    @classmethod
    def _normalize_qdrant_url(cls, value: object) -> object:
        """Qdrant client expects API root (port 6333), not the /dashboard UI path."""
        if not isinstance(value, str):
            return value
        url = value.strip().strip('"').strip("'").rstrip("/")
        if url.endswith("/dashboard"):
            url = url[: -len("/dashboard")]
        return url

    def qdrant_startup_diag(self) -> str:
        """Safe one-line Qdrant config summary (no secrets)."""
        if not self.qdrant_url:
            return "url=(empty)"
        parsed = urlparse(self.qdrant_url)
        host = parsed.netloc or parsed.path or "?"
        return (
            f"url={parsed.scheme or 'http'}://{host} "
            f"api_key_set={bool(self.qdrant_api_key)} "
            f"timeout_s={self.qdrant_timeout_seconds}"
        )

    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    # Embeddings may be served by a different OpenAI-compatible provider than
    # chat completions (for example, an Ofox embedding route). Empty endpoint
    # and key values intentionally fall back to the primary OpenAI settings.
    openai_embedding_base_url: str = ""
    openai_embedding_api_key: str = ""
    openai_embedding_model: str = "text-embedding-3-small"
    openai_request_timeout_seconds: float = 60.0

    # Agent Memory Leaderboard adapter. Raw evidence remains authoritative;
    # optional gpt-4o-mini calls add retrieval terms and rerank candidates.
    aml_require_vector_index: bool = Field(
        default=True, validation_alias="AML_REQUIRE_VECTOR_INDEX"
    )
    aml_candidate_limit: int = Field(
        default=400, ge=100, le=5000, validation_alias="AML_CANDIDATE_LIMIT"
    )
    aml_max_user_units: int = Field(
        default=10000, ge=100, le=100000, validation_alias="AML_MAX_USER_UNITS"
    )
    aml_rrf_k: int = Field(default=60, ge=1, le=1000, validation_alias="AML_RRF_K")
    aml_vector_weight: float = Field(
        default=1.0, ge=0.0, le=10.0, validation_alias="AML_VECTOR_WEIGHT"
    )
    aml_lexical_weight: float = Field(
        default=1.0, ge=0.0, le=10.0, validation_alias="AML_LEXICAL_WEIGHT"
    )
    aml_option_weight: float = Field(
        default=0.35, ge=0.0, le=10.0, validation_alias="AML_OPTION_WEIGHT"
    )
    aml_exact_match_enabled: bool = Field(default=True, validation_alias="AML_EXACT_MATCH_ENABLED")
    aml_exact_match_weight: float = Field(
        default=0.45, ge=0.0, le=10.0, validation_alias="AML_EXACT_MATCH_WEIGHT"
    )
    aml_temporal_ranking_enabled: bool = Field(
        default=True, validation_alias="AML_TEMPORAL_RANKING_ENABLED"
    )
    aml_temporal_weight: float = Field(
        default=0.35, ge=0.0, le=10.0, validation_alias="AML_TEMPORAL_WEIGHT"
    )
    aml_aggregation_weight: float = Field(
        default=0.35, ge=0.0, le=10.0, validation_alias="AML_AGGREGATION_WEIGHT"
    )
    aml_user_evidence_boost: float = Field(
        default=0.06, ge=0.0, le=0.5, validation_alias="AML_USER_EVIDENCE_BOOST"
    )
    aml_assistant_evidence_penalty: float = Field(
        default=0.12,
        ge=0.0,
        le=0.5,
        validation_alias="AML_ASSISTANT_EVIDENCE_PENALTY",
    )
    aml_neighbor_evidence_enabled: bool = Field(
        default=True, validation_alias="AML_NEIGHBOR_EVIDENCE_ENABLED"
    )
    aml_neighbor_seed_limit: int = Field(
        default=8, ge=1, le=100, validation_alias="AML_NEIGHBOR_SEED_LIMIT"
    )
    aml_neighbor_window: int = Field(default=1, ge=1, le=5, validation_alias="AML_NEIGHBOR_WINDOW")
    aml_neighbor_weight: float = Field(
        default=0.35, ge=0.0, le=10.0, validation_alias="AML_NEIGHBOR_WEIGHT"
    )
    # Compound questions benefit from independent semantic recall per facet.
    # The original query remains facet zero, and only explicit conjunctions
    # are expanded so ordinary BEAM/PersonaMem traffic keeps the legacy path.
    memory_retrieve_multifacet_enabled: bool = Field(
        default=True, validation_alias="MEMORY_RETRIEVE_MULTIFACET_ENABLED"
    )
    memory_retrieve_multifacet_max_queries: int = Field(
        default=3, ge=1, le=6, validation_alias="MEMORY_RETRIEVE_MULTIFACET_MAX_QUERIES"
    )
    memory_retrieve_multifacet_candidate_limit: int = Field(
        default=30,
        ge=5,
        le=100,
        validation_alias="MEMORY_RETRIEVE_MULTIFACET_CANDIDATE_LIMIT",
    )
    memory_retrieve_multifacet_max_items: int = Field(
        default=12, ge=1, le=50, validation_alias="MEMORY_RETRIEVE_MULTIFACET_MAX_ITEMS"
    )
    # Historical/superseded claims require a separate precision-tuned rollout.
    # Keep them off by default so ordinary retrieval remains current-only.
    memory_retrieve_historical_enabled: bool = Field(
        default=False, validation_alias="MEMORY_RETRIEVE_HISTORICAL_ENABLED"
    )
    # Preserve explicit priced facts when answering a scoped financial
    # aggregation question (for example, total bike expenses).
    memory_retrieve_monetary_evidence_boost: float = Field(
        default=0.18,
        ge=0.0,
        le=0.5,
        validation_alias="MEMORY_RETRIEVE_MONETARY_EVIDENCE_BOOST",
    )
    # Keep concrete operands (amounts, durations, and counts) available for
    # aggregation questions after the hybrid candidate merge.
    memory_retrieve_aggregation_evidence_boost: float = Field(
        default=0.12,
        ge=0.0,
        le=0.5,
        validation_alias="MEMORY_RETRIEVE_AGGREGATION_EVIDENCE_BOOST",
    )
    # When both user and assistant turns are indexed, favor first-person user
    # evidence. Assistant advice remains retrievable but cannot crowd out the
    # factual turn that it answered.
    memory_retrieve_user_evidence_boost: float = Field(
        default=0.06,
        ge=0.0,
        le=0.5,
        validation_alias="MEMORY_RETRIEVE_USER_EVIDENCE_BOOST",
    )
    memory_retrieve_assistant_evidence_penalty: float = Field(
        default=0.12,
        ge=0.0,
        le=0.5,
        validation_alias="MEMORY_RETRIEVE_ASSISTANT_EVIDENCE_PENALTY",
    )
    # Counting/aggregation questions are especially vulnerable to top-k
    # semantic noise. Re-rank a bounded shortlist with the configured chat
    # model so hypothetical and third-party examples do not become operands.
    memory_retrieve_aggregation_rerank_enabled: bool = Field(
        default=False, validation_alias="MEMORY_RETRIEVE_AGGREGATION_RERANK_ENABLED"
    )
    aml_session_diversity_enabled: bool = Field(default=True, validation_alias="AML_SESSION_DIVERSITY_ENABLED")
    aml_session_max_items: int = Field(default=4, ge=1, le=100, validation_alias="AML_SESSION_MAX_ITEMS")
    aml_llm_model: str = Field(default="gpt-4o-mini", validation_alias="AML_LLM_MODEL")
    aml_llm_add_augment_enabled: bool = Field(
        default=False, validation_alias="AML_LLM_ADD_AUGMENT_ENABLED"
    )
    aml_llm_rerank_enabled: bool = Field(default=False, validation_alias="AML_LLM_RERANK_ENABLED")
    aml_llm_required: bool = Field(default=False, validation_alias="AML_LLM_REQUIRED")
    aml_llm_rerank_candidates: int = Field(
        default=50, ge=5, le=100, validation_alias="AML_LLM_RERANK_CANDIDATES"
    )
    # Aggregation questions need several independent operands.  Allow the
    # selector to keep more than the ordinary profile item cap, while the
    # request's top_k and max_tokens remain hard safety limits.
    memory_retrieve_aggregation_max_items: int = Field(
        default=12, ge=1, le=50, validation_alias="MEMORY_RETRIEVE_AGGREGATION_MAX_ITEMS"
    )
    memory_retrieve_aggregation_max_claim_chars: int = Field(
        default=1200,
        ge=200,
        le=5000,
        validation_alias="MEMORY_RETRIEVE_AGGREGATION_MAX_CLAIM_CHARS",
    )
    # A top-k made entirely from one long session is brittle for cross-session
    # questions. Prefer a bounded number of candidates from each evidence
    # group, then fall back to the remaining ranked candidates if necessary.
    memory_retrieve_session_diversity_enabled: bool = Field(
        default=True, validation_alias="MEMORY_RETRIEVE_SESSION_DIVERSITY_ENABLED"
    )
    memory_retrieve_session_max_items: int = Field(
        default=2, ge=1, le=20, validation_alias="MEMORY_RETRIEVE_SESSION_MAX_ITEMS"
    )
    # Claims emitted from the same source event/session often contain an
    # answer and its qualifier in separate records. Expand only around the
    # strongest seeds and keep the lookup tightly bounded.
    memory_retrieve_evidence_neighbor_enabled: bool = Field(
        default=True, validation_alias="MEMORY_RETRIEVE_EVIDENCE_NEIGHBOR_ENABLED"
    )
    memory_retrieve_evidence_neighbor_seed_limit: int = Field(
        default=4, ge=1, le=20, validation_alias="MEMORY_RETRIEVE_EVIDENCE_NEIGHBOR_SEED_LIMIT"
    )
    memory_retrieve_evidence_neighbor_limit: int = Field(
        default=16, ge=1, le=100, validation_alias="MEMORY_RETRIEVE_EVIDENCE_NEIGHBOR_LIMIT"
    )
    # Opt-in, ID-only diagnostics for tracking evidence through recall, policy,
    # ranking, and the final item/token budget. Never log claim text or vectors.
    memory_retrieve_diagnostics_enabled: bool = Field(
        default=False, validation_alias="MEMORY_RETRIEVE_DIAGNOSTICS_ENABLED"
    )
    memory_retrieve_diagnostics_max_ids: int = Field(
        default=200, ge=1, le=1000, validation_alias="MEMORY_RETRIEVE_DIAGNOSTICS_MAX_IDS"
    )
    openai_request_timeout_seconds: float = 60.0

    deepseek_v4_pro_base_url: str = "https://api.deepseek.com"
    deepseek_v4_pro_api_key: str = ""
    deepseek_v4_pro_model: str = "deepseek-v4-pro"
    deepseek_v4_pro_request_timeout_seconds: float = 60.0

    kafka_bootstrap_servers: str = "127.0.0.1:9092"
    kafka_schema_changelog_topic: str = "schema-changelog"
    kafka_canal_topic: str = "canal-memory-engine"
    kafka_billing_events_topic: str = "billing-events"
    kafka_consumers_enabled: bool = False
    kafka_publish_enabled: bool = True

    canal_enabled: bool = False
    canal_mysql_database: str = "memory_engine"
    canal_forward_to_schema_topic: bool = True
    schema_sync_api_publish: bool = True
    schema_changelog_dedup_ttl_seconds: int = 300

    qdrant_async_index: bool = True
    memory_runtime_monitor_enabled: bool = Field(default=False, validation_alias="MEMORY_RUNTIME_MONITOR_ENABLED")
    memory_v1_dual_write_enabled: bool = Field(
        default=False, validation_alias="MEMORY_V1_DUAL_WRITE_ENABLED"
    )
    memory_claim_min_confidence: float = Field(
        default=0.8, ge=0.0, le=1.0, validation_alias="MEMORY_CLAIM_MIN_CONFIDENCE"
    )
    memory_v2_bundle_ttl_seconds: int = Field(
        default=3600, ge=60, validation_alias="MEMORY_V2_BUNDLE_TTL_SECONDS"
    )
    memory_candidate_oss_timeout_seconds: float = Field(
        default=15.0,
        gt=0,
        validation_alias="MEMORY_CANDIDATE_OSS_TIMEOUT_SECONDS",
    )
    memory_candidate_oss_max_bytes: int = Field(
        default=20 * 1024 * 1024,
        ge=1,
        validation_alias="MEMORY_CANDIDATE_OSS_MAX_BYTES",
    )
    memory_candidate_oss_allowed_hosts: str = Field(
        default="",
        validation_alias="MEMORY_CANDIDATE_OSS_ALLOWED_HOSTS",
        description="Comma-separated extra OSS hostnames or domain suffixes.",
    )
    billing_enforce_quota: bool = False
    governance_auto_apply_threshold: float = 0.9

    admin_bootstrap_secret: str = ""
    # Service-to-service Bearer (legacy; /data/user/* now use H5 headers).
    service_bearer_token: str = Field(
        default="",
        validation_alias="MEMORY_ENGINE_SERVICE_BEARER_TOKEN",
    )
    # Open-source end-user API settings; H5 aliases keep deployments compatible.
    user_token_skip_validate: bool = Field(default=False, validation_alias=AliasChoices("USER_TOKEN_SKIP_VALIDATE", "H5_SKIP_TOKEN_VALIDATE"))
    user_token_redis_key_template: str = Field(default="", validation_alias=AliasChoices("USER_TOKEN_REDIS_KEY_TEMPLATE", "H5_USER_TOKEN_REDIS_KEY_TEMPLATE"))
    user_account_validate_url: str = Field(default="", validation_alias=AliasChoices("USER_ACCOUNT_VALIDATE_URL", "H5_ACCOUNT_VALIDATE_URL"))
    user_account_validate_timeout_seconds: float = 5.0
    end_user_default_tenant_id: int | None = Field(default=1, validation_alias=AliasChoices("END_USER_DEFAULT_TENANT_ID", "H5_DEFAULT_TENANT_ID"))
    end_user_default_org_id: int = Field(default=0, validation_alias=AliasChoices("END_USER_DEFAULT_ORG_ID", "H5_DEFAULT_ORG_ID"))

    memory_export_email_max_items: int = Field(
        default=5000,
        validation_alias="MEMORY_EXPORT_EMAIL_MAX_ITEMS",
    )
    smtp_host: str = Field(default="", validation_alias="SMTP_HOST")
    smtp_port: int = Field(default=587, validation_alias="SMTP_PORT")
    smtp_user: str = Field(default="", validation_alias="SMTP_USER")
    smtp_password: str = Field(default="", validation_alias="SMTP_PASSWORD")
    smtp_from: str = Field(default="", validation_alias="SMTP_FROM")
    smtp_use_tls: bool = Field(default=True, validation_alias="SMTP_USE_TLS")
    onboarding_allow_self_register: bool = True

    temporal_host: str = "127.0.0.1:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "memory-engine-main"

    supabase_url: str = ""
    supabase_anon_key: str = ""

    @property
    def redis_dsn(self) -> str:
        """Redis URL with port, password, and logical database from settings."""
        raw = self.redis_url.strip()
        if not raw:
            return ""
        # Bare hostname (no redis://) is parsed as path by urlparse → would fall back to 127.0.0.1
        parsed = urlparse(raw if "://" in raw else f"redis://{raw}")
        scheme = parsed.scheme or "redis"
        host = parsed.hostname or ""
        port = self.redis_port
        password = self.redis_password or (parsed.password or "")
        if password:
            userinfo = f":{quote_plus(password, safe='')}@"
        else:
            userinfo = ""
        netloc = f"{userinfo}{host}:{port}"
        return urlunparse((scheme, netloc, f"/{self.redis_database}", "", "", ""))

    @cached_property
    def _resolved_mongodb_dsn_override(self) -> str:
        """Non-empty MONGODB_DSN only when not a console template placeholder."""
        raw = self.mongodb_dsn_override.strip()
        if not raw:
            return ""
        if _PLACEHOLDER_DSN.search(raw):
            logger.warning(
                "MONGODB_DSN still contains <user>/<password> placeholders; "
                "ignoring it — use real credentials or unset MONGODB_DSN and set "
                "MONGODB_URI + MONGODB_USER + MONGODB_PASSWORD instead."
            )
            return ""
        return raw

    @property
    def mongodb_dsn_mode(self) -> str:
        """How mongodb_dsn was built (for startup logs)."""
        if self._resolved_mongodb_dsn_override:
            return "MONGODB_DSN"
        if self.mongodb_user or self.mongodb_password:
            return "MONGODB_URI+MONGODB_USER+MONGODB_PASSWORD"
        raw = self.mongodb_uri.strip()
        if raw and raw.split("://", 1)[-1].split("/")[0].count("@") >= 1:
            return "MONGODB_URI (credentials only in URI)"
        return "MONGODB_URI (no credentials)"

    @property
    def mongodb_dsn(self) -> str:
        """MongoDB URI; inject user/password without breaking replica-set host lists."""
        override = self._resolved_mongodb_dsn_override
        if override:
            return override
        user = self.mongodb_user or ""
        password = self.mongodb_password or ""
        raw = self.mongodb_uri.strip()
        if not raw:
            return ""
        if "://" in raw:
            scheme, _, rest = raw.partition("://")
        else:
            scheme, rest = "mongodb", raw
        # A plain single host uses MONGODB_PORT unless the URI already specifies one.
        host_part = rest.split("/", 1)[0].split("?", 1)[0].split("@")[-1]
        if host_part and "," not in host_part and ":" not in host_part and not host_part.startswith("["):
            rest = rest.replace(host_part, f"{host_part}:{self.mongodb_port}", 1)
        if user or password:
            rest = _mongodb_strip_userinfo(rest)
            if user:
                userinfo = f"{quote_plus(user)}:{quote_plus(password, safe='')}@"
            else:
                userinfo = f":{quote_plus(password, safe='')}@"
            dsn = f"{scheme}://{userinfo}{rest}"
        else:
            dsn = f"{scheme}://{rest}"
        if (user or password) and "authSource=" not in dsn and self.mongodb_auth_source:
            sep = "&" if "?" in dsn else "?"
            dsn = f"{dsn}{sep}authSource={quote_plus(self.mongodb_auth_source, safe='')}"
        return dsn

    @property
    def mongodb_has_credentials(self) -> bool:
        """Whether the effective DSN includes credentials."""
        if self._resolved_mongodb_dsn_override:
            body = self._resolved_mongodb_dsn_override.split("://", 1)[-1]
            return body.split("/")[0].count("@") >= 1
        if self.mongodb_user or self.mongodb_password:
            return True
        raw = self.mongodb_uri.strip()
        return bool(raw) and raw.split("://", 1)[-1].split("/")[0].count("@") >= 1

    def mongodb_startup_diag(self) -> str:
        """Safe one-line summary for startup logs (no secrets)."""
        if self._resolved_mongodb_dsn_override:
            return "source=MONGODB_DSN creds_in_dsn=true"
        parsed = urlparse(self.mongodb_dsn)
        hosts = parsed.netloc.split("@")[-1] if parsed.netloc else "?"
        pwd = self.mongodb_password
        pwd_hint = f"len={len(pwd)}" if pwd else "len=0"
        if pwd and "%" in pwd:
            pwd_hint += " (contains '%' — use plaintext password, not URL-encoded)"
        return (
            f"source={self.mongodb_dsn_mode} user={self.mongodb_user or '(empty)'} "
            f"password_set={bool(pwd)} {pwd_hint} creds_in_dsn={self.mongodb_has_credentials} "
            f"authSource={self.mongodb_auth_source} hosts={hosts} db={self.mongodb_database}"
        )

    @property
    def mysql_dsn(self) -> str:
        """Async SQLAlchemy DSN (password URL-encoded)."""
        user = quote_plus(self.mysql_user)
        password = quote_plus(self.mysql_password)
        return (
            f"mysql+aiomysql://{user}:{password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
        )

    @property
    def openai_api_base(self) -> str:
        """Normalize OpenAI-compatible base URL to .../v1."""
        url = self.openai_base_url.rstrip("/")
        suffix = "/chat/completions"
        if url.endswith(suffix):
            url = url[: -len(suffix)]
        return url

    @property
    def openai_embedding_api_base(self) -> str:
        """Normalize the optional embedding provider base URL."""
        url = (self.openai_embedding_base_url or self.openai_base_url).rstrip("/")
        suffix = "/embeddings"
        if url.endswith(suffix):
            url = url[: -len(suffix)]
        return url

    def redis_key(self, *parts: str) -> str:
        """Build a namespaced Redis key under configured prefix."""
        prefix = self.redis_key_prefix.strip(":").rstrip(":")
        body = ":".join(str(p) for p in parts if p != "")
        return f"{prefix}:{body}" if body else prefix


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
