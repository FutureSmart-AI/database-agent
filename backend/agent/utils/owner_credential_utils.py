"""Fetch an owner's provider API key (BYOK), falling back to the platform key where allowed.

Whether the platform fallback is allowed at all is decided per owner by
`agent/utils/provider_key_scope.py`: owners on `own` (bring-your-own-key) never fall back;
owners on `platform` keep the behaviour described below.

Reads NL2SQL's own `user_provider_keys` table. This used to be an HTTP GET to the usage
service (`/v1/owners/{owner}/credentials/{provider}/internal`) on every LLM call from 20
call sites, with a hardcoded production URL and a committed API key — which also meant
staging read credentials out of production.

The public surface is unchanged (`get_owner_api_key_for_provider`, `get_llm_api_key`,
`get_provider_from_model`, `get_openai_compatible_*`), so no call site needed editing.

Fallback behaviour is deliberately preserved: when the owner has no key of their own, the
platform key from the environment is used and the source is reported as "platform-key",
which is what the usage event records for cost attribution. Note what that means — a
lookup that fails for the wrong reason bills the owner's usage to the platform rather
than erroring, so `_lookup_owner_key` distinguishes "no key stored" (normal, fall back)
from "could not read the store" (logged as an error, still falls back to keep queries
answerable).
"""
import os
from typing import Optional
from logger import logger
from dotenv import load_dotenv

load_dotenv()


# One provider, one stored row. `get_provider_from_model` returns "gemini" for Gemini
# models while credentials were historically stored under "google" (both map to
# GOOGLE_API_KEY above), and the credential lookup matches the provider string exactly —
# so without canonicalising, a stored Google key is simply never found for a Gemini model
# and the owner silently falls back to the platform key.
#
# Canonical form is the STORED one ("google"), so existing rows keep working untouched.
PROVIDER_ALIASES = {
    "gemini": "google",
}


def canonical_provider(provider: Optional[str]) -> str:
    """The name a credential is stored under, for any accepted spelling of a provider."""
    p = (provider or "").strip().lower()
    return PROVIDER_ALIASES.get(p, p)


PROVIDER_ENV_MAP = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "groq": "GROQ_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "google": "GOOGLE_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "llamaparse": "LLAMAPARSE_API_KEY",
}

# OpenAI-compatible providers reached via ChatOpenAI with a custom base_url. Existing providers
# (openai/anthropic/groq/google) are unaffected — they return None here and use their own SDKs.
OPENAI_COMPATIBLE_BASE_URLS = {
    "deepseek": "https://api.deepseek.com/v1",
    "minimax": "https://api.minimax.io/v1",
}


def get_openai_compatible_base_url(provider: Optional[str]) -> Optional[str]:
    """Base URL for OpenAI-compatible providers (DeepSeek, MiniMax); None for all others."""
    return OPENAI_COMPATIBLE_BASE_URLS.get((provider or "").lower())


def get_openai_compatible_client_kwargs(provider: Optional[str]) -> dict:
    """ChatOpenAI kwargs (base_url + env api_key + extra_body) for OpenAI-compatible providers
    (DeepSeek, MiniMax); empty dict for everything else. For LLM-build sites that use env creds
    directly (db_router, description jobs, follow-up, HC) so DeepSeek/MiniMax hit the right
    endpoint. DeepSeek V4 defaults to slow thinking mode → disable it here too."""
    p = (provider or "").lower()
    base = OPENAI_COMPATIBLE_BASE_URLS.get(p)
    if not base:
        return {}
    kw = {"base_url": base, "api_key": os.getenv(PROVIDER_ENV_MAP.get(p, ""))}
    if p == "deepseek":
        kw["extra_body"] = {"thinking": {"type": "disabled"}}
    return kw


def _env_fallback(provider: str) -> Optional[str]:
    """Get API key from environment variable."""
    env_var = PROVIDER_ENV_MAP.get(provider.lower())
    if not env_var:
        return None
    return os.getenv(env_var)


def get_provider_from_model(model_name: str) -> str:
    """
    Infer provider from model name.
    
    Note: Models like 'openai/gpt-oss-120b' are Groq-hosted OpenAI-compatible models,
    so they require Groq API keys, not OpenAI keys.
    """
    m = (model_name or "").lower()
    
    # Check for Groq-hosted models first (including OpenAI-compatible ones)
    if "groq" in m or m.startswith("groq/"):
        return "groq"
    # Models with "oss" (Open Source Software) are typically Groq-hosted
    # Patterns: "gpt-oss-120b", "openai/gpt-oss-120b", "/oss-", "-oss-", etc.
    if "-oss-" in m or "/oss-" in m or "/oss_" in m or m.endswith("-oss") or m.endswith("_oss"):
        return "groq"
    # OpenAI-prefixed models that are Groq-hosted (like openai/gpt-oss-120b)
    if m.startswith("openai/") and ("oss" in m or "groq" in m):
        return "groq"
    
    if "claude" in m or "anthropic" in m or m.startswith("anthropic/"):
        return "anthropic"
    if "gemini" in m or m.startswith("google/") or m.startswith("gemini/"):
        return "gemini"
    if "deepseek" in m or m.startswith("deepseek/"):
        return "deepseek"
    if "minimax" in m or "abab" in m or m.startswith("minimax/"):
        return "minimax"
    if "openai" in m:
        return "openai"
    return "openai"


