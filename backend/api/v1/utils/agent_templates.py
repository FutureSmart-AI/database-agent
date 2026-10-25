"""Business instructions applied when an agent is created.

Templates store prompt-only node records. Model/provider/temperature inherit the
current central operation profile, including file overrides. Explicit developer
node bindings retain their normal priority. Template instructions do not name
schema-specific tables or columns; database descriptions supply that context.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from types import SimpleNamespace

from logger import logger

# ---------------------------------------------------------------------------
# saas_founder
# ---------------------------------------------------------------------------
# Every line below was written after watching a real query get it wrong, and
# kept only if the score moved. The trial clause exists because "past its trial"
# was read as "has no trial", which silently deleted every customer who had ever
# converted from one. The status clause exists because `active` looks like it
# means "is a customer" and does not - a customer whose card just failed is
# still a customer. The refund clause exists because an agent disagreed with our
# own answer key about a refunded payment and turned out to be right.
_SAAS_FOUNDER_SQL_GEN = """How a SaaS business counts customers and money. Column and table names differ
from one company's database to the next, so find the ones carrying these
meanings in the schema you have been given, and apply the rules to those.

WHO COUNTS AS A CUSTOMER
Any figure about revenue, customer numbers, churn, retention or growth counts a
subscription only if ALL of the following hold - every one of them, every time:
  - the subscription is live on the date being asked about: it had started by
    then, and it had not ended by then. This is the condition most often left
    out, and leaving it out counts customers who cancelled months ago as
    current ones. A subscription with no end recorded is still running; one
    with an end date counts only for dates before it
  - the plan is a paid one, not a free or zero-price tier
  - the account belongs to a real customer, not to the company running the
    service: internal, test, demo and staff accounts are excluded. Whichever
    column marks them, join that table for it even when nothing else in the
    query needs that table
  - the subscription is no longer inside a trial. That is TWO cases, and both
    count: it never had a trial at all, or its trial ended on or before the
    date being asked about. Requiring the trial-end to be empty is wrong - it
    silently deletes every customer who converted from a trial, which is most
    of them
  - the subscription has taken at least one payment that succeeded. A payment
    that succeeded and was later refunded still counts: the money did change
    hands. This holds for EVERY revenue and customer figure, not only for
    churn and conversion - a subscription whose card has never once gone
    through is not recurring revenue, however live the row looks

Leave any one of them out and the figure is wrong in a way that still looks
plausible: internal accounts inflate revenue, free accounts inflate customer
counts, and trials that expired unpaid inflate churn.

A subscription that ended without ever taking a successful payment was a trial
that ran out. It never was a customer: it is not churn, and it is not a
conversion.

A subscription that ended at the moment another began on the same account is a
plan change or a seat change. That account is still a customer, not a loss, and
usually pays more than before.

WHAT A CUSTOMER PAYS, AGAINST WHAT WE HAVE COLLECTED
The recurring amount on the subscription is what a customer pays per month
right now. A payments or charges table is a history of money collected, and
summing it answers "how much has this customer ever paid us", which is a
different and usually much larger number. Revenue per month, per country, per
plan or per channel comes from the subscription's recurring amount - not from
adding up payment rows.

A status column records a row's present state, not its history. Whether a
subscription was live on a given date comes from its start and end timestamps,
so "paying now" and "paying last month" are date comparisons and never a status
compared to 'active'.

TRIALS
A trial belongs to a subscription, not to an account. Count trial
subscriptions, and treat a trial as converted when THAT subscription took a
successful payment - not when its account has paid something at some point.

"How many converted last month" is anchored on the TRIAL, not the payment: the
trial ended within that month, and that subscription went on to pay. Anchoring
on the payment date instead counts every customer who happened to be billed
that month, which is all of them.

HOW LONG A CUSTOMER STAYS
Tenure is measured per subscription, from its start to its end. Where an
account has held several, add those spans together rather than measuring from
the first start to the last end - the gap between two subscriptions is not time
spent as a customer. Say whether the figure covers customers who have already
left, customers still active, or both; mixing them without saying so overstates
how long people stay.

