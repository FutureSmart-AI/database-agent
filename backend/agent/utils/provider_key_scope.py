"""Which provider keys one request or setup job may use.

Two sources exist, chosen per owner by `nl2sql_owner_config.provider_key_source`:

  platform   The owner's own key when they have stored one, else the platform key from
             the environment. This is the long-standing behaviour, the standalone
             installation's only mode, and the explicit choice for platform-managed
             owners on the hosted service.
  own        Bring-your-own-key. Every model and embedding call uses the owner's stored
             key. A missing, unreadable or invalid key is an error the owner can act on —
             never a silent switch to the platform key.

An owner with no stored choice gets the deployment default, `DEFAULT_PROVIDER_KEY_SOURCE`
(unset means `platform`, so a standalone installation behaves exactly as before).

WHY A SCOPE AND NOT JUST THE LOOKUP. Most call sites resolve the owner's key explicitly
through `get_owner_api_key_for_provider`. Several do not — table selection, setup
descriptions, chart post-processing and embedding clients build a provider client with no
key and let the factory read the environment. Rather than trusting every such site to be
found and threaded, the owner's keys are bound once at the entry point (chat flow,
description job, profiling job) and `env_key_for` — the one place an environment key is
read — answers from that binding. A site nobody threaded therefore uses the owner's key,
and a path with no binding at all fails closed when the deployment default is `own`.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from agent.utils.model_profiles import ModelConfigurationError, ProviderCredentialError
from logger import logger

OWN = "own"
PLATFORM = "platform"
SOURCES = (OWN, PLATFORM)

# Stored provider names. "gemini" is stored as "google" (see owner_credential_utils).
_PROVIDER_LABELS = {
    "openai": "OpenAI", "google": "Google", "groq": "Groq", "anthropic": "Anthropic",
    "deepseek": "DeepSeek", "minimax": "MiniMax",
}


# ProviderCredentialError codes, stable for clients: provider_key_missing,
# provider_key_invalid, provider_key_unreadable, provider_key_rejected, provider_key_unbound.


def provider_label(provider: Optional[str]) -> str:
    p = canonical(provider)
    return _PROVIDER_LABELS.get(p, p or "model provider")


def canonical(provider: Optional[str]) -> str:
    p = (provider or "").strip().lower()
    return "google" if p == "gemini" else p


def deployment_default_source() -> str:
    value = (os.getenv("DEFAULT_PROVIDER_KEY_SOURCE") or PLATFORM).strip().lower()
    if value not in SOURCES:
        raise ModelConfigurationError(
            f"DEFAULT_PROVIDER_KEY_SOURCE must be one of {', '.join(SOURCES)}")
    return value


def missing_key_error(provider: Optional[str]) -> ProviderCredentialError:
    label = provider_label(provider)
    return ProviderCredentialError(
        "provider_key_missing",
        f"No {label} API key is configured for this workspace. Add your {label} API key "
        f"under Credentials, then ask again.")


def invalid_key_error(provider: Optional[str]) -> ProviderCredentialError:
    label = provider_label(provider)
    return ProviderCredentialError(
        "provider_key_invalid",
        f"Your saved {label} API key failed validation. Update it under Credentials, "
        f"then ask again.")


def unreadable_key_error(provider: Optional[str]) -> ProviderCredentialError:
    label = provider_label(provider)
    return ProviderCredentialError(
        "provider_key_unreadable",
        f"Your saved {label} API key could not be read. Remove it and add it again under "
        f"Credentials.")


def rejected_key_error(provider: Optional[str]) -> ProviderCredentialError:
    label = provider_label(provider)
    return ProviderCredentialError(
        "provider_key_rejected",
        f"{label} rejected the API key saved under Credentials. Check that the key is "
        f"active and has access to the configured model, then update it.")


@dataclass(frozen=True)
class KeyScope:
    owner_id: Optional[str]
    source: str
    # canonical provider -> (key, is_valid); populated only for `own`.
    keys: Dict[str, Tuple[str, bool]] = field(default_factory=dict)
    # canonical provider -> error code, for stored rows that could not be decrypted.
    unreadable: Dict[str, str] = field(default_factory=dict)

    def owner_key(self, provider: Optional[str]) -> str:
        """The owner's usable key for `provider`, or the error the owner should see."""
        p = canonical(provider)
        if p in self.unreadable:
            raise unreadable_key_error(p)
        found = self.keys.get(p)
        if not found:
            raise missing_key_error(p)
        key, is_valid = found
        if not is_valid:
            raise invalid_key_error(p)
        return key


_scope: ContextVar[Optional[KeyScope]] = ContextVar("provider_key_scope", default=None)


def current_scope() -> Optional[KeyScope]:
    return _scope.get()


