"""The sole network boundary: an OpenAI-compatible Chat Completions client."""

import contextlib
import io

from .errors import RunnerError
from .redaction import redact


class OpenAIAdapter:
    def __init__(self, config):
        self.config = config

    def complete(self, messages):
        try:
            from openai import OpenAI
        except ImportError:
            raise RunnerError("Install the openai-compatible extra to use this provider") from None
        try:
            # Third-party diagnostics must not pollute the harness protocol or logs.
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with OpenAI(api_key=self.config.api_key, base_url=self.config.base_url,
                            timeout=60, max_retries=0) as client:
                    response = client.chat.completions.create(
                        model=self.config.model, messages=redact(messages),
                        response_format={"type": "json_object"},
                    )
            content = response.choices[0].message.content
        except Exception:
            raise RunnerError("OpenAI-compatible API request failed") from None
        if not isinstance(content, str) or len(content.encode()) > 512 * 1024:
            raise RunnerError("API response must contain bounded JSON text")
        return content
