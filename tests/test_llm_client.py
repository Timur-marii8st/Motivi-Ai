from unittest.mock import MagicMock

from app.llm import client as client_module


def test_get_openai_client_uses_configured_proxy(monkeypatch):
    http_client = object()
    openai_client = object()
    http_factory = MagicMock(return_value=http_client)
    openai_factory = MagicMock(return_value=openai_client)

    monkeypatch.setattr(
        client_module.settings,
        "OPENROUTER_PROXY_URL",
        "http://singbox:1080",
    )
    monkeypatch.setattr(client_module, "DefaultAsyncHttpxClient", http_factory)
    monkeypatch.setattr(client_module, "AsyncOpenAI", openai_factory)

    result = client_module.get_openai_client()

    assert result is openai_client
    http_factory.assert_called_once_with(proxy="http://singbox:1080")
    openai_factory.assert_called_once_with(
        base_url=client_module.settings.OPENROUTER_BASE_URL,
        api_key=client_module.settings.OPENROUTER_API_KEY,
        http_client=http_client,
    )


def test_get_openai_client_keeps_direct_mode_when_proxy_is_empty(monkeypatch):
    openai_client = object()
    http_factory = MagicMock()
    openai_factory = MagicMock(return_value=openai_client)

    monkeypatch.setattr(client_module.settings, "OPENROUTER_PROXY_URL", "  ")
    monkeypatch.setattr(client_module, "DefaultAsyncHttpxClient", http_factory)
    monkeypatch.setattr(client_module, "AsyncOpenAI", openai_factory)

    result = client_module.get_openai_client()

    assert result is openai_client
    http_factory.assert_not_called()
    openai_factory.assert_called_once_with(
        base_url=client_module.settings.OPENROUTER_BASE_URL,
        api_key=client_module.settings.OPENROUTER_API_KEY,
    )
