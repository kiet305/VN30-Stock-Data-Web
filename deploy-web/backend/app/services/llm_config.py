from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.schemas import LlmConfigResponse, LlmConfigUpdate, LlmProviderOption


PROVIDER_OPTIONS: dict[str, dict[str, str | None]] = {
    "openai": {"label": "OpenAI", "key_env": "OPENAI_API_KEY", "default_model": "gpt-4.1"},
    "anthropic": {"label": "Anthropic", "key_env": "ANTHROPIC_API_KEY", "default_model": "claude-sonnet-4-5"},
    "google": {"label": "Google Gemini", "key_env": "GOOGLE_API_KEY", "default_model": "gemini-2.5-pro"},
    "azure": {"label": "Azure OpenAI", "key_env": "AZURE_OPENAI_API_KEY", "default_model": "gpt-4.1"},
    "deepseek": {"label": "DeepSeek", "key_env": "DEEPSEEK_API_KEY", "default_model": "deepseek-chat"},
    "qwen": {"label": "Qwen", "key_env": "DASHSCOPE_API_KEY", "default_model": "qwen-plus"},
    "qwen-cn": {"label": "Qwen CN", "key_env": "DASHSCOPE_CN_API_KEY", "default_model": "qwen-plus"},
    "openrouter": {"label": "OpenRouter", "key_env": "OPENROUTER_API_KEY", "default_model": "openai/gpt-4.1"},
    "xai": {"label": "xAI", "key_env": "XAI_API_KEY", "default_model": "grok-4"},
    "glm": {"label": "GLM", "key_env": "ZHIPU_API_KEY", "default_model": "glm-4.5"},
    "minimax": {"label": "MiniMax", "key_env": "MINIMAX_API_KEY", "default_model": "MiniMax-M1"},
    "ollama": {"label": "Ollama local", "key_env": None, "default_model": "llama3.1"},
}


@dataclass(frozen=True)
class LlmRuntimeConfig:
    provider: str
    model: str
    key_env: str | None
    api_key: str | None


def _config_path() -> Path:
    _reports_dir, logs_dir = get_settings().analysis_report_dirs
    return logs_dir / "llm_config.json"


def _provider_options() -> list[LlmProviderOption]:
    return [
        LlmProviderOption(
            provider=provider,
            label=str(item["label"]),
            key_env=item["key_env"],
            default_model=str(item["default_model"]),
        )
        for provider, item in PROVIDER_OPTIONS.items()
    ]


def _read_config() -> dict[str, Any]:
    path = _config_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_config(payload: dict[str, Any]) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def _normalize_provider(value: str | None) -> str:
    provider = (value or get_settings().tradingagents_provider or "openai").strip().lower()
    return provider if provider in PROVIDER_OPTIONS else "openai"


def _default_model(provider: str) -> str:
    return str(PROVIDER_OPTIONS.get(provider, PROVIDER_OPTIONS["openai"])["default_model"])


def _mask_key(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "••••"
    return f"{value[:4]}••••{value[-4:]}"


def _updated_at(payload: dict[str, Any]) -> datetime | None:
    value = payload.get("updated_at")
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def get_llm_runtime_config() -> LlmRuntimeConfig:
    settings = get_settings()
    payload = _read_config()
    provider = _normalize_provider(payload.get("provider") if isinstance(payload.get("provider"), str) else None)
    configured_model = payload.get("model")
    model = configured_model.strip() if isinstance(configured_model, str) and configured_model.strip() else settings.tradingagents_model
    if not model:
        model = _default_model(provider)

    key_env = PROVIDER_OPTIONS[provider]["key_env"]
    saved_keys = payload.get("api_keys")
    saved_key = saved_keys.get(key_env) if isinstance(saved_keys, dict) and key_env else None
    api_key = saved_key.strip() if isinstance(saved_key, str) and saved_key.strip() else None
    if not api_key and key_env:
        env_key = os.environ.get(str(key_env))
        api_key = env_key.strip() if env_key else None

    return LlmRuntimeConfig(provider=provider, model=model, key_env=key_env, api_key=api_key)


def get_llm_config() -> LlmConfigResponse:
    payload = _read_config()
    runtime = get_llm_runtime_config()
    return LlmConfigResponse(
        provider=runtime.provider,
        model=runtime.model,
        key_env=runtime.key_env,
        has_api_key=bool(runtime.api_key) or runtime.key_env is None,
        api_key_preview=_mask_key(runtime.api_key),
        updated_at=_updated_at(payload),
        source=str(_config_path()),
        providers=_provider_options(),
    )


def update_llm_config(update: LlmConfigUpdate) -> LlmConfigResponse:
    payload = _read_config()
    provider = _normalize_provider(update.provider or payload.get("provider"))
    model = (update.model or "").strip()
    if not model:
        existing_model = payload.get("model")
        model = existing_model.strip() if isinstance(existing_model, str) and existing_model.strip() else _default_model(provider)

    key_env = PROVIDER_OPTIONS[provider]["key_env"]
    saved_keys = payload.get("api_keys")
    api_keys = dict(saved_keys) if isinstance(saved_keys, dict) else {}
    if key_env:
        if update.clear_api_key:
            api_keys.pop(key_env, None)
        elif update.api_key is not None and update.api_key.strip():
            api_keys[str(key_env)] = update.api_key.strip()

    next_payload = {
        "provider": provider,
        "model": model,
        "api_keys": api_keys,
        "updated_at": datetime.now().replace(microsecond=0).isoformat(),
    }
    _write_config(next_payload)
    return get_llm_config()