WHAT SOMETHING COSTS US, AGAINST WHAT A CUSTOMER PAYS
What a plan charges, and what a subscription bills per month, is revenue: what
the customer pays us. Neither is ever a cost. What serving a customer costs the
business lives in the usage or event data, per action. So what the free tier
costs us is a sum over usage, not a look at the free plan's price.

Usage and event tables are cumulative - every action ever recorded - and carry
no period of their own. Summed unfiltered they set a lifetime of cost against a
single month of revenue, which is several times too large. A monthly cost is
the last 30 days of usage, selected by a date filter; it is NOT the whole table
divided by the number of days. Reduce usage to one row per account for that
period BEFORE joining it to the subscription rows; joined directly, each
subscription repeats once per event and revenue is multiplied by the event
count.

PAYMENTS
A payment or charge table usually holds one row per ATTEMPT to collect, not one
per payment received, so a retried bill appears several times and totals taken
across rows count it repeatedly. Group to the invoice or bill before summing
any amount.

Revenue lost to failed collection is every invoice where NO attempt ever
succeeded. Do not start from the invoices that carry a failed attempt: an
invoice can go unpaid without a failure recorded against it, and those are lost
revenue too. Equally, an invoice that failed once and was then paid is not lost
at all.

WHAT TO DO WITH A RATIO
When a question compares two things - churn in money against churn in
customers, revenue by one plan type against another - give the rate or the
percentage as well as the absolute figures, and state the base each rate is
measured against. Two dollar amounts on their own do not answer a question
about which is worse."""


TEMPLATES: Dict[str, Dict[str, Any]] = {
    "saas_founder": {
        "label": "SaaS founder",
        "description": (
            "Subscription business questions - MRR, churn, retention, trial "
            "conversion, unit economics - with the definitions a founder means "
            "by them."
        ),
        "nodes": {
            "sql_gen": {
                "prompt": _SAAS_FOUNDER_SQL_GEN,
            },
        },
    },
}


def list_templates() -> List[Dict[str, str]]:
    """Templates a caller may choose from, for a picker at agent creation."""
    return [
        {"template_id": tid, "label": t["label"], "description": t["description"]}
        for tid, t in TEMPLATES.items()
    ]


def get_template(template_id: Optional[str]) -> Optional[Dict[str, Any]]:
    return TEMPLATES.get(template_id) if template_id else None


async def apply_template(agent_id: str, template_id: str,
                         user_id: Optional[str] = None) -> Dict[str, Any]:
    """Write a template's node configuration onto a freshly created agent.

    Returns a summary of what was applied. Never raises: a template that fails
    to apply must not fail the agent creation that requested it - the caller
    ends up with a working, unconfigured agent and a logged error, which is the
    state they would have been in without a template at all.
    """
    template = get_template(template_id)
    if not template:
        logger.warning("[template] unknown template_id=%s for agent=%s", template_id, agent_id)
        return {"applied": False, "reason": "unknown template_id: %s" % template_id}

    # Templates supply business instructions, not a provider override. The ORM
    # already permits null bindings; the runtime inherits the current operation
    # profile for this prompt-only record. Public model edits still use NodeConfig
    # and require an explicit complete binding.
    from chatbot_management.db_utils.chatbot_node_db_utils import upsert_node_configs_in_db

    configs = [
        SimpleNamespace(
            node_name=node_name,
            provider=None,
            model=None,
            temperature=None,
            prompt=cfg.get("prompt"),
        )
        for node_name, cfg in (template.get("nodes") or {}).items()
    ]

    try:
        await upsert_node_configs_in_db(agent_id, configs, user_id=user_id)
    except Exception as e:  # noqa: BLE001
        logger.error("[template] %s failed on agent=%s: %s", template_id, agent_id, e)
        return {"applied": False, "reason": str(e)[:200]}

    logger.info("[template] applied %s to agent=%s (%d node(s))",
                template_id, agent_id, len(configs))
    return {
        "applied": True,
        "template_id": template_id,
        "label": template["label"],
        "nodes": [c.node_name for c in configs],
    }
