from sqlmodel import SQLModel, Field
from typing import Optional, List
from datetime import datetime
from sqlalchemy import (
    Column, JSON, Text, PrimaryKeyConstraint,
    String, TIMESTAMP, BigInteger, ForeignKey, Index, text, Boolean, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB, NUMERIC
from uuid import UUID, uuid4
from decimal import Decimal
from datetime import timezone
from typing import Dict, Any

class Users(SQLModel, table=True):
    __tablename__ = "users"
    user_id: str = Field(primary_key=True)
    email_id: str = Field(index=True)
    user_name: Optional[str] = None
    deleted: bool = Field(default=False)

class ChatbotConnection(SQLModel, table=True):
    __tablename__ = "chatbot_connection"
    # Multi-DB: PK moved from chatbot_id to db_id so an agent can have many databases.
    db_id: str = Field(primary_key=True, index=True)  # DB_<8hex>
    user_id: str = Field(index=True)
    owner_id: Optional[str] = Field(default=None, index=True)  # owning agent's owner email — avoids a chatbot_details join for shared agents
    chatbot_id: Optional[str] = Field(default=None, index=True)  # no longer unique; kept for legacy joins
    agent_id: Optional[str] = Field(default=None, index=True)  # now 1:N — many rows per agent
    db_host: str
    db_name: str
    db_user: str
    db_password: str
    db_port: int = Field(default=3306)
    db_engine: str
    description: Optional[str] = Field(default=None, sa_column=Column(Text))
    is_active: bool = Field(default=True)
    status: Optional[str] = Field(default="untested")  # untested | connected | error
    description_source: Optional[str] = Field(default=None)      # manual | auto (None until a description exists)
    description_updated_at: Optional[datetime] = None            # when the description was last written
    table_count: Optional[int] = None
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_by: Optional[str] = Field(default=None, index=True)  # acting dashboard user on last edit; user_id above is the fixed creator
    # Soft delete: detaching a database keeps the row as a tombstone so the deletion is
    # auditable. Every reader must filter `deleted == False`.
    deleted: bool = Field(default=False, index=True)
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[str] = Field(default=None, index=True)  # acting dashboard user on the delete

class ChatSessions(SQLModel, table=True):
    __tablename__ = "chat_sessions"
    session_id: str = Field(primary_key=True)
    chatbot_id: str = Field(index=True)
    agent_id: Optional[str] = Field(default=None, index=True)  # New field for RESTful API
    user_id: Optional[str] = Field(default=None, index=True)  # Made optional for guest users
    session_title: Optional[str] = None
    display_message: Optional[str] = None
    created_time: Optional[datetime] = Field(default_factory=datetime.now)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)  # last dashboard touch (rename/delete)
    updated_by: Optional[str] = Field(default=None, index=True)  # acting dashboard user on last edit (None for internal/API-key)
    deleted: bool = Field(default=False)
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[str] = Field(default=None, index=True)  # acting dashboard user on the soft delete

class FewShotExamples(SQLModel, table=True):
    __tablename__ = "few_shot_examples"
    chatbot_id: str = Field(primary_key=True, index=True)
    db_id: Optional[str] = Field(default=None, primary_key=True, index=True)  # Multi-DB scope
    agent_id: Optional[str] = Field(default=None, index=True)  # New field for RESTful API
    user_id: Optional[str] = Field(default=None, index=True)  # Made optional for guest users
    file_name: Optional[str] = None
    url: Optional[str] = None
    few_shot_examples: Optional[str] = Field(default=None, sa_column=Column(Text))
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_by: Optional[str] = Field(default=None, index=True)  # acting dashboard user on last edit (None for internal/API-key)
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[str] = Field(default=None, index=True)  # acting dashboard user on the delete

class IssuedTokens(SQLModel, table=True):
    __tablename__ = "issued_tokens"
    token_id: Optional[int] = Field(default=None, primary_key=True)
    token: str = Field(index=True)
    email_id: str = Field(index=True)
    session_id: str = Field(index=True)
    issued_at: Optional[datetime] = Field(default_factory=datetime.utcnow)

