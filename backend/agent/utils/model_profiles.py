"""Versioned operation configuration, without credentials or provider fallback."""
from __future__ import annotations

import importlib
import json
import logging
import math
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE = "futuresmart-recommended-v1"
NODE_OPERATIONS = {
    "router": "sql_agent.router", "db_router": "sql_agent.db_router",
    "select_table": "sql_agent.select_table", "sql_gen": "sql_agent.sql_generation",
    "final_answer_node": "sql_agent.rephrase_answer", "chart_agent": "chart_agent.suggest",
}
PROVIDERS = {
    "openai": ("langchain_openai", "ChatOpenAI", "OPENAI_API_KEY"),
    "google": ("langchain_google_genai", "ChatGoogleGenerativeAI", "GOOGLE_API_KEY"),
    "groq": ("langchain_groq", "ChatGroq", "GROQ_API_KEY"),
    "anthropic": ("langchain_anthropic", "ChatAnthropic", "ANTHROPIC_API_KEY"),
    "deepseek": ("langchain_openai", "ChatOpenAI", "DEEPSEEK_API_KEY"),
    "minimax": ("langchain_openai", "ChatOpenAI", "MINIMAX_API_KEY"),
}
FIELDS = {"provider", "model", "temperature", "reasoning_effort", "endpoint",
          "max_tokens", "timeout", "max_retries"}
CAPABILITIES = {"temperature", "reasoning_effort", "endpoint"}
EMBEDDING_DIMENSIONS = {"text-embedding-3-small": 1536,
                        "text-embedding-3-large": 3072, "text-embedding-ada-002": 1536}


class ModelConfigurationError(ValueError):
    """Invalid operation configuration; error messages never include credentials."""


def _object(value: Any, where: str) -> dict:
    if not isinstance(value, dict):
        raise ModelConfigurationError(f"{where} must be an object")
    return value


def _read(path: Path) -> dict:
    try:
        return _object(json.loads(path.read_text(encoding="utf-8")), str(path))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ModelConfigurationError(f"Cannot read model configuration: {path}") from error


def merge_binding(base: dict, override: dict | None) -> dict:
    """A new binding resets inherited capabilities, while explicit options remain."""
    merged = dict(base)
    if override is not None:
        override = _object(override, "operation override")
        if set(override) - FIELDS:
            raise ModelConfigurationError("Unknown model option")
        if ("provider" in override) != ("model" in override):
            raise ModelConfigurationError("An operation binding requires both provider and model")
        if "provider" in override:
            for field in CAPABILITIES:
                merged.pop(field, None)
        merged.update(override)
    return validate_binding(merged)