async def _lookup_owner_key(owner_id: str, provider: str) -> Optional[str]:
    """The owner's own key for this provider from the local store, or None.

    Imported lazily: this module is pulled in by every LLM node, and the storage layer
    reaches the models and session factory — keeping those out of module scope avoids an
    import cycle.

    Never raises. A missing row is normal and returns None quietly; a failure to READ or
    DECRYPT is logged as an error before returning None, because the two are very
    different problems that both end in the platform key being used.
    """
    try:
        from chatbot_management.db_utils.credentials_db_utils import get_plain_credential
        from chatbot_management.services.sqlmodel_session import async_session

        # "gemini" and "google" are the same provider; look under the stored name.
        lookup_provider = canonical_provider(provider)

        async with async_session() as session:
            found = await get_plain_credential(session, owner_id, lookup_provider)

        if not found:
            logger.info(
                f"ℹ️ [CREDENTIAL] No owner key stored | owner_id: {owner_id} | provider: {provider}"
            )
            return None

        api_key, is_valid = found
        if not is_valid:
            # Kept, not discarded: the last live provider check failed, but the key may
            # since have been re-enabled upstream, and refusing to try it would take a
            # working setup offline on the strength of a stale check.
            logger.warning(
                f"⚠️ [CREDENTIAL] Owner key is marked invalid, using it anyway | "
                f"owner_id: {owner_id} | provider: {provider}"
            )
        return api_key

    except Exception as e:
        logger.error(
            f"💥 [CREDENTIAL] Could not read owner credential store | owner_id: {owner_id} | "
            f"provider: {provider} | error: {e}",
            exc_info=True,
        )
        return None


async def get_owner_api_key_for_provider(
    owner_id: Optional[str],
    provider: str,
    return_source: bool = False,
) -> Optional[str] | tuple[Optional[str], Optional[str]]:
    """
    Get API key for a specific provider for an owner.
    1) Hit provider-specific endpoint for decrypted api_key.
    2) If not found, fallback to environment variable.
    
    Returns API key with comprehensive logging of source.
    """
    # Bring-your-own-key owners never reach the environment fallback below: their stored
    # key is used, or the caller gets an error naming the provider and the fix. The bound
    # request scope answers when it is this owner's; otherwise the stored choice is read.
    from agent.utils.provider_key_scope import OWN, current_scope, owner_key_source, resolve_scope
    scope = current_scope()
    if scope is None or (owner_id and scope.owner_id != owner_id):
        source = await owner_key_source(owner_id)
        if source == OWN:
            scope = await resolve_scope(owner_id)
    else:
        source = scope.source
    if source == OWN:
        owner_key = scope.owner_key(provider)
        logger.info(
            f"✅ [CREDENTIAL] Using OWNER API KEY (bring-your-own-key) | owner_id: {owner_id} | "
            f"provider: {provider} | source: user_provider_keys"
        )
        if return_source:
            return owner_key, "owner-key"
        return owner_key

    if not owner_id:
        logger.info(f"🔑 [CREDENTIAL] No owner_id provided, using ENV VAR for provider: {provider}")
        env_key = _env_fallback(provider)
        if env_key:
            logger.info(f"✅ [CREDENTIAL] Using ENV VAR API KEY | provider: {provider} | source: .env")
        if return_source:
            return env_key, "platform-key" if env_key else None
        return env_key

    owner_key = await _lookup_owner_key(owner_id, provider)
    if owner_key:
        logger.info(
            f"✅ [CREDENTIAL] Using OWNER API KEY | owner_id: {owner_id} | provider: {provider} | "
            f"source: user_provider_keys"
        )
        if return_source:
            return owner_key, "owner-key"
        return owner_key

    # Fallback to environment variable
    env_key = _env_fallback(provider)
    if env_key:
        logger.info(
            f"⚠️ [CREDENTIAL] Using ENV VAR API KEY (fallback) | owner_id: {owner_id} | provider: {provider} | "
            f"source: .env"
        )
        if return_source:
            return env_key, "platform-key"
        return env_key

    logger.warning(f"❌ [CREDENTIAL] No API key found | owner_id: {owner_id} | provider: {provider}")
    if return_source:
        return None, None
    return None


async def get_llm_api_key(owner_id: Optional[str], model_name: str, provider: Optional[str] = None) -> Optional[str]:
    """
    Convenience helper: infer provider from model, fetch owner key, else env.
    Logs credential source for tracking.
    """
    prov = provider or get_provider_from_model(model_name or "")
    logger.info(f"🔑 [CREDENTIAL] Getting API key | owner_id: {owner_id} | model: {model_name} | provider: {prov}")
    key = await get_owner_api_key_for_provider(owner_id, prov)
    if key:
        return key
    # Reached only for platform-sourced owners: a bring-your-own-key owner either got a key
    # above or an error was raised.
    env_key = _env_fallback(prov)
    if env_key:
        logger.info(
            f"⚠️ [CREDENTIAL] Using ENV VAR API KEY (final fallback) | owner_id: {owner_id or 'N/A'} | "
            f"model: {model_name} | provider: {prov} | source: .env"
        )
    return env_key