class ApiKeys(SQLModel, table=True):
    __tablename__ = "api_keys"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[str] = Field(default=None, index=True)  # Made optional for guest users
    chatbot_id: Optional[str] = Field(default=None, index=True)
    agent_id: Optional[str] = Field(default=None, index=True)  # New field for RESTful API
    api_key: str = Field(unique=True, index=True)
    is_active: bool = Field(default=True)
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    revoked_at: Optional[datetime] = None

class TableDescription(SQLModel, table=True):
    __tablename__ = "table_descriptions"
    user_id: Optional[str] = Field(default=None, index=True)  # Made optional for guest users
    chatbot_id: str = Field(primary_key=True, index=True)
    db_id: Optional[str] = Field(default=None, primary_key=True, index=True)  # Multi-DB scope
    agent_id: Optional[str] = Field(default=None, index=True)  # New field for RESTful API
    file_name: Optional[str] = None
    url: Optional[str] = None
    description: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    entry_flags: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_by: Optional[str] = Field(default=None, index=True)  # acting dashboard user on last edit (None for internal/API-key)
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[str] = Field(default=None, index=True)  # acting dashboard user on the last description delete
    high_cardinality_columns: Optional[dict] = Field(default=None, sa_column=Column("high_cardinality_columns", JSON))

class ColumnDescription(SQLModel, table=True):
    __tablename__ = "column_descriptions"
    user_id: Optional[str] = Field(default=None, index=True)  # Made optional for guest users or master key
    chatbot_id: str = Field(primary_key=True, index=True)
    db_id: Optional[str] = Field(default=None, primary_key=True, index=True)  # Multi-DB scope
    agent_id: Optional[str] = Field(default=None, index=True)  # New field for RESTful API
    table_name: str = Field(primary_key=True, index=True)
    column_descriptions: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)

class HCColumnProfiles(SQLModel, table=True):
    __tablename__ = "hc_column_profiles"
    __table_args__ = (PrimaryKeyConstraint("chatbot_id", "db_id", "table_name"),)
    chatbot_id: str = Field(index=True)
    db_id: str = Field(default="", index=True)  # Multi-DB scope (part of composite PK)
    agent_id: Optional[str] = Field(default=None, index=True)
    table_name: str = Field(index=True)
    column_profiles: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    profiled_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)

class ChatbotDetails(SQLModel, table=True):
    __tablename__ = "chatbot_details"
    user_id: Optional[str] = Field(default=None)  # Made optional for guest users
    chatbot_id: str = Field(primary_key=True)
    agent_id: Optional[str] = Field(default=None, index=True)  # New field for RESTful API
    owner_id: Optional[str] = Field(default=None, index=True)  # Owner email address
    chatbot_name: str
    system_prompt: Optional[str] = None
    service_description: Optional[str] = Field(default=None, sa_column=Column(Text))
    llm_provider: Optional[str] = Field(default=None, sa_column=Column("provider", Text))
    model: Optional[str] = None
    temperature: Optional[float] = None
    greet_message: Optional[str] = None
    debug_info: Optional[bool] = Field(default=False)
    show_sql_query: Optional[bool] = Field(default=True)
    show_db_result: Optional[bool] = Field(default=True)
    graph_output: Optional[bool] = Field(default=True)
    allowed_graphs: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    # Answer settings the dashboard's Settings screen owns. Each is the saved default for the
    # agent; a chat request may still override it per call.
    follow_up: Optional[bool] = Field(default=False)
    voice_input_enabled: Optional[bool] = Field(default=False)
    voice_output_enabled: Optional[bool] = Field(default=False)
    suggested_questions: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    max_query_execution_time: Optional[int] = Field(default=30)
    enable_query_caching: Optional[bool] = Field(default=True)
    default_max_tokens: Optional[int] = Field(default=1500)
    # A demo agent appears in EVERY signed-in user's agent list, at viewer standing
    # (chat, messages and feedback - no settings, no credentials, no deletion). It
    # exists so a new user can ask a real question on their first visit instead of
    # having to connect a database before seeing anything work. Ownership is
    # unchanged: owner_id still names the one account that can edit it.
    is_demo: Optional[bool] = Field(default=False, index=True)

    # Public-access policy for the two anonymous surfaces. The embedded widget and the
    # full-screen share link are independent policies: each has its own opt-in flag and its
    # own Origin allowlist, never combined or intersected. An empty allowlist means "any
    # origin", which only takes effect once the matching is_public flag is on.
    is_public: Optional[bool] = Field(default=False)
    allowed_domains: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    fullscreen_is_public: Optional[bool] = Field(default=False)
    fullscreen_allowed_domains: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    created_at: Optional[datetime] = Field(default_factory=datetime.now)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)  # last modification (any write)
    updated_by: Optional[str] = Field(default=None, index=True)  # acting dashboard user on last edit (None for internal/API-key); distinct from fixed owner_id
    deleted: bool = Field(default=False)
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[str] = Field(default=None, index=True)  # acting dashboard user on the soft delete

