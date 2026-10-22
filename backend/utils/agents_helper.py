from typing import Optional, List, Dict, Any
from models.sql_models import ChatbotDetails
from logger import logger
from chatbot_management.utils.common_utils import generate_bot_id
from chatbot_management.db_utils.bot_crud_db_utils import (
    insert_chatbot_details,
    get_agent_by_id as get_agent_from_db,
    get_agents_by_owner_id,
    get_all_agents,
    update_agent_details
)

# Helper function to get agent by ID
async def get_agent_by_id(agent_id: str) -> Optional[ChatbotDetails]:
    """Retrieve a single agent by ID - wrapper for bot_crud_db_utils function"""
    return await get_agent_from_db(agent_id)


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


# Helper function to get all agents or filter by owner email
async def get_agents_list(owner_id: Optional[str] = None) -> Dict[str, List[Dict]]:
    """Get all agents or filter by owner email, formatted for list response"""
    try:
        if owner_id:
            owned_chatbots = await get_agents_by_owner_id(owner_id)
        else:
            owned_chatbots = await get_all_agents()
        
        invited_chatbots = []  # Logic for invited agents can be added later if needed
        
        # Format owned agents
        formatted_owned = [
            {
                "owner_id": b.owner_id if b.owner_id else "unknown",
                "agent_id": b.chatbot_id,
                "agent_name": b.chatbot_name,
                "created_at": b.created_at.isoformat() if b.created_at else None
            }
            for b in (owned_chatbots or [])
        ]

        # Format invited agents
        formatted_invited = [
            {
                "owner_id": b.owner_id if b.owner_id else "unknown",
                "agent_id": b.chatbot_id,
                "agent_name": b.chatbot_name,
                "created_at": b.created_at.isoformat() if b.created_at else None
            }
            for b in (invited_chatbots or [])
        ]
            
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
            "greet_message": agent_data.greet_message
        }

        # Insert into database
        db_result = await insert_chatbot_details(chatbot_details)
        return agent_id if db_result else None
    except Exception as e:
        logger.error(f"Error creating agent in helper: {e}")
        return None


# Helper function to update agent
async def update_agent_in_db(agent_id: str, update_data: dict) -> Optional[ChatbotDetails]:
    """Update agent in database - wrapper for bot_crud_db_utils function"""
    return await update_agent_details(agent_id, update_data)
