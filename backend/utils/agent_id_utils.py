"""
Utility functions for handling agent_id and chatbot_id compatibility.

This module provides helper functions to ensure backward compatibility
between the old chatbot_id and new agent_id naming conventions.
"""

from typing import Optional


def resolve_agent_chatbot_id(agent_id: Optional[str] = None, chatbot_id: Optional[str] = None) -> str:
    """
    Resolve agent_id and chatbot_id to a single ID value.
    
    This function ensures backward compatibility by accepting both agent_id and chatbot_id.
    Priority is given to agent_id if both are provided.
    
    Args:
        agent_id: The new agent_id parameter (preferred)
        chatbot_id: The legacy chatbot_id parameter (for backward compatibility)
        
    Returns:
        str: The resolved ID value
        
    Raises:
        ValueError: If neither agent_id nor chatbot_id is provided
        
    Examples:
        >>> resolve_agent_chatbot_id(agent_id="agent123")
        'agent123'
        
        >>> resolve_agent_chatbot_id(chatbot_id="bot456")
        'bot456'
        
        >>> resolve_agent_chatbot_id(agent_id="agent123", chatbot_id="bot456")
        'agent123'  # agent_id takes priority
    """
    if agent_id:
        return agent_id
    elif chatbot_id:
        return chatbot_id
    else:
        raise ValueError("Either agent_id or chatbot_id must be provided")


def get_both_ids(id_value: str) -> dict:
    """
    Get both agent_id and chatbot_id from a single ID value.
    
    This is useful when you need to set both fields in database operations
    to maintain consistency between old and new field names.
    
    Args:
        id_value: The ID value (can be from either agent_id or chatbot_id)
        
    Returns:
        dict: Dictionary with both 'agent_id' and 'chatbot_id' keys set to the same value
        
    Example:
        >>> get_both_ids("agent123")
        {'agent_id': 'agent123', 'chatbot_id': 'agent123'}
    """
    return {
        'agent_id': id_value,
        'chatbot_id': id_value
    }


def sync_agent_chatbot_id(record: object, id_value: Optional[str] = None) -> None:
    """
    Synchronize agent_id and chatbot_id fields on a database record.
    
    This ensures both fields have the same value for consistency.
    If id_value is provided, both fields are set to that value.
    Otherwise, agent_id is synced from chatbot_id or vice versa.
    
    Args:
        record: Database record object with agent_id and/or chatbot_id attributes
        id_value: Optional ID value to set both fields to
        
    Example:
        >>> record = ChatbotDetails(chatbot_id="bot123")
        >>> sync_agent_chatbot_id(record)
        >>> record.agent_id
        'bot123'
    """
    if id_value:
        # Set both to the provided value
        if hasattr(record, 'agent_id'):
            record.agent_id = id_value
        if hasattr(record, 'chatbot_id'):
            record.chatbot_id = id_value
    else:
        # Sync from whichever is set
        if hasattr(record, 'agent_id') and hasattr(record, 'chatbot_id'):
            if record.agent_id and not record.chatbot_id:
                record.chatbot_id = record.agent_id
            elif record.chatbot_id and not record.agent_id:
                record.agent_id = record.chatbot_id