class ChatbotInvitations(SQLModel, table=True):
    """A collaborator on an agent. One row = one person granted access, at one role.

    Emails are stored lowercased: role resolution matches the caller's signed-in email against
    `invited_user_email`, and a casing difference would leave the user invited but denied every
    role. `add_invitation_roles` normalises the existing rows and enforces uniqueness on
    (agent_id, lower(invited_user_email)), so a person cannot hold two roles on one agent.
    """
    __tablename__ = "chatbot_invitations"
    invitation_id: Optional[int] = Field(default=None, primary_key=True)
    chatbot_id: str = Field(index=True)
    agent_id: Optional[str] = Field(default=None, index=True)  # New field for RESTful API
    invited_user_email: str = Field(index=True)
    invited_by_email: str = Field(index=True)
    # viewer | editor. Owners are not stored here at all — ownership is chatbot_details.owner_id.
    role: Optional[str] = Field(default="viewer")
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_by: Optional[str] = Field(default=None, index=True)  # acting user on the last role change

class ChatbotNodeConfig(SQLModel, table=True):
    __tablename__ = "chatbot_node_config"
    id: Optional[int] = Field(default=None, primary_key=True)
    chatbot_id: str = Field(index=True)
    agent_id: Optional[str] = Field(default=None, index=True)  # New field for RESTful API
    user_id: Optional[str] = Field(default=None, index=True)  # acting user on last dashboard write (None for internal/API-key)
    node_name: str = Field(index=True)
    provider: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    is_default: Optional[bool] = Field(default=False)
    prompt: Optional[str] = Field(default=None, sa_column=Column(Text))
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_by: Optional[str] = Field(default=None, index=True)  # acting dashboard user on last edit (None for internal/API-key)
    deleted_at: Optional[datetime] = None
    deleted_by: Optional[str] = Field(default=None, index=True)  # acting dashboard user on the delete

class ChatLogs(SQLModel, table=True):
    __tablename__ = "nl2sql_logs"
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: str = Field(index=True)
    user_id: Optional[str] = Field(default=None, index=True)  # Made optional for guest users
    agent_id: Optional[str] = Field(default=None, index=True)  # Agent ID
    chat_id: str = Field(index=True)
    user_query: Optional[str] = Field(default=None, sa_column=Column("query", Text))
    refined_query: Optional[str] = None
    sql_query: Optional[str] = None
    db_output: Optional[str] = None
    gpt_response: Optional[str] = Field(default=None, sa_column=Column("response", Text))
    graph_output: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    # The built answer payload for this turn, stored so it can be replayed later. The
    # scalar columns above cannot carry it: `selected_tables` has no column at all, and
    # `db_output` holds bare rows with the column names dropped, so a reader rebuilding
    # from them loses the sources and the table headers permanently.
    #
    # WRITE-ONLY for now. Nothing serves these yet — the response shape stays exactly as
    # it was — because changing keys the dashboard already reads is what broke its Data /
    # Sources / Execution panels. Storing first means the information still exists when a
    # reader is added additively, instead of being lost turn by turn.
    #
    # Assign the dict itself — never json.dumps into a JSON column, or readers get a str.
    debug_info: Optional[dict] = Field(default=None, sa_column=Column("debug_info", JSON))
    chart_output: Optional[dict] = Field(default=None, sa_column=Column("chart_output", JSON))
    gpt_response_time: Optional[str] = None
    db_fetch_time: Optional[str] = None
    tokens_consumed: Optional[str] = None
    is_graph_output: Optional[bool] = None
    is_debug_mode: Optional[bool] = None
    is_answered: Optional[bool] = None
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    feedback: Optional[str] = None

