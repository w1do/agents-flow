"""Deep Agents SDK adapter restricted to the runner's JSON action protocol."""

import contextlib
import io

from .errors import RunnerError
from .redaction import redact

HIDDEN_TOOLS = {
    "ls", "read_file", "write_file", "edit_file", "delete", "glob", "grep",
    "execute", "write_todos", "task",
}


class DeepAgentsAdapter:
    def __init__(self, config):
        try:
            from deepagents import (
                GeneralPurposeSubagentProfile,
                HarnessProfile,
                create_deep_agent,
                register_harness_profile,
            )
            from langchain_openai import ChatOpenAI
            from .sdk_history import SecretHistory
        except ImportError:
            raise RunnerError("Install the deepagents provider dependencies") from None
        register_harness_profile(
            "openai",
            HarnessProfile(
                excluded_tools=HIDDEN_TOOLS,
                general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
            ),
        )
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                model = ChatOpenAI(
                    model=config.model, api_key=config.api_key, base_url=config.base_url,
                    timeout=60, max_retries=0,
                )
                self.history = SecretHistory()
                self.agent = create_deep_agent(model=model, tools=[], middleware=[self.history])
                tool_node = getattr(self.agent, "nodes", {}).get("tools")
                if tool_node is not None:
                    self.sdk_tool_names = frozenset(tool_node.bound._tools_by_name)
                    tool_node.bound._tools_by_name.clear()
                    tool_node.bound._injected_args.clear()
                else:
                    self.sdk_tool_names = frozenset()
        except Exception:
            raise RunnerError("Deep Agents could not initialize the configured model") from None

    def complete(self, messages):
        self.history.paths.pending = None
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                result = self.agent.invoke({"messages": redact(messages)}, config={"recursion_limit": 40})
            message = result["messages"][-1]
            content = message.content
        except Exception:
            raise RunnerError("Deep Agents model request failed") from None
        if not isinstance(content, str) or len(content.encode()) > 512 * 1024:
            raise RunnerError("Deep Agents response must contain bounded JSON text")
        return self.history.paths.reply(content)