async def owner_key_source(owner_id: Optional[str]) -> str:
    """The stored per-owner choice, else the deployment default. Never guesses on error."""
    default = deployment_default_source()
    if not owner_id:
        return default
    from sqlmodel import select
    from chatbot_management.services.sqlmodel_session import async_session
    from models.sql_models import Nl2sqlOwnerConfig

    async with async_session() as session:
        result = await session.execute(
            select(Nl2sqlOwnerConfig.provider_key_source)
            .where(Nl2sqlOwnerConfig.owner_id == owner_id.strip().lower()))
        stored = result.scalar_one_or_none()
    if stored is None:
        return default
    if stored not in SOURCES:
        raise ModelConfigurationError(f"Unknown provider key source for owner: {stored}")
    return stored


async def _load_owner_keys(owner_id: str) -> Tuple[Dict[str, Tuple[str, bool]], Dict[str, str]]:
    from sqlmodel import select
    from chatbot_management.services.sqlmodel_session import async_session
    from chatbot_management.utils.encryption import decrypt_api_key
    from models.sql_models import UserProviderKeys

    keys: Dict[str, Tuple[str, bool]] = {}
    unreadable: Dict[str, str] = {}
    async with async_session() as session:
        rows = (await session.execute(
            select(UserProviderKeys).where(UserProviderKeys.owner_id == owner_id))).scalars().all()
    for row in rows:
        provider = canonical(row.provider)
        try:
            keys[provider] = (decrypt_api_key(row.encrypted_key), bool(row.is_valid))
        except Exception as error:
            logger.error("[CREDENTIAL] Owner key could not be decrypted | owner_id=%s provider=%s "
                         "error=%s", owner_id, provider, type(error).__name__)
            unreadable[provider] = "provider_key_unreadable"
    return keys, unreadable


async def resolve_scope(owner_id: Optional[str]) -> KeyScope:
    source = await owner_key_source(owner_id)
    if source == PLATFORM:
        return KeyScope(owner_id=owner_id, source=PLATFORM)
    if not owner_id:
        raise ProviderCredentialError(
            "provider_key_unbound",
            "This request has no workspace owner, so no API key can be selected for it.")
    keys, unreadable = await _load_owner_keys(owner_id)
    logger.info("[CREDENTIAL] Bring-your-own-key scope | owner_id=%s providers=%s unreadable=%s",
                owner_id, sorted(keys), sorted(unreadable))
    return KeyScope(owner_id=owner_id, source=OWN, keys=keys, unreadable=unreadable)


@asynccontextmanager
async def owner_key_scope(owner_id: Optional[str]):
    """Bind the owner's key policy for everything awaited inside, including child tasks."""
    scope = await resolve_scope(owner_id)
    token = _scope.set(scope)
    try:
        yield scope
    finally:
        _scope.reset(token)


@asynccontextmanager
async def platform_key_scope(owner_id: Optional[str]):
    """Bind the platform key policy for everything awaited inside.

    Only for an authenticated internal caller that has already applied its own
    product's key policy for `owner_id` (Document Intelligence's chart requests, see
    chart_agent/api/chart_api.py). `owner_id` is kept for usage attribution.
    """
    token = _scope.set(KeyScope(owner_id=owner_id, source=PLATFORM))
    try:
        yield
    finally:
        _scope.reset(token)


def env_key_for(provider: Optional[str], env_var: Optional[str]) -> Optional[str]:
    """The key a client built without an explicit key may use. The ONLY sanctioned env read.

    Under an `own` scope this is the owner's key (or a clear error). Under `platform` it is
    the environment key, unchanged. With no scope bound it follows the deployment default:
    `platform` reads the environment as before; `own` refuses, because an unbound call on a
    bring-your-own-key deployment has no owner whose key it could use.
    """
    scope = _scope.get()
    if scope is not None:
        if scope.source == OWN:
            return scope.owner_key(provider)
        return os.getenv(env_var) if env_var else None
    if deployment_default_source() == OWN:
        logger.error("[CREDENTIAL] Provider client requested outside an owner key scope | "
                     "provider=%s", canonical(provider))
        raise ProviderCredentialError(
            "provider_key_unbound",
            "This operation is not bound to a workspace owner, so no API key can be selected "
            "for it.")
    return os.getenv(env_var) if env_var else None


def is_provider_auth_error(error: BaseException) -> bool:
    """A provider refusing the key itself (HTTP 401), anywhere in the cause chain."""
    seen = set()
    current: Optional[BaseException] = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if type(current).__name__ == "AuthenticationError":
            return True
        status = getattr(current, "status_code", None)
        if status is None:
            status = getattr(getattr(current, "response", None), "status_code", None)
        if status == 401:
            return True
        current = current.__cause__ or current.__context__
    return False