class AgentHealthEvent(SQLModel, table=True):
    """One row per chat query — the analytics store behind the Agent Health APIs.

    Separate from `nl2sql_logs` on purpose: that table is the conversation transcript
    (what the user saw), this one is the per-query health record (how the run went).
    They share `chat_id`, which is also the idempotency key here — a retried write for
    the same query updates nothing rather than double-counting it.

    `cost_usd` stays NULL while a run is unpriced; readers must never coerce it to 0,
    or unpriced spend is silently counted as free. `cost_complete` carries that fact
    per row so a window can report whether its total is a lower bound.
    """
    __tablename__ = "nl2sql_agent_health_events"
    id: Optional[int] = Field(default=None, primary_key=True)
    event_type: Optional[str] = Field(default="agent_query")
    schema_version: Optional[int] = Field(default=1)
    event_ts: Optional[datetime] = Field(default_factory=datetime.utcnow, index=True)

    # identity — mirrors nl2sql_logs so the two join cleanly
    agent_id: Optional[str] = Field(default=None, index=True)
    owner_id: Optional[str] = Field(default=None, index=True)
    user_id: Optional[str] = Field(default=None, index=True)
    session_id: Optional[str] = Field(default=None, index=True)
    chat_id: str = Field(index=True, unique=True)  # idempotency key
    request_id: Optional[str] = Field(default=None, index=True)
    trace_id: Optional[str] = Field(default=None)          # LangSmith trace
    langsmith_run_id: Optional[str] = Field(default=None)  # root run, for direct read_run

    # what was asked
    query: Optional[str] = Field(default=None, sa_column=Column(Text))
    refined_query: Optional[str] = Field(default=None, sa_column=Column(Text))

    # how it was answered — NL2SQL routing, not the orchestrator's service routing
    route: Optional[str] = Field(default=None, index=True)   # sql | cross_db | pandas | direct_answer
    nodes_used: Optional[list] = Field(default=None, sa_column=Column(JSON))
    db_id: Optional[str] = Field(default=None, index=True)   # DB the db_router picked
    db_ids: Optional[list] = Field(default=None, sa_column=Column(JSON))  # cross-DB fan-out set
    cross_db: Optional[bool] = Field(default=False)
    sql_query: Optional[str] = Field(default=None, sa_column=Column(Text))
    selected_tables: Optional[list] = Field(default=None, sa_column=Column(JSON))
    rows_returned: Optional[int] = Field(default=None)
    chart_generated: Optional[bool] = Field(default=False)
    pandas_used: Optional[bool] = Field(default=False)

    # outcome
    status: Optional[str] = Field(default=None, index=True)   # answered | no_answer | error
    is_answered: Optional[bool] = Field(default=False, index=True)
    failure_category: Optional[str] = Field(default=None, index=True)
    failed_stage: Optional[str] = Field(default=None, index=True)  # node name
    failure_detail: Optional[str] = Field(default=None, sa_column=Column(Text))
    from_widget: Optional[bool] = Field(default=False)
    key_type: Optional[str] = Field(default=None)  # platform-key | own-key

    # metrics
    latency_ms: Optional[int] = Field(default=0)
    db_fetch_ms: Optional[int] = Field(default=0)   # connection-details fetch, NL2SQL-specific
    sql_exec_ms: Optional[int] = Field(default=0)   # time inside the customer database
    input_tokens: Optional[int] = Field(default=0)
    output_tokens: Optional[int] = Field(default=0)
    total_tokens: Optional[int] = Field(default=0)
    cost_usd: Optional[float] = Field(default=None)          # NULL while unpriced
    cost_complete: Optional[bool] = Field(default=False)
    retry_count: Optional[int] = Field(default=0)
    provider: Optional[str] = Field(default=None)
    model: Optional[str] = Field(default=None, index=True)
    # per-node breakdown: [{node_name, provider, model, input_tokens, output_tokens,
    # total_tokens, latency_ms, calls, errors, total_cost}, ...]
    node_data: Optional[list] = Field(default=None, sa_column=Column(JSON))

    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)


