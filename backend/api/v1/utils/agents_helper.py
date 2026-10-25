from typing import Optional, List, Dict, Any
from datetime import datetime
from models.sql_models import ChatbotDetails
from chatbot_management.services.logger import logger
from chatbot_management.utils.common_utils import generate_bot_id
from chatbot_management.db_utils.bot_crud_db_utils import insert_chatbot_details, delete_chatbot_details
from chatbot_management.services.sqlmodel_session import get_async_session
from sqlmodel import select, or_


def format_agent_response(agent: ChatbotDetails, extra: dict = None) -> dict:
    """Format agent object into standard API response data dict"""
    owner_id = agent.owner_id if agent.owner_id else "unknown"
    data = {
        "agent_id": agent.chatbot_id,
        "owner_id": owner_id,
        "agent_name": agent.chatbot_name,
        "system_prompt": agent.system_prompt,
        "provider": agent.llm_provider,
        "model": agent.model,
        "temperature": agent.temperature,
        "greet_message": agent.greet_message,
        "show_sql_query": bool(getattr(agent, "show_sql_query", False)),
        "show_db_result": bool(getattr(agent, "show_db_result", False)),
        "updated_at": agent.updated_at.isoformat() if getattr(agent, "updated_at", None) else None,
        "updated_by": getattr(agent, "updated_by", None),
    }
    if extra:
        data.update(extra)
    return data


async def delete_agent_from_db(agent_id: str, deleted_by: str = None) -> bool:
    """Soft-delete agent from database.

    deleted_by: acting dashboard user (email); None for internal / master-key callers.
    """
    from chatbot_management.db_utils.bot_crud_db_utils import delete_chatbot_details
    return await delete_chatbot_details(agent_id, deleted_by=deleted_by)


# Helper function to get agent by ID
async def get_agent_by_id(agent_id: str) -> Optional[ChatbotDetails]:
    """Retrieve a single agent by ID"""
    try:
        async for session in get_async_session():
            statement = select(ChatbotDetails).where(
                ChatbotDetails.agent_id == agent_id,
                ChatbotDetails.deleted == False
            )
            results = await session.execute(statement)
            agent = results.scalars().one_or_none()
            return agent
    except Exception as e:
        logger.error(f"Error getting agent by ID: {e}")
        return None


# Helper function to get owner_id (email) from agent
async def get_owner_id_from_agent(agent: ChatbotDetails) -> str:
    """Get owner_id (email) from agent - uses owner_id column directly"""
    return agent.owner_id if agent.owner_id else "unknown"


# Helper function to format agent data for response
def format_agent_data(agent: ChatbotDetails) -> Dict[str, Any]:
    """Standardize agent data formatting for API responses"""
    return {
        "agent_id": agent.chatbot_id,
        "owner_id": agent.owner_id if agent.owner_id else "unknown",
        "agent_name": agent.chatbot_name,
        "system_prompt": agent.system_prompt,
        "provider": agent.llm_provider,
        "model": agent.model,
        "temperature": agent.temperature,
        "greet_message": agent.greet_message,
        "created_at": agent.created_at.isoformat() if agent.created_at else None
    }


async def get_invited_agents(
    user_email: Optional[str],
    owned_chatbots: List[ChatbotDetails],
) -> tuple:
    """The agents shared with `user_email`, and the role held on each: `(agents, {id: role})`.

    Returns `([], {})` for an unidentified caller — a master-key listing has no identity to have
    been invited as, and returning every invitation on the platform would be wrong.

    Agents the caller already owns are excluded, so an owner who was also invited (possible on an
    agent that changed hands) appears once, under `owned_agents`, at the higher standing.
    """
    from agent.db_utils.invitation_db_utils import get_invited_agent_roles

    if not user_email:
        return [], {}

    roles = await get_invited_agent_roles(user_email)
    if not roles:
        return [], {}

    owned_ids = set()
    for agent in owned_chatbots or []:
        owned_ids.update(i for i in (agent.agent_id, agent.chatbot_id) if i)

    candidate_ids = [i for i in roles if i not in owned_ids]
    if not candidate_ids:
        return [], roles

    async for session in get_async_session():
        result = await session.execute(
            select(ChatbotDetails).where(
                or_(
                    ChatbotDetails.agent_id.in_(candidate_ids),
                    ChatbotDetails.chatbot_id.in_(candidate_ids),
                ),
                ChatbotDetails.deleted == False
            )
        )
        # An invitation can outlive its agent (invitations are not cascaded on soft delete), so
        # the filter above may return fewer agents than there are invitations. That is correct:
        # a deleted agent should not appear in anyone's shared list.
        agents = list(result.scalars().all())

    # Deduplicate: an agent matching on both agent_id and chatbot_id comes back once per match.
    unique = {}
    for agent in agents:
        unique.setdefault(agent.chatbot_id, agent)
    return list(unique.values()), roles


