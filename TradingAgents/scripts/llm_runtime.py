from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def load_runtime_env() -> None:
    root = repo_root()
    for candidate in (
        root / ".env",
        root.parent / ".env",
    ):
        load_env_file(candidate)


def build_llm_kwargs(provider: str, config: dict[str, Any]) -> dict[str, Any]:
    provider = provider.lower()
    from tradingagents.llm_clients.api_key_env import get_api_key_env

    kwargs: dict[str, Any] = {}
    api_key_env = get_api_key_env(provider)
    if api_key_env:
        api_key = os.environ.get(api_key_env)
        if api_key:
            kwargs["api_key"] = api_key
        else:
            hint = f"Set {api_key_env} in .env, your shell, or the web LLM configuration panel"
            raise RuntimeError(f"{api_key_env} is not set. {hint}.")

    if config.get("temperature") is not None:
        kwargs["temperature"] = config["temperature"]
    return kwargs


def apply_llm_runtime_defaults(provider: str, model: str) -> str:
    provider = provider.lower()
    os.environ["TRADINGAGENTS_LLM_PROVIDER"] = provider
    os.environ["TRADINGAGENTS_QUICK_THINK_LLM"] = model
    os.environ["TRADINGAGENTS_DEEP_THINK_LLM"] = model
    os.environ.setdefault("TRADINGAGENTS_OUTPUT_LANGUAGE", "Vietnamese")
    return provider
