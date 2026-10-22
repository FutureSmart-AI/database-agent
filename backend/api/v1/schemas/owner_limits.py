"""Response schemas for the Usage screen's Limits tab."""
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class LimitItem(BaseModel):
    """One limit, with its usage and its escape route already resolved.

    Read `lifted` before `percent`. A lifted limit has `percent: None` and must be drawn
    without a progress bar — a bar against a ceiling nobody is enforcing is a lie the
    reader can act on. `maximum` still states the ceiling in words either way, so
    "lifted" never means the reader loses sight of what the cap actually is.

    `limit: null` is no limit at all: show `used` and the words, never a 0% bar.
    """
    key: str
    label: str
    used: float
    # None = unlimited. 0 = a real cap of zero, which blocks everything.
    limit: Optional[float] = None
    unit: str
    maximum: str
    note: str

    # Providers whose own key removes this limit. Empty means no key lifts it — only a
    # tier change does.
    lifted_by: List[str] = Field(default_factory=list)
    held: List[str] = Field(default_factory=list)
    missing: List[str] = Field(default_factory=list)
    lifted: bool = False

    # None whenever there is nothing to be a percentage of: unlimited, or lifted.
    percent: Optional[float] = None
    # "plan" | "plan-or-own-keys"
    raises: str = "plan"
    # Whether exceeding this actually stops anything. Only the daily chat cap does; every
    # other row is reporting, and the UI must not imply a consequence that does not exist.
    enforced: bool = False


class LimitGroup(BaseModel):
    group: str
    items: List[LimitItem]


class TierInfo(BaseModel):
    name: str
    tier_type: Optional[str] = None
    # True when this owner has no stored configuration row and is on the defaults.
    is_default: bool = False


class BillingWindow(BaseModel):
    """The fixed window period-scoped limits are measured over.

    Fixed on purpose: the Usage screen's period selector does NOT apply to the Limits tab,
    because a ceiling anchored to a window the reader can change is meaningless.
    """
    days: int
    start: str
    end: str


class OwnerLimitsResponse(BaseModel):
    """Everything the Limits tab renders, in one read.

    The consumption-source filter does not apply here either — a limit is enforced against
    every request the platform served, whichever key paid for it.
    """
    owner_id: str
    tier: TierInfo
    billing_window: BillingWindow
    own_credentials: List[str] = Field(default_factory=list)
    token_rate_usd: float
    groups: List[LimitGroup]
    # Keys of the limits with no headroom left. Only `queries_per_day` appearing here
    # actually stops anything.
    exceeded: List[str] = Field(default_factory=list)

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "owner_id": "someone@example.com",
            "tier": {"name": "Trial", "tier_type": "trial", "is_default": True},
            "billing_window": {"days": 30, "start": "2026-07-27T09:14:02Z",
                               "end": "2026-08-26T09:14:02Z"},
            "own_credentials": ["groq", "openai"],
            "token_rate_usd": 3.8e-06,
            "groups": [{
                "group": "Requests, tokens and cost",
                "items": [{
                    "key": "queries_per_day", "label": "Chat requests per day",
                    "used": 18, "limit": 20, "unit": "requests",
                    "maximum": "20 requests per rolling 24 hours",
                    "note": "Questions asked across every agent and the CSV agent...",
                    "lifted_by": [], "held": [], "missing": [], "lifted": False,
                    "percent": 90.0, "raises": "plan", "enforced": True,
                }],
            }],
            "exceeded": [],
        }
    })