class DescriptionGenerationJobs(SQLModel, table=True):
    __tablename__ = "description_generation_jobs"
    job_id: str = Field(primary_key=True)  # JOB_<8hex>
    agent_id: Optional[str] = Field(default=None, index=True)
    db_id: Optional[str] = Field(default=None, index=True)
    status: str = Field(default="running")  # running | done | failed
    description: Optional[str] = Field(default=None, sa_column=Column(Text))
    error: Optional[str] = Field(default=None, sa_column=Column(Text))
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)

class WidgetsSettings(SQLModel, table=True):
    __tablename__ = "widgets_settings"
    id: Optional[int] = Field(default=None, primary_key=True)
    chatbot_id: Optional[str] = Field(default=None, index=True)
    agent_id: Optional[str] = Field(default=None, index=True)
    user_id: Optional[str] = Field(default=None, index=True)  # fixed owner, set once at creation
    heading: Optional[str] = None
    sub_heading: Optional[str] = None
    greet_message: Optional[str] = None
    color: Optional[str] = None
    show_sources: Optional[bool] = None
    widget_icon: Optional[str] = None    # URL, either uploaded to S3 or supplied directly
    widget_avatar: Optional[str] = None  # URL, same
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    # Soft delete, so removing a widget's settings stays auditable. Every reader filters
    # `deleted == False`.
    deleted: bool = Field(default=False, index=True)
    # Kept separate from user_id so updating or deleting never overwrites the owner.
    updated_by: Optional[str] = Field(default=None, index=True)
    deleted_by: Optional[str] = Field(default=None, index=True)
    deleted_at: Optional[datetime] = None


# ============================================================================
# Owner provider credentials (BYOK) — NL2SQL's own copy of the credential store.
#
# Ported from fs-agent-usage-limits (`services/database_models_credentials.py`).
# Every LLM node asks for the owner's own provider key before falling back to the
# platform key; that lookup used to be an HTTP call to the usage service
# (`GET /v1/owners/{owner}/credentials/{provider}/internal`) from 20 call sites.
#
# The plaintext key is NEVER stored. Three columns stand in for it:
#   encrypted_key  Fernet ciphertext — needs APP_MASTER_KEY to read
#   key_hash       HMAC-SHA256 with HASH_SALT — lets a duplicate be detected
#                  without decrypting anything, and is not reversible
#   key_mask       "sk-...48sA" for display, so the UI never needs the real key
#
# Both secrets MUST match the usage service's, or rows copied across from it are
# permanently undecryptable.
# ============================================================================

class UserProviderKeys(SQLModel, table=True):
    __tablename__ = "user_provider_keys"

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column("id", PG_UUID(as_uuid=True), primary_key=True, nullable=False),
    )

    # The owner the key belongs to (an email, matching chatbot_details.owner_id).
    owner_id: str = Field(
        sa_column=Column("owner_id", String(255), nullable=False),
    )

    # Provider slug: openai | anthropic | groq | google | deepseek | minimax | ...
    provider: str = Field(
        sa_column=Column("provider", String(100), nullable=False),
    )

    encrypted_key: str = Field(
        sa_column=Column("encrypted_key", Text, nullable=False),
    )
    # 64-char hex HMAC-SHA256. Used for duplicate detection only — never for lookup
    # by key, and never reversible back to the key itself.
    key_hash: str = Field(
        sa_column=Column("key_hash", String(64), nullable=False),
    )
    key_mask: str = Field(
        sa_column=Column("key_mask", String(50), nullable=False),
    )

    # Result of the live provider check at write time. A key that stops working is
    # marked invalid rather than deleted, so the owner can see why it failed.
    is_valid: bool = Field(
        default=True,
        sa_column=Column("is_valid", Boolean, nullable=False, server_default=text("true")),
    )
    last_used_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column("last_used_at", TIMESTAMP(timezone=True), nullable=True),
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column("created_at", TIMESTAMP(timezone=True),
                         server_default=text("CURRENT_TIMESTAMP"), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column("updated_at", TIMESTAMP(timezone=True),
                         server_default=text("CURRENT_TIMESTAMP"), nullable=False),
    )

    __table_args__ = (
        # One key per owner per provider — an upsert target, so adding a second key
        # for the same provider replaces it instead of quietly creating a rival row.
        UniqueConstraint("owner_id", "provider", name="user_provider_keys_owner_id_provider_key"),
        Index("idx_keys_owner_provider", "owner_id", "provider"),
    )

