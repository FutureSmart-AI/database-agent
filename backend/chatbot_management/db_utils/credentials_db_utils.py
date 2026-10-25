"""Owner provider-key (BYOK) storage — NL2SQL's own credential store.

This is what the usage service did behind `/v1/owners/{owner}/credentials*`: encrypt a
key on the way in, hand back the plaintext only through the internal read, and expose
everything else masked. Ported from fs-agent-usage-limits
(`utils/credentials_management.py`) now that NL2SQL owns its credentials instead of
fetching them over HTTP on every LLM call.

Two things to know:

* **The plaintext is only ever produced by `get_plain_credential` /
  `list_all_plain_credentials`.** Every other read returns the mask. Decryption needs
  `APP_MASTER_KEY`, so a misconfigured environment fails closed — it cannot silently
  return a wrong key.

* **`get_plain_credential` does NOT update `last_used_at`.** It sits on the hot path —
  every LLM call in the graph asks for a key — so touching a row per call would add a
  write to every model invocation. The usage service's internal read behaved the same
  way; the column is maintained by management operations only.
"""
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from chatbot_management.utils.encryption import (
    encrypt_api_key,
    decrypt_api_key,
    mask_api_key,
)
from logger import logger
from models.sql_models import UserProviderKeys
from otel_tracing import track_time


@track_time("DB: Get Owner Credential")
async def get_plain_credential(
    session: AsyncSession,
    owner_id: str,
    provider: str,
) -> Optional[Tuple[str, bool]]:
    """The owner's decrypted key for this provider, or None when there isn't one.

    Returns `(api_key, is_valid)`. `is_valid` is the result of the last live provider
    check — a key that has since been revoked upstream still decrypts fine, so callers
    that care about freshness should look at it.

    Returns None rather than raising when absent: "this owner has no key of their own"
    is the normal case, not an error, and the caller falls back to the platform key.
    A DECRYPTION failure does raise — that means misconfigured key material, and
    quietly treating it as "no key" would silently bill the owner's usage to the
    platform.
    """
    statement = select(UserProviderKeys).where(
        UserProviderKeys.owner_id == owner_id,
        UserProviderKeys.provider == provider,
    )
    result = await session.execute(statement)
    credential = result.scalar_one_or_none()

    if not credential:
        return None

    api_key = decrypt_api_key(credential.encrypted_key)
    return api_key, credential.is_valid


@track_time("DB: Upsert Owner Credential")
async def add_or_update_credential(
    session: AsyncSession,
    owner_id: str,
    provider: str,
    api_key: str,
    is_valid: bool = True,
) -> UserProviderKeys:
    """Store or replace an owner's key for one provider.

    Upsert on (owner_id, provider) — the table's unique constraint. Replacing rather
    than inserting matters: two live keys for the same provider would make which one
    gets used non-deterministic.
    """
    encrypted_key, key_hash = encrypt_api_key(api_key)
    key_mask = mask_api_key(api_key)
    now = datetime.now(timezone.utc)

    statement = select(UserProviderKeys).where(
        UserProviderKeys.owner_id == owner_id,
        UserProviderKeys.provider == provider,
    )
    result = await session.execute(statement)
    existing = result.scalar_one_or_none()

    if existing:
        existing.encrypted_key = encrypted_key
        existing.key_hash = key_hash
        existing.key_mask = key_mask
        existing.is_valid = is_valid
        existing.updated_at = now
        credential = existing
        logger.info(f"Updated credential | owner_id={owner_id} provider={provider} mask={key_mask}")
    else:
        credential = UserProviderKeys(
            owner_id=owner_id,
            provider=provider,
            encrypted_key=encrypted_key,
            key_hash=key_hash,
            key_mask=key_mask,
            is_valid=is_valid,
            created_at=now,
            updated_at=now,
        )
        session.add(credential)
        logger.info(f"Stored credential | owner_id={owner_id} provider={provider} mask={key_mask}")

    await session.commit()
    await session.refresh(credential)
    return credential


@track_time("DB: List Owner Credentials")
async def list_credentials(
    session: AsyncSession,
    owner_id: str,
) -> List[UserProviderKeys]:
    """Every provider this owner has a key for. Rows carry the mask, not the key —
    callers must not decrypt for display."""
    statement = (
        select(UserProviderKeys)
        .where(UserProviderKeys.owner_id == owner_id)
        .order_by(UserProviderKeys.provider)
    )
    result = await session.execute(statement)
    return list(result.scalars().all())


@track_time("DB: Delete Owner Credential")
async def delete_credential(
    session: AsyncSession,
    owner_id: str,
    provider: str,
) -> bool:
    """Remove an owner's key for one provider. True if a row was deleted.

    A hard delete: the whole point is that the ciphertext stops existing. Soft-deleting
    a credential would keep the encrypted key on disk, which is the opposite of what
    someone removing their key is asking for.
    """
    statement = select(UserProviderKeys).where(
        UserProviderKeys.owner_id == owner_id,
        UserProviderKeys.provider == provider,
    )
    result = await session.execute(statement)
    credential = result.scalar_one_or_none()

    if not credential:
        return False

    await session.delete(credential)
    await session.commit()
    logger.info(f"Deleted credential | owner_id={owner_id} provider={provider}")
    return True


@track_time("DB: List All Plain Credentials")
async def list_all_plain_credentials(
    session: AsyncSession,
    provider: Optional[str] = None,
) -> List[dict]:
    """Every stored key, decrypted, optionally narrowed to one provider.

    This exists for the same reason the usage service had it — a service-to-service
    sweep — and it is the most dangerous read in this module: one call returns every
    owner's plaintext key. It must stay behind master-key auth only.
    """
    statement = select(UserProviderKeys)
    if provider:
        statement = statement.where(UserProviderKeys.provider == provider)
    statement = statement.order_by(UserProviderKeys.owner_id)

    result = await session.execute(statement)
    credentials = result.scalars().all()

    items = []
    for cred in credentials:
        try:
            items.append({
                "owner_id": cred.owner_id,
                "provider": cred.provider,
                "api_key": decrypt_api_key(cred.encrypted_key),
                "is_valid": cred.is_valid,
            })
        except Exception as e:
            # One unreadable row must not sink the whole sweep — report and continue,
            # so a single bad row does not hide every good one.
            logger.error(
                f"list_all_plain_credentials: could not decrypt "
                f"owner_id={cred.owner_id} provider={cred.provider}: {e}"
            )
    return items
