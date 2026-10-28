import json

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI

from runner.config import Config
from runner.sdk import DeepAgentsAdapter, HIDDEN_TOOLS


@pytest.mark.parametrize("tool", sorted(HIDDEN_TOOLS))
def test_real_sdk_sanitizes_every_rejected_tool_retry(monkeypatch, tool):
    secret = "sdk-retry-private-value-83912"
    config = Config("deepagents", "https://example.invalid/v1", secret, "offline")
    calls = []

    def generate(_self, messages, **_kwargs):
        history = json.dumps([message.model_dump() for message in messages])
        assert secret not in history
        calls.append(history)
        if len(calls) <= 2:
            message = AIMessage(content=f"secret={secret}", additional_kwargs={"private": secret},
                                tool_calls=[{"name": tool, "args": {"value": secret},
                                             "id": f"call-{len(calls)}", "type": "tool_call"}])
        else:
            message = AIMessage(content='{"action":"finish","result_summary":"Done"}')
        return ChatResult(generations=[ChatGeneration(message=message)])

    monkeypatch.setattr(ChatOpenAI, "_generate", generate)
    adapter = DeepAgentsAdapter(config)
    assert not adapter.agent.nodes["tools"].bound._tools_by_name
    result = adapter.complete([{"role": "user", "content": f"Input {secret}"}])
    assert len(calls) == 3
    assert "[REDACTED]" in calls[1] and "[REDACTED]" in calls[2]
    assert json.loads(result)["action"] == "finish"
