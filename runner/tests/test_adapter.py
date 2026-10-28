import sys
from types import SimpleNamespace

import pytest

from runner.adapter import OpenAIAdapter
from runner.config import Config
from runner.errors import RunnerError


def test_thin_adapter_uses_configured_openai_compatible_endpoint(monkeypatch):
    observed = {}

    class Client:
        def __init__(self, **kwargs):
            observed.update(kwargs)
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def create(self, **kwargs):
            observed["request"] = kwargs
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"action":"finish"}'))])

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=Client))
    config = Config("openai-compatible", "https://compatible.example/v1", "private-key", "model")
    messages = [{"role": "user", "content": "request"}]
    assert OpenAIAdapter(config).complete(messages) == '{"action":"finish"}'
    assert observed["base_url"] == config.base_url
    assert observed["api_key"] == config.api_key
    assert observed["max_retries"] == 0
    assert observed["request"]["model"] == "model"
    assert observed["request"]["messages"] == messages


def test_api_errors_do_not_expose_response_or_credentials(monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("Authorization: private-key; response body")

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=fail))
    with pytest.raises(RunnerError) as failure:
        OpenAIAdapter(Config("openai-compatible", api_key="private-key")).complete([])
    assert str(failure.value) == "OpenAI-compatible API request failed"
