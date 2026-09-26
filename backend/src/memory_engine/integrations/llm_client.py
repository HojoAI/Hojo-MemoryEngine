"""OpenAI-compatible LLM client."""

from openai import AsyncOpenAI

from memory_engine.config import get_settings


def build_openai_client(
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout_seconds: float | None = None,
) -> AsyncOpenAI:
    """Build client from overrides or app settings."""
    settings = get_settings()
    timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else settings.openai_request_timeout_seconds
    )
    return AsyncOpenAI(
        base_url=base_url or settings.openai_api_base,
        api_key=api_key or settings.openai_api_key or "sk-placeholder",
        timeout=timeout,
    )


def get_openai_client() -> AsyncOpenAI:
    """Build async OpenAI client from settings."""
    return build_openai_client()


async def chat_completion(
    prompt: str,
    system: str | None = None,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    llm_params: dict | None = None,
) -> tuple[str, int, int]:
    """Run chat completion; returns text, prompt_tokens, completion_tokens."""
    client = build_openai_client(base_url=base_url, api_key=api_key)
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    settings = get_settings()
    extra = {k: v for k, v in (llm_params or {}).items() if v is not None}
    resp = await client.chat.completions.create(
        model=model or settings.openai_model,
        messages=messages,
        **extra,
    )
    choice = resp.choices[0].message.content or ""
    usage = resp.usage
    pt = usage.prompt_tokens if usage else 0
    ct = usage.completion_tokens if usage else 0
    return choice, pt, ct


async def embed_text(text: str) -> list[float]:
    """Create embedding vector."""
    return (await embed_texts([text]))[0]


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Create embedding vectors in one provider request, preserving input order."""
    if not texts:
        return []
    settings = get_settings()
    client = build_openai_client(
        base_url=settings.openai_embedding_api_base,
        api_key=settings.openai_embedding_api_key or settings.openai_api_key,
    )
    resp = await client.embeddings.create(
        model=settings.openai_embedding_model,
        input=texts,
    )
    ordered = sorted(resp.data, key=lambda item: item.index)
    return [list(item.embedding) for item in ordered]
