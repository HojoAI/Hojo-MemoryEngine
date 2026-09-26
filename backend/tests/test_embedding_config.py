from memory_engine.config import Settings


def test_embedding_settings_fall_back_to_primary_provider() -> None:
    settings = Settings(
        openai_base_url="https://chat.example/v1",
        openai_api_key="chat-key",
    )

    assert settings.openai_embedding_api_base == "https://chat.example/v1"
    assert settings.openai_embedding_model == "text-embedding-3-small"


def test_embedding_settings_support_dedicated_provider() -> None:
    settings = Settings(
        openai_base_url="https://chat.example/v1",
        openai_embedding_base_url="https://api.ofox.io/v1/embeddings",
        openai_embedding_api_key="embedding-key",
        openai_embedding_model="google/gemini-embedding-2-preview",
    )

    assert settings.openai_embedding_api_base == "https://api.ofox.io/v1"
    assert settings.openai_embedding_api_key == "embedding-key"
    assert settings.openai_embedding_model == "google/gemini-embedding-2-preview"
