from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class EndpointConfig:
    name: str
    base_url: str
    model: str
    api_key_env: str
    api_key: str = field(default="", init=False)
    enabled: bool = field(default=True, init=False)

    def __post_init__(self) -> None:
        self.api_key = os.environ.get(self.api_key_env, "")
        self.enabled = bool(self.api_key)


@dataclass
class TestConfig:
    runs_per_case: int = 5
    temperature: float = 0.0
    max_tokens: int = 1024
    timeout: float = 60.0


def default_endpoints() -> list[EndpointConfig]:
    return [
        EndpointConfig(
            name="opencode-go",
            base_url="https://opencode.ai/zen/go/v1",
            model=os.environ.get("OPENCODE_GO_MODEL", "deepseek-v4-flash"),
            api_key_env="OPENCODE_GO_API_KEY",
        ),
        EndpointConfig(
            name="deepseek-official",
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
            model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
            api_key_env="DEEPSEEK_API_KEY",
        ),
    ]