class Nl2sqlOwnerConfig(SQLModel, table=True):
    """Per-owner NL2SQL settings: tier, the caps NL2SQL can actually enforce, and
    whether the service is switched on for them.

    A DELIBERATE SUBSET of the usage service's `owner_configurations` +
    `owner_platform_limits`. Only fields NL2SQL can answer for itself are kept:

      kept      tier_type, max_agents, max_llm_tokens_per_month, max_team_members,
                nl2sql_enabled
                — every one is countable from this database (`chatbot_details`,
                  `nl2sql_agent_health_events`, `chatbot_invitations`).

      omitted   max_indexed_characters, max_file_size_mb   -> the knowledge service's
                max_conversations_per_month,
                max_messages_per_month                     -> the chat service counts these
                enabled_services for the other five services -> not NL2SQL's to answer;
                  six services each holding a copy would give six answers to one question
                default_models                              -> NL2SQL already has better:
                  `model_config.json` plus per-node overrides in `chatbot_node_config`

    NULL on a cap means unlimited, matching the usage service. An owner with no row at
    all falls back to `chatbot_management/utils/owner_defaults.py` — the API always
    answers, so a customer who has never been configured is not a 404.
    """
    __tablename__ = "nl2sql_owner_config"

    # The owner's email, lower-cased. Matches chatbot_details.owner_id, which this
    # database stores lower-case everywhere (718 agents, 0 exceptions).
    owner_id: str = Field(primary_key=True)

    tier_type: str = Field(default="trial")          # trial | payg | custom
    base_tier: Optional[str] = Field(default=None)   # set only for custom tiers

    # Caps. NULL = unlimited.
    max_agents: Optional[int] = Field(default=None)
    max_llm_tokens_per_month: Optional[int] = Field(default=None)
    max_team_members: Optional[int] = Field(default=None)
    # The one cap this service ENFORCES: chat is refused with 429 past it. Counted over a
    # ROLLING 24 hours, not a calendar day, so the allowance returns by itself as the oldest
    # queries age out — no reset job to run, and no midnight cliff.
    # NULL = unlimited. The default is 20; see the add_owner_query_cap migrations.
    max_queries_per_day: Optional[int] = Field(default=None)

    # Whether NL2SQL is enabled for this owner at all.
    nl2sql_enabled: bool = Field(default=True)
    nl2sql_enabled_at: Optional[datetime] = Field(default=None)

    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    # Acting dashboard user on the last edit — same convention as the rest of this repo.
    updated_by: Optional[str] = Field(default=None, index=True)

# ============================================================================
# Usage events — NL2SQL's own copy of the usage-tracking store.
#
# Ported from fs-agent-usage-limits (`services/database_models_usage_events.py`).
# NL2SQL used to POST every event to that service over HTTP and keep nothing locally:
# an outage lost the data, and nothing here could read its own usage back.
#
# WHY THIS EXISTS ALONGSIDE nl2sql_agent_health_events — they answer different questions:
#   agent health  one row per CHAT QUERY, agent-scoped, since 2026-08-13 (per-node
#                 breakdown, failure stage, route). Answers "how is this agent doing?"
#   usage events  one row per OPERATION (each LLM call, SQL exec, chart), OWNER-scoped,
#                 with full history. Answers "what is this customer using?"
# The Usage & Limits screen is owner-level with months of history, which the health table
# cannot serve — it is agent-level and only as old as the feature.
#
# One deliberate difference from the source schema: `owner_id` carries NO foreign key.
# Upstream it references `owner_configurations.owner_id`; here an owner is the email on
# `chatbot_details.owner_id`, so it is a plain indexed string.
# ============================================================================