# Helper function to get all agents or filter by owner email
async def get_demo_agents(exclude_ids: set) -> List[ChatbotDetails]:
    """Agents flagged `is_demo`, minus any the caller already reaches another way.

    A demo agent is shown to every signed-in user so a new account can ask a real
    question before connecting a database of its own. It arrives at viewer
    standing, which the authorization layer already limits to chat, messages and
    feedback - so a viewer cannot read the agent's database host or credentials
    and cannot change or delete it.

    `exclude_ids` carries the agents already listed as owned or invited: the
    account that OWNS the demo agent must keep seeing it as an owner, and an
    agent appearing twice in one list is a bug.

    Returns [] on any failure. A demo agent is a nicety; an agent list that
    fails because of one is not.
    """
    try:
        async for session in get_async_session():
            result = await session.execute(
                select(ChatbotDetails).where(
                    ChatbotDetails.is_demo == True,  # noqa: E712 - SQLAlchemy needs ==
                    ChatbotDetails.deleted == False,  # noqa: E712
                )
            )
            return [
                a for a in result.scalars().all()
                if not ({a.agent_id, a.chatbot_id} & exclude_ids)
            ]
    except Exception as e:  # noqa: BLE001
        logger.error(f"Error loading demo agents: {e}")
    return []


async def get_agents_list(owner_id: Optional[str] = None) -> Dict[str, List[Dict]]:
    """Get all agents or filter by owner email, formatted for list response"""
    try:
        owned_chatbots = []
        async for session in get_async_session():
            if owner_id:
                agent_result = await session.execute(
                    select(ChatbotDetails).where(
                        ChatbotDetails.owner_id == owner_id,
                        ChatbotDetails.deleted == False
                    )
                )
                owned_chatbots = list(agent_result.scalars().all())
            else:
                statement = select(ChatbotDetails).where(ChatbotDetails.deleted == False)
                results = await session.execute(statement)
                owned_chatbots = list(results.scalars().all())

        # Agents shared with this caller. Only a named caller has any: a master-key listing has no
        # identity to be invited as, so it keeps the previous behaviour of returning owned only.
        invited_chatbots, invited_roles = await get_invited_agents(owner_id, owned_chatbots)

        # Format via the same helper GET /agents/{id} uses, so a listed agent and a fetched
        # one carry identical fields. The list previously returned only 4 of them, forcing
        # callers into an extra request per agent to read model/prompt/visibility settings.
        # created_at is passed as `extra` because format_agent_response leaves it to callers.
        formatted_owned = [
            format_agent_response(b, {
                "created_at": b.created_at.isoformat() if b.created_at else None,
                # `role` is reported on both lists so a caller never has to infer standing from
                # which array an agent arrived in. Nothing authorizes on it.
                "role": "owner",
            })
            for b in (owned_chatbots or [])
        ]

        formatted_invited = [
            format_agent_response(b, {
                "created_at": b.created_at.isoformat() if b.created_at else None,
                "role": invited_roles.get(b.agent_id) or invited_roles.get(b.chatbot_id) or "viewer",
            })
            for b in (invited_chatbots or [])
        ]

        # Demo agents belong in "My Agents" - the list a new user actually looks
        # at - so they are returned in owned_agents, first.
        #
        # The client has to meet this halfway. That list is filtered on owner_id
        # matching the signed-in user, and a demo agent is owned by one account
        # and shown to all of them, so today the API returns 22 agents and the
        # screen draws 21. The row carries is_demo true and role "viewer" for
        # exactly this: admit it despite the owner_id, label it as an example,
        # and hide rename, settings and delete.
        #
        # The API deliberately does NOT report the caller as the owner to force
        # the row through that filter. It would render today and leave every
        # later reader of owner_id believing something untrue.
        #
        # Skipped for an unidentified caller (master-key listing), matching how
        # invitations are treated above - there is no "every user" to be one of.
        if owner_id:
            already = set()
            for b in list(owned_chatbots or []) + list(invited_chatbots or []):
                already.update(i for i in (b.agent_id, b.chatbot_id) if i)
            demo_rows = [
                format_agent_response(b, {
                    "created_at": b.created_at.isoformat() if b.created_at else None,
                    "role": "viewer",
                    "is_demo": True,
                })
                for b in await get_demo_agents(already)
            ]
            # Prepended into the OWNED list: the list is paginated at 20 and an
            # owner here holds as many as 506 agents, so appending put it on page
            # 26. owner_id on these rows is the real owner, not the caller - the
            # client is expected to admit a row whose owner_id differs from the
            # signed-in user when is_demo is true, and to hide rename, settings
            # and delete on it.
            formatted_owned[:0] = demo_rows

        return {
            "owned_agents": formatted_owned,
            "invited_agents": formatted_invited
        }
    except Exception as e:
        logger.error(f"Error listing agents in helper: {e}")
        return {"owned_agents": [], "invited_agents": []}