def validate_binding(binding: dict) -> dict:
    conf = dict(_object(binding, "operation binding"))
    provider, model = conf.get("provider"), conf.get("model")
    if not isinstance(provider, str) or not isinstance(model, str) or not model.strip():
        raise ModelConfigurationError("Every operation requires provider and nonempty model")
    provider = "google" if provider.lower() == "gemini" else provider.lower()
    if provider not in PROVIDERS:
        raise ModelConfigurationError(f"Unsupported model provider: {provider}")
    conf["provider"] = provider
    if model in {"gpt-6.1-sol", "gpt-6-luna"} and provider != "openai":
        raise ModelConfigurationError(f"{model} requires the OpenAI provider")
    endpoint, reasoning = conf.get("endpoint"), conf.get("reasoning_effort")
    if provider == "openai":
        if model == "gpt-6.1-sol":
            if endpoint not in (None, "responses"):
                raise ModelConfigurationError("gpt-6.1-sol tools require the Responses endpoint")
            if reasoning not in (None, "low", "medium", "high", "xhigh", "max"):
                raise ModelConfigurationError("Unsupported gpt-6.1-sol reasoning effort")
            if conf.get("temperature") is not None:
                raise ModelConfigurationError("gpt-6.1-sol does not support temperature")
            conf.update(endpoint="responses", reasoning_effort=reasoning or "low")
        elif model == "gpt-6-luna":
            if endpoint not in (None, "chat_completions", "responses"):
                raise ModelConfigurationError("Unsupported OpenAI endpoint")
            endpoint = endpoint or "chat_completions"
            if endpoint == "chat_completions" and reasoning not in (None, "none"):
                raise ModelConfigurationError("gpt-6-luna Chat tools require reasoning_effort=none")
            if reasoning not in (None, "none", "low", "medium", "high", "xhigh", "max"):
                raise ModelConfigurationError("Unsupported gpt-6-luna reasoning effort")
            conf.update(endpoint=endpoint, reasoning_effort=reasoning or "none")
            if reasoning not in (None, "none") and conf.get("temperature") is not None:
                raise ModelConfigurationError("gpt-6-luna reasoning requests require temperature=null")
        elif endpoint not in (None, "chat_completions", "responses"):
            raise ModelConfigurationError("Unsupported OpenAI endpoint")
        if model.lower().startswith("gpt-5"):
            endpoint = endpoint or "chat_completions"
            if endpoint == "chat_completions" and reasoning not in (None, "none"):
                raise ModelConfigurationError("GPT-5 Chat tools require reasoning_effort=none; select Responses for reasoning")
            conf.update(endpoint=endpoint, reasoning_effort=reasoning or "none")
    elif endpoint not in (None, "chat_completions") or reasoning is not None:
        raise ModelConfigurationError(f"Unsupported endpoint/reasoning options for {provider}")
    if "timeout" in conf and (isinstance(conf["timeout"], bool) or not isinstance(conf["timeout"], (int, float)) or not math.isfinite(conf["timeout"]) or conf["timeout"] <= 0):
        raise ModelConfigurationError("timeout must be finite and positive")
    if "max_tokens" in conf and (type(conf["max_tokens"]) is not int or conf["max_tokens"] <= 0):
        raise ModelConfigurationError("max_tokens must be a positive integer")
    if "max_retries" in conf and (type(conf["max_retries"]) is not int or conf["max_retries"] < 0):
        raise ModelConfigurationError("max_retries must be a nonnegative integer")
    temp = conf.get("temperature")
    if temp is not None and (isinstance(temp, bool) or not isinstance(temp, (float, int)) or not 0 <= temp <= 2):
        raise ModelConfigurationError("temperature must be null or between 0 and 2")
    conf.setdefault("timeout", 45)
    conf.setdefault("max_retries", 0)
    conf.setdefault("max_tokens", 8192 if model == "gpt-6.1-sol" else 2048)
    return conf


def load_profile(config_path: str | Path | None = None) -> dict:
    path = Path(config_path or os.getenv("MODEL_CONFIG_PATH") or ROOT / "model_config.json")
    user = _read(path)
    version = user.get("profile", DEFAULT_PROFILE)
    if version != DEFAULT_PROFILE:
        raise ModelConfigurationError(f"Unknown model profile: {version}")
    shipped = _read(ROOT / "model_profiles" / f"{version}.json")
    result = {"profile": version}
    operations = {name: dict(shipped["roles"][role]) for name, role in shipped["operations"].items()}
    single = user.get("single_provider")
    if single is not None:
        single = _object(single, "single_provider")
        if not single.get("provider") or not single.get("model"):
            raise ModelConfigurationError("single_provider requires provider and model")
        operations = {name: merge_binding(base, single) for name, base in operations.items()}
    overrides = dict(_object(user.get("overrides", {}), "overrides"))
    allowed = {"profile", "single_provider", "overrides", "embeddings", "fallback"}
    for group in {name.split(".")[0] for name in operations}:
        allowed.add(group)
        for name, binding in _object(user.get(group, {}), group).items():
            op = f"{group}.{name}"
            if op in overrides:
                raise ModelConfigurationError(f"Duplicate operation override: {op}")
            overrides[op] = binding
    if set(user) - allowed:
        raise ModelConfigurationError("Unknown top-level model configuration field")
    if "fallback" in user:
        overrides.setdefault("csv_agent.answer", user["fallback"])
    for operation in overrides:
        if operation not in operations:
            raise ModelConfigurationError(f"Unknown model operation: {operation}")
    for name, base in operations.items():
        group, key = name.split(".", 1)
        result.setdefault(group, {})[key] = merge_binding(base, overrides.get(name))
    result["fallback"] = dict(result["csv_agent"]["answer"])
    embeddings = deepcopy(shipped["embeddings"])
    for name, override in _object(user.get("embeddings", {}), "embeddings").items():
        if name not in embeddings:
            raise ModelConfigurationError(f"Unknown embedding operation: {name}")
        embeddings[name].update(_object(override, name))
    for name, e in embeddings.items():
        prefix = "FEWSHOT" if name == "fewshot" else "HC"
        model, size = os.getenv(f"{prefix}_EMBEDDING_MODEL"), os.getenv(f"{prefix}_EMBEDDING_SIZE")
        legacy_size = os.getenv("HC_DENSE_VECTOR_SIZE") if prefix == "HC" else None
        if size and legacy_size and size != legacy_size:
            raise ModelConfigurationError("Conflicting HC embedding dimension settings")
        size = size or legacy_size
        if model:
            e.update(model=model, dimensions=EMBEDDING_DIMENSIONS.get(model))
        if size:
            try:
                e["dimensions"] = int(size)
            except ValueError as error:
                raise ModelConfigurationError(f"{prefix}_EMBEDDING_SIZE must be an integer") from error
        if e.get("provider") != "openai" or e.get("model") not in EMBEDDING_DIMENSIONS:
            raise ModelConfigurationError(f"Unsupported embedding binding: {name}")
        if set(e) - {"provider", "model", "dimensions"}:
            raise ModelConfigurationError(f"Unknown embedding configuration option: {name}")
        if e.get("dimensions") != EMBEDDING_DIMENSIONS[e["model"]]:
            raise ModelConfigurationError(f"Embedding model/dimension mismatch: {name}")
    result["embeddings"] = embeddings
    return result