class UsageEvent(SQLModel, table=True):
    __tablename__ = "usage_events"

    event_id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column("event_id", PG_UUID(as_uuid=True), primary_key=True, nullable=False),
    )

    # Nullable: widget/anonymous traffic and internal jobs legitimately have no owner.
    owner_id: Optional[str] = Field(
        default=None, sa_column=Column("owner_id", String(255), nullable=True))

    # 'platform-key' or 'owner-key' — whose credentials paid for the call. Drives whether
    # the spend is billable to the platform or already covered by the customer (BYOK).
    key_type: Optional[str] = Field(
        default=None, sa_column=Column("key_type", String(50), nullable=True))

    agent_id: Optional[str] = Field(
        default=None, sa_column=Column("agent_id", String(255), nullable=True))
    service_id: Optional[str] = Field(
        default=None, sa_column=Column("service_id", String(255), nullable=True))

    service_type: str = Field(sa_column=Column("service_type", String(100), nullable=False))
    operation: str = Field(sa_column=Column("operation", String(100), nullable=False))
    label: Optional[str] = Field(
        default=None, sa_column=Column("label", String(100), nullable=True))

    session_id: Optional[str] = Field(
        default=None, sa_column=Column("session_id", String(255), nullable=True))
    request_id: Optional[str] = Field(
        default=None, sa_column=Column("request_id", String(255), nullable=True))
    operation_id: Optional[str] = Field(
        default=None, sa_column=Column("operation_id", String(255), nullable=True))

    # When the operation happened, as reported by the caller — not when it was stored.
    timestamp: datetime = Field(
        sa_column=Column("timestamp", TIMESTAMP(timezone=True), nullable=False))

    # Python attribute is `event_metadata` because `metadata` is reserved by SQLAlchemy;
    # the database column is still called `metadata`.
    event_metadata: Optional[Dict[str, Any]] = Field(
        default=None, sa_column=Column("metadata", JSONB))

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column("created_at", TIMESTAMP(timezone=True),
                         server_default=text("CURRENT_TIMESTAMP"), nullable=False))

    # Partial indexes on the nullable attribution columns: most rows populate only one or
    # two of them, so indexing the NULLs would be dead weight on a hot write path.
    __table_args__ = (
        Index("idx_events_owner_time", "owner_id", "timestamp",
              postgresql_where=text("owner_id IS NOT NULL")),
        Index("idx_events_key_type_time", "key_type", "timestamp",
              postgresql_where=text("key_type IS NOT NULL")),
        Index("idx_events_agent_time", "agent_id", "timestamp",
              postgresql_where=text("agent_id IS NOT NULL")),
        Index("idx_events_service_op", "service_type", "operation", "timestamp"),
        Index("idx_events_session", "session_id", "timestamp",
              postgresql_where=text("session_id IS NOT NULL")),
        Index("idx_events_request", "request_id", "timestamp",
              postgresql_where=text("request_id IS NOT NULL")),
        Index("idx_events_service_id", "service_id", "timestamp",
              postgresql_where=text("service_id IS NOT NULL")),
        Index("idx_events_timestamp", "timestamp"),
        # The analytics API filters inside metadata (provider, model), so GIN not btree.
        Index("idx_events_metadata_gin", "metadata", postgresql_using="gin"),
    )


class UsageMetricRow(SQLModel, table=True):
    """One measurement belonging to a usage event (tokens, seconds, rows returned...).

    Class name differs from the usage service's `UsageMetric` on purpose: the request
    schema in `api/v1/schemas/usage_events.py` already owns that name as a Pydantic model,
    and having a table and a request model share it is how the wrong one gets imported.
    The table name `usage_metrics` is unchanged.
    """
    __tablename__ = "usage_metrics"

    metric_id: Optional[int] = Field(
        default=None,
        sa_column=Column("metric_id", BigInteger, primary_key=True,
                         autoincrement=True, nullable=False))

    # CASCADE: a metric is meaningless without its event, so deleting the event takes its
    # metrics with it rather than leaving orphans.
    event_id: UUID = Field(
        sa_column=Column("event_id", PG_UUID(as_uuid=True),
                         ForeignKey("usage_events.event_id", ondelete="CASCADE"),
                         nullable=False))

    metric_name: str = Field(sa_column=Column("metric_name", String(100), nullable=False))
    # NUMERIC(20,4) holds token counts and second-precision durations in one column
    # without float drift when summed over a reporting window.
    metric_value: Decimal = Field(sa_column=Column("metric_value", NUMERIC(20, 4), nullable=False))

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column("created_at", TIMESTAMP(timezone=True),
                         server_default=text("CURRENT_TIMESTAMP"), nullable=False))

    __table_args__ = (
        Index("idx_metrics_event", "event_id"),
        Index("idx_metrics_name", "metric_name"),
        Index("idx_metrics_name_value", "metric_name", "metric_value"),
    )
