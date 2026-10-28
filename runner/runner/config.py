"""Environment-only provider configuration; constructing it never uses the network."""

import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .errors import RunnerError
from .envfile import read_env_file
from .secrets import SecretSnapshot, install


@dataclass(frozen=True)
class Config:
    provider: str = "stub"
    base_url: str = field(default="https://api.openai.com/v1", repr=False)
    api_key: str = field(default="", repr=False)
    model: str = ""
    secrets: SecretSnapshot = field(default_factory=SecretSnapshot, repr=False)

    def __post_init__(self):
        snapshot = SecretSnapshot(self.secrets.values | ({self.api_key} if self.api_key else set()))
        object.__setattr__(self, "secrets", snapshot)
        install(snapshot)

    @classmethod
    def from_env(cls, env=None):
        env = dict(os.environ if env is None else env)
        # Exactly one file read supplies both the provider and the snapshot.
        private = read_env_file(env)
        snapshot = SecretSnapshot.capture(env, private)
        install(snapshot)
        provider = env.get("AGENT_PROVIDER", "stub").strip()
        if provider not in {"stub", "deepagents", "openai-compatible"}:
            raise RunnerError("AGENT_PROVIDER must be stub, deepagents or openai-compatible")
        if provider == "stub":
            return cls(secrets=snapshot)
        env = private | env
        key = env.get("OPENAI_API_KEY", "").strip()
        model = (env.get("OPENAI_MODEL") or env.get("AGENT_MODEL") or "").strip()
        url = env.get("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError:
            raise RunnerError("OPENAI_BASE_URL is invalid") from None
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or any(c.isspace() for c in url) or port == 0):
            raise RunnerError("OPENAI_BASE_URL must be an HTTP(S) URL without credentials")
        if not key or any(c.isspace() for c in key):
            raise RunnerError("OPENAI_API_KEY is required and must not contain whitespace")
        if not model:
            raise RunnerError("OPENAI_MODEL or AGENT_MODEL is required")
        return cls(provider, url.rstrip("/"), key, model, snapshot)

    def reload(self, env=None):
        """Explicit rotation returns a new config and installs its new snapshot."""
        return type(self).from_env(env)