# Helper function to paginate agents
def paginate_agents(agents_data: Dict[str, List[Dict]], page: int, limit: int) -> Dict[str, Any]:
    """Apply pagination to the agents list"""
    formatted_owned = agents_data["owned_agents"]
    formatted_invited = agents_data["invited_agents"]

    # Combine all agents for pagination
    all_agents = formatted_owned + formatted_invited
    total = len(all_agents)
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit

    # Apply pagination logic
    if start_idx < len(formatted_owned):
        paginated_owned = formatted_owned[start_idx:min(end_idx, len(formatted_owned))]
        remaining = limit - len(paginated_owned)
        if remaining > 0 and formatted_invited:
            paginated_invited = formatted_invited[:remaining]
        else:
            paginated_invited = []
    else:
        # Pagination starts in invited
        paginated_owned = []
        invited_start = start_idx - len(formatted_owned)
        paginated_invited = formatted_invited[invited_start:invited_start + limit]

    return {
        "owned_agents": paginated_owned,
        "invited_agents": paginated_invited,
        "pagination": {
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit if total > 0 else 1
        }
    }


# Helper function to create a new agent
async def create_new_agent(owner_email: str, agent_data: Any) -> Optional[str]:
    """Create a new NL2SQL agent and return the agent_id"""
    try:
        # Generate unique agent ID
        agent_id = generate_bot_id()

        # Prepare agent details
        chatbot_details = {
            "owner_id": owner_email,
            "chatbot_id": agent_id,
            "agent_id": agent_id,
            "chatbot_name": agent_data.agent_name,
            "system_prompt": agent_data.system_prompt,
            "llm_provider": agent_data.provider,
            "model": agent_data.model,
            "temperature": agent_data.temperature,
            "greet_message": agent_data.greet_message,
            "show_sql_query": bool(agent_data.show_sql_query),
            "show_db_result": bool(agent_data.show_db_result),
        }

        # Insert into database
        db_result = await insert_chatbot_details(chatbot_details)
        if not db_result:
            return None

        # A template pre-fills the business knowledge for a kind of business -
        # what counts as a customer, how revenue is counted - which the schema
        # cannot say on its own. Applied after the row exists, and deliberately
        # never fatal: a template that fails leaves a normal working agent
        # rather than losing the agent the caller asked for.
        template_id = getattr(agent_data, "template_id", None)
        if template_id:
            try:
                from api.v1.utils.agent_templates import apply_template
                result = await apply_template(agent_id, template_id, user_id=owner_email)
                if not result.get("applied"):
                    logger.warning("Agent %s created, template %s not applied: %s",
                                   agent_id, template_id, result.get("reason"))
            except Exception as tmpl_err:  # noqa: BLE001
                logger.error("Agent %s created, template %s raised: %s",
                             agent_id, template_id, tmpl_err)

        return agent_id
    except Exception as e:
        logger.error(f"Error creating agent in helper: {e}")
        return None


# Helper function to update agent
async def update_agent_in_db(agent_id: str, update_data: dict, updated_by: Optional[str] = None) -> Optional[ChatbotDetails]:
    """Update agent in database.

    updated_by: acting dashboard user (email); stamped only when truthy so internal /
    API-key (master) calls leave it NULL. updated_at is set on every edit.
    """
    try:
        async for session in get_async_session():
            statement = select(ChatbotDetails).where(
                ChatbotDetails.agent_id == agent_id,
                ChatbotDetails.deleted == False
            )
            results = await session.execute(statement)
            agent = results.scalars().one_or_none()

            if not agent:
                return None

            # Update only provided fields
            for key, value in update_data.items():
                if value is not None:
                    # Map agent_name to chatbot_name
                    if key == "agent_name":
                        setattr(agent, "chatbot_name", value)
                    elif key == "provider":
                        setattr(agent, "llm_provider", value)
                    else:
                        setattr(agent, key, value)

            agent.updated_at = datetime.utcnow()
            if updated_by:
                agent.updated_by = updated_by  # stamp the acting dashboard user

            await session.commit()
            await session.refresh(agent)
            return agent
    except Exception as e:
        logger.error(f"Error updating agent: {e}")
        return None
