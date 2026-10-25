"""Owner Credentials APIs (BYOK).

Store, list and remove an owner's own provider API keys, so their model usage bills to
their account instead of the platform's. Ported from fs-agent-usage-limits
(`routers/credentials_router.py`) now that NL2SQL owns its credentials rather than reading
them from that service on every LLM call.

Endpoint shapes and response envelopes are kept identical to the usage service's, so the
Dashboard can move over by changing only the base URL.

Endpoints:
  GET    /v1/owners/providers                                    supported providers
  POST   /v1/owners/{owner_id}/credentials                       add or replace a key
  GET    /v1/owners/{owner_id}/credentials                       list keys (masked)
  DELETE /v1/owners/{owner_id}/credentials/{provider}            remove a key
  GET    /v1/owners/{owner_id}/credentials/{provider}/internal   decrypted, master key only
  GET    /v1/owners/credentials/internal                         all decrypted, master key only

Two rules that matter more than the rest:

* The plaintext key is only ever returned by the two `/internal` endpoints, and they are
  master-key only. A session or agent-key caller cannot reach them at all, not even for
  their own key, so a stolen browser session cannot harvest stored provider keys.

* A key is validated live with the provider before being stored, and a rejected key is not
  saved. Storing an unusable key would be worse than refusing it: the credential lookup
  falls back to the platform key on failure, so the owner would look configured while
  their usage quietly billed to the platform.

Ownership scoping mirrors `analytics.py` — a session caller acts on their own address, the
master key acts on whoever it names. Owner-level RBAC is not enforced, for the same reason
it is off in `agent/utils/authorization.py`.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from api.v1.schemas.credentials import (
    CredentialAddRequest,
    CredentialAddResponse,
    CredentialData,
    CredentialDeleteResponse,
    CredentialListResponse,
    InternalCredentialItem,
    InternalCredentialListResponse,
    InternalCredentialResponse,
    ProviderListResponse,
)
from chatbot_management.db_utils.credentials_db_utils import (
    add_or_update_credential,
    delete_credential,
    get_plain_credential,
    list_all_plain_credentials,
    list_credentials,
)
from chatbot_management.services.sqlmodel_session import async_session
from chatbot_management.utils.api_key_validation import validate_api_key
from chatbot_management.utils.api_validation import get_api_key_or_session
from agent.utils.owner_credential_utils import canonical_provider
from logger import logger
from otel_tracing import track_time

router = APIRouter(prefix="/v1/owners", tags=["Owner Credentials"])

# What the UI should offer. Must stay in step with the validators in
# `chatbot_management/utils/api_key_validation.py`.
#
# `gemini` is deliberately absent even though POST accepts it: a Gemini key is stored
# under `google` (see `canonical_provider`), so advertising both would put the same
# provider in the dropdown twice.
#
# `llamaparse` and `firecrawl` are absent because NL2SQL has no document-parsing or
# web-scraping path and neither library is installed — a key stored for them could never
# be used.
_LLM_PROVIDERS = ["openai", "anthropic", "groq", "google", "deepseek", "minimax"]


def _resolve_owner(auth: dict, owner_id: str) -> str:
    """Which owner this request acts on.

    Resolution, not authorization — see `agent/utils/authorization.py`, where RBAC is off
    because the chat service 404s on agents NL2SQL created. A session caller defaults to
    their own address; "me" is accepted so the UI need not know its own email.
    """
    if owner_id == "me":
        resolved = auth.get("user_id")
        if not resolved:
            raise HTTPException(
                status_code=400,
                detail="owner_id 'me' requires a session; name the owner explicitly with an API key",
            )
        owner_id = resolved
    # Lower-cased because this repo stores owner emails that way everywhere (718 agents, 0
    # exceptions) and the credential lookup matches exactly. A caller passing
    # OWNER@EXAMPLE.COM would otherwise create a second row that no query ever finds, and
    # the owner would silently fall back to the platform key.
    resolved = (owner_id or "").strip().lower()
    # A browser session acts only on its own keys. Without this a signed-in user could
    # name any other owner's email and add, list or remove that owner's provider keys.
    # Master-key callers (service-to-service) still name the owner explicitly.
    if auth.get("auth_type") == "session" and resolved != (auth.get("user_id") or "").strip().lower():
        raise HTTPException(status_code=403, detail="A session may only manage its own credentials")
    return resolved


def _require_master_key(auth: dict) -> None:
    """Gate the two endpoints that return plaintext keys. Master key only."""
    if auth.get("auth_type") != "master_api_key":
        raise HTTPException(status_code=403, detail="This endpoint requires the master API key")


@router.get("/providers", response_model=ProviderListResponse)
async def api_list_providers(
    auth: dict = Depends(get_api_key_or_session),
) -> ProviderListResponse:
    """Providers a key can be stored for, grouped for the UI."""
    return ProviderListResponse(llm_providers=_LLM_PROVIDERS)


@router.post("/{owner_id}/credentials", response_model=CredentialAddResponse,
             status_code=status.HTTP_200_OK)
@track_time("API: Add Owner Credential")
async def api_add_credential(
    payload: CredentialAddRequest,
    owner_id: str = Path(..., description="Owner email, or 'me' for the caller"),
    auth: dict = Depends(get_api_key_or_session),
) -> CredentialAddResponse:
    """Validate a key with the provider, then store it encrypted.

    Replaces any existing key for the same provider, so which key gets used is never
    ambiguous. A key the provider rejects is not stored, and the reason is returned.
    """
    target_owner = _resolve_owner(auth, owner_id)
    # Store under one name per provider ("gemini" -> "google"), so a second row can never
    # be created for the same key and the lookup is unambiguous.
    provider = canonical_provider(payload.provider)

    try:
        is_valid, error_message = await validate_api_key(provider, payload.api_key)
    except ValueError as e:
        # Unsupported provider: a 422, not a server fault.
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"POST credentials for {target_owner} - validation error: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="Could not reach the provider to validate the key")

    if not is_valid:
        # 422: the request was well-formed, the key itself was refused.
        raise HTTPException(status_code=422, detail=f"Key validation failed: {error_message}")

    try:
        async with async_session() as session:
            credential = await add_or_update_credential(
                session,
                owner_id=target_owner,
                provider=provider,
                api_key=payload.api_key,
                is_valid=True,
            )
    except Exception as e:
        logger.error(f"POST credentials for {target_owner} - Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred")

    return CredentialAddResponse(
        data=CredentialData(
            provider=credential.provider,
            mask=credential.key_mask,
            is_valid=credential.is_valid,
            updated_at=(credential.updated_at or datetime.now(timezone.utc)).isoformat(),
        )
    )


@router.get("/{owner_id}/credentials", response_model=CredentialListResponse)
@track_time("API: List Owner Credentials")
async def api_list_credentials(
    owner_id: str = Path(..., description="Owner email, or 'me' for the caller"),
    auth: dict = Depends(get_api_key_or_session),
) -> CredentialListResponse:
    """Which providers this owner has a key for. Masked, never the key itself."""
    target_owner = _resolve_owner(auth, owner_id)
    try:
        async with async_session() as session:
            rows = await list_credentials(session, target_owner)
    except Exception as e:
        logger.error(f"GET credentials for {target_owner} - Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred")

    return CredentialListResponse(data=[
        CredentialData(
            provider=r.provider,
            mask=r.key_mask,
            is_valid=r.is_valid,
            updated_at=(r.updated_at or r.created_at).isoformat(),
        )
        for r in rows
    ])


@router.delete("/{owner_id}/credentials/{provider}", response_model=CredentialDeleteResponse)
@track_time("API: Delete Owner Credential")
async def api_delete_credential(
    owner_id: str = Path(..., description="Owner email, or 'me' for the caller"),
    provider: str = Path(..., description="Provider whose key should be removed"),
    auth: dict = Depends(get_api_key_or_session),
) -> CredentialDeleteResponse:
    """Remove an owner's key for one provider.

    A hard delete: the ciphertext stops existing, which is what removing a key means.
    Their usage falls back to the platform key from the next call onward.
    """
    target_owner = _resolve_owner(auth, owner_id)
    provider = canonical_provider(provider)
    try:
        async with async_session() as session:
            deleted = await delete_credential(session, target_owner, provider)
    except Exception as e:
        logger.error(f"DELETE credentials {target_owner}/{provider} - Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred")

    if not deleted:
        raise HTTPException(status_code=404, detail="No credential stored for that provider")

    return CredentialDeleteResponse(message=f"Credential for {provider} deleted")


@router.get("/{owner_id}/credentials/{provider}/internal",
            response_model=InternalCredentialResponse, include_in_schema=False)
@track_time("API: Get Internal Credential")
async def api_get_internal_credential(
    owner_id: str = Path(...),
    provider: str = Path(...),
    auth: dict = Depends(get_api_key_or_session),
) -> InternalCredentialResponse:
    """Decrypted key for one owner and provider. Master key only.

    Hidden from the schema, kept for service-to-service callers. NL2SQL's own nodes do NOT
    use this: they read the store directly via `agent.utils.owner_credential_utils`, with
    no HTTP hop.
    """
    _require_master_key(auth)
    provider = canonical_provider(provider)
    try:
        async with async_session() as session:
            found = await get_plain_credential(session, owner_id, provider)
    except Exception as e:
        logger.error(f"GET internal credential {owner_id}/{provider} - Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred")

    if not found:
        raise HTTPException(status_code=404, detail="No credential stored for that provider")

    api_key, is_valid = found
    return InternalCredentialResponse(provider=provider, api_key=api_key, is_valid=is_valid)


@router.get("/credentials/internal", response_model=InternalCredentialListResponse,
            include_in_schema=False)
@track_time("API: List Internal Credentials")
async def api_list_internal_credentials(
    provider: Optional[str] = Query(None, description="Narrow to one provider"),
    auth: dict = Depends(get_api_key_or_session),
) -> InternalCredentialListResponse:
    """Every stored key, decrypted. Master key only.

    The most dangerous read here: one call returns every owner's key. Kept for parity with
    the usage service, which exposed the same sweep.
    """
    _require_master_key(auth)
    try:
        async with async_session() as session:
            items = await list_all_plain_credentials(session, provider=provider)
    except Exception as e:
        logger.error(f"GET internal credentials list - Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred")

    return InternalCredentialListResponse(data=[InternalCredentialItem(**i) for i in items])
