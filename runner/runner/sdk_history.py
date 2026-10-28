"""Sanitize every SDK model turn, including rejected-tool retry history."""

from dataclasses import replace

from langchain.agents.middleware import AgentMiddleware

from .redaction import redact
from .model_paths import PathIdentity


def safe_message(message):
    fields = ("content", "additional_kwargs", "response_metadata", "tool_calls",
              "invalid_tool_calls", "artifact", "name", "id", "tool_call_id")
    return message.model_copy(update={name: redact(getattr(message, name))
                                      for name in fields if hasattr(message, name)})


class SecretHistory(AgentMiddleware):
    def __init__(self):
        self.paths = PathIdentity()

    def clean_response(self, response):
        for message in response.result:
            self.paths.capture(message.content)
        return replace(response, result=[safe_message(message) for message in response.result],
                       structured_response=redact(response.structured_response))

    def wrap_model_call(self, request, handler):
        messages = [safe_message(message) for message in request.messages]
        system = safe_message(request.system_message) if request.system_message else None
        response = handler(request.override(
            messages=messages, system_message=system,
            state={**request.state, "messages": messages},
        ))
        return self.clean_response(response)

    async def awrap_model_call(self, request, handler):
        messages = [safe_message(message) for message in request.messages]
        system = safe_message(request.system_message) if request.system_message else None
        response = await handler(request.override(
            messages=messages, system_message=system,
            state={**request.state, "messages": messages},
        ))
        return self.clean_response(response)
