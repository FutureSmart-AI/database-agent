"""Constants and derivations behind the Usage screen's Limits tab.

Every row on that tab obeys two rules, and they are the reason this module exists rather
than the numbers being inlined at the call site:

* **Each limit declares how it is lifted.** A `plan` limit moves by changing tier. An
  `own-keys` limit exists only because the work ran on FutureSmart platform credentials,
  so the owner can remove it themselves by bringing their own key.

* **A limit the owner has already lifted carries no progress figure.** A bar drawn
  against a ceiling nobody is enforcing is a lie the reader can act on, so `lifted` items
  report `percent: None` and still state the ceiling as a number.

WHAT THE TAB DELIBERATELY IGNORES. Neither the consumption-source filter nor the period
selector applies to it. A limit is enforced against every request the platform served,
whichever key paid for it, and a ceiling anchored to a window the reader can change is
meaningless — so the window here is fixed and stated instead.

ONLY ONE OF THESE CAPS BLOCKS ANYTHING. `max_queries_per_day` is enforced: chat returns
429 past it. Every other row is reporting. The `enforced` flag on each item says which is
which, so the UI never implies a consequence that does not exist.
"""
import os
from typing import Optional

# The billing window every period-scoped limit is measured over. Fixed rather than taken
# from the screen's period selector — see the module docstring.
LIMIT_WINDOW_DAYS = 30

# Dollars per token, used to turn recorded tokens into the estimated spend the tab shows.
# An estimate, not a bill: it is a single blended rate applied to token counts, and the
# provider's own invoice is the authority on anything billed to the owner's own keys.
#
# Environment-overridable because it is a commercial number that will change without a
# code release being the right way to change it.
TOKEN_RATE_USD = float(os.getenv("USAGE_TOKEN_RATE_USD", "0.0000038"))

# Caps that the Limits tab reports but that are NOT yet per-owner columns on
# `nl2sql_owner_config`, so they cannot be raised for one customer with the PATCH that
# raises the others. Promoting one to per-owner means a migration plus an entry in
# SETTABLE_LIMITS; until then these apply to everybody and that is stated in the note.
MAX_DATABASES = 15
# None means genuinely no limit — nothing caps how many databases one agent routes
# between. Reported so the reader can see their largest agent, not to imply a ceiling.
MAX_DATABASES_PER_AGENT: Optional[int] = None

# `tier_type` on nl2sql_owner_config is a slug; this is what a customer should read.
TIER_LABELS = {"trial": "Trial", "payg": "Pay as you go", "custom": "Custom"}


def tier_label(tier_type: Optional[str]) -> str:
    """Human-readable tier name. Unknown slugs are titled rather than hidden."""
    if not tier_type:
        return "Trial"
    return TIER_LABELS.get(tier_type, tier_type.replace("_", " ").title())


def estimated_cost(tokens: float) -> float:
    """Estimated spend for a token count, at the blended rate. Never rounded here."""
    return float(tokens or 0) * TOKEN_RATE_USD


def cost_ceiling(token_ceiling: Optional[int], tokens_used: float,
                 cost_used: float) -> Optional[float]:
    """The spend ceiling implied by the token ceiling, at this workspace's own rate.

    DERIVED, NOT POLICY, and deliberately UNROUNDED. The cost bar and the token bar
    describe the same consumption, so they must read the same percentage. Because the
    ceiling is `blended_rate * token_ceiling` and spend is `blended_rate * tokens_used`,
    the two percentages are equal by construction — but only while the ceiling stays
    unrounded.

    Rounding this to a tidy figure breaks exactly that: rounding a true $2.28 ceiling up
    to $5.00 makes the cost bar read 25% while the token bar reads 56% for identical
    usage. Two bars disagreeing about one number is the defect this derivation prevents,
    so do not "tidy" the result. A round ceiling is also a CHOSEN ceiling, and a chosen
    ceiling cannot answer "where did that come from".

    The blended rate is taken from actuals where there are any, so this stays correct if
    per-model pricing ever replaces the single rate above.
    """
    if token_ceiling is None:
        return None
    blended = (cost_used / tokens_used) if tokens_used else TOKEN_RATE_USD
    return blended * token_ceiling