def operation_config(operation: str, override: dict | None = None) -> dict:
    group, name = NODE_OPERATIONS.get(operation, operation).split(".", 1)
    profile = load_profile()
    if group not in profile or name not in profile[group]:
        raise ModelConfigurationError(f"Unknown model operation: {operation}")
    return merge_binding(profile[group][name], override)


def response_text(message) -> str:
    """Normalize actual LangChain Chat strings and Responses text blocks."""
    text = getattr(message, "text", None)
    if isinstance(text, str):
        return text.strip()
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content.strip()
    raise TypeError("Model response has no supported text content")


def build_chat_model(conf: dict, *, api_key: str | None = None, **transport: Any):
    """Construct exactly the configured provider/model, with injectable test transport."""
    conf = validate_binding(conf)
    provider = conf["provider"]
    module, cls, key_env = PROVIDERS[provider]
    key = api_key or os.getenv(key_env)
    if not key:
        raise ModelConfigurationError(f"Missing {key_env} for selected provider {provider}")
    try:
        model_class = getattr(importlib.import_module(module), cls)
    except (ImportError, AttributeError) as error:
        raise ModelConfigurationError(f"Selected provider SDK is unavailable: {provider}") from error
    kwargs = {k: v for k, v in conf.items() if k in FIELDS - {"provider", "endpoint"} and v is not None}
    kwargs.update(api_key=key, **transport)
    if provider == "openai":
        kwargs["use_responses_api"] = conf.get("endpoint") == "responses"
        if kwargs["use_responses_api"]:
            kwargs["store"] = False
    elif provider in ("deepseek", "minimax"):
        from agent.utils.owner_credential_utils import get_openai_compatible_client_kwargs
        compat = get_openai_compatible_client_kwargs(provider)
        compat.pop("api_key", None)
        kwargs.update(compat)
    elif provider == "google":
        kwargs["max_output_tokens"] = kwargs.pop("max_tokens")
    client = model_class(**kwargs)
    logging.getLogger(__name__).info(
        "model.client provider=%s model=%s endpoint=%s reasoning_effort=%s",
        provider, conf["model"], conf.get("endpoint", "provider-native"), conf.get("reasoning_effort"))
    return client


def configured_model_factory(conf: dict):
    """Adapter for existing schema builders; resolved config owns model capabilities."""
    def construct(**kwargs):
        binding = dict(conf)
        # Existing callers may impose tighter bounds than the profile, never loosen them.
        for field in ("timeout", "max_tokens", "max_retries"):
            if field in kwargs:
                validate_binding({**binding, field: kwargs[field]})
                binding[field] = min(binding[field], kwargs[field])
        # Keep the existing bounded same-model DeepSeek repair temperature behavior.
        if binding["provider"] == "deepseek" and "temperature" in kwargs:
            binding["temperature"] = kwargs["temperature"]
        transport = {k: kwargs[k] for k in ("http_client", "http_async_client", "client", "async_client") if k in kwargs}
        return build_chat_model(binding, api_key=kwargs.get("api_key"), **transport)
    return construct
