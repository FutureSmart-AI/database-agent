"""Request/response models for owner provider-key (BYOK) management.

Ported from fs-agent-usage-limits (`services/pydantic_models_credentials.py`), keeping the
same response envelopes so a caller written against that service works here unchanged.

Two differences:
  * `firecrawl` is dropped from the provider list (NL2SQL has no web-scraping provider)
    and `deepseek`, `minimax` and `gemini` are added — NL2SQL supports all three.
  * Pydantic v2 syntax, matching the rest of this repo.

The plaintext key appears in exactly two models — `InternalCredentialResponse` and
`InternalCredentialItem` — both served only by master-key endpoints. Everything an owner
can reach carries `mask` instead.
"""
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# Providers an owner may store a key for. Kept in step with
# `agent/utils/owner_credential_utils.PROVIDER_ENV_MAP` and the validators in
# `chatbot_management/utils/api_key_validation.py` — a provider missing from either would
# be accepted here and then fail at validation or lookup.
SupportedProvider = Literal[
    "openai", "anthropic", "groq", "google", "gemini",
    "deepseek", "minimax",
]


class CredentialAddRequest(BaseModel):
    provider: SupportedProvider = Field(..., description="Provider to store the key for")
    api_key: str = Field(..., min_length=8, description="The provider API key (never stored in plaintext)")

    model_config = ConfigDict(json_schema_extra={
        "example": {"provider": "openai", "api_key": "sk-proj-..."}
    })


class CredentialData(BaseModel):
    provider: str = Field(..., description="Provider name")
    mask: str = Field(..., description="Masked key, e.g. 'sk-...48sA'")
    is_valid: bool = Field(..., description="Whether the key passed live validation")
    updated_at: str = Field(..., description="ISO 8601 timestamp of the last update")


class CredentialAddResponse(BaseModel):
    status: Literal["success"] = "success"
    data: CredentialData


class CredentialListResponse(BaseModel):
    status: Literal["success"] = "success"
    data: List[CredentialData] = Field(default_factory=list)


class CredentialDeleteResponse(BaseModel):
    status: Literal["success"] = "success"
    message: str = Field(..., description="Confirmation message")


class ProviderListResponse(BaseModel):
    """Providers this service can store and validate keys for.

    The usage service also returns `document_and_web_providers` (llamaparse, firecrawl).
    That field is dropped rather than returned empty: NL2SQL has no document-parsing or
    web-scraping path, so it would always be `[]` — noise in every response and a field
    the UI has to special-case. The dashboard already guards its use
    (`s.document_and_web_providers && ...forEach`), so its absence is handled.

    `gemini` is accepted on write but NOT advertised here: it is stored as `google`
    (see `canonical_provider`), so listing both would show one provider twice in a
    dropdown.
    """
    llm_providers: List[str]


class InternalCredentialResponse(BaseModel):
    """Master-key only — carries the DECRYPTED key."""
    provider: str
    api_key: str
    is_valid: bool


class InternalCredentialItem(BaseModel):
    """Master-key only — carries the DECRYPTED key."""
    owner_id: str
    provider: str
    api_key: str
    is_valid: bool


class InternalCredentialListResponse(BaseModel):
    data: List[InternalCredentialItem] = Field(default_factory=list)
