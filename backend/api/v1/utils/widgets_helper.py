"""Business logic for per-agent widget settings.

The settings row is the widget's appearance. Reading it is the one NL2SQL surface an anonymous
caller can reach, so `PUBLIC_FIELDS` is a default-deny whitelist: a public caller sees what is
needed to render the widget and nothing else — never `user_id`, timestamps, or audit columns.
"""
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import HTTPException

from chatbot_management.services.logger import logger

# Exactly what an anonymous caller may see.
PUBLIC_FIELDS = (
    "heading",
    "sub_heading",
    "greet_message",
    "color",
    "show_sources",
    "widget_icon",
    "widget_avatar",
)

DEFAULT_SETTINGS = {
    "heading": "Welcome",
    "sub_heading": "Got a Question? Just Ask!",
    "greet_message": "Hello! What's up?",
    "color": "#3a5fe3",
    "show_sources": False,
    "widget_icon": "https://futuresmart-rag-bot.s3.us-east-1.amazonaws.com/default_bot/widget_icon.svg",
    "widget_avatar": "https://futuresmart-rag-bot.s3.us-east-1.amazonaws.com/default_bot/widget_avatar.svg",
}

DEFAULT_ICONS = [
    "https://futuresmart-rag-bot.s3.us-east-1.amazonaws.com/default_bot/widget_icon.svg",
    "https://futuresmart-rag-bot.s3.us-east-1.amazonaws.com/default_icon_1/widget_icon.svg",
    "https://futuresmart-rag-bot.s3.us-east-1.amazonaws.com/default_icon_2/widget_icon.svg",
    "https://futuresmart-rag-bot.s3.us-east-1.amazonaws.com/default_icon_3/widget_icon.svg",
    "https://futuresmart-rag-bot.s3.us-east-1.amazonaws.com/default_icon_4/widget_icon.svg",
    "https://futuresmart-rag-bot.s3.us-east-1.amazonaws.com/default_icon_5/widget_icon.svg",
    "https://futuresmart-rag-bot.s3.us-east-1.amazonaws.com/default_icon_6/widget_icon.svg",
]

DEFAULT_AVATARS = [
    "https://futuresmart-rag-bot.s3.us-east-1.amazonaws.com/default_bot/widget_avatar.svg",
    "https://futuresmart-rag-bot.s3.us-east-1.amazonaws.com/default_avatar_1/widget_avatar.svg",
    "https://futuresmart-rag-bot.s3.us-east-1.amazonaws.com/default_avatar_2/widget_avatar.svg",
    "https://futuresmart-rag-bot.s3.us-east-1.amazonaws.com/default_avatar_3/widget_avatar.svg",
    "https://futuresmart-rag-bot.s3.us-east-1.amazonaws.com/default_avatar_4/widget_avatar.svg",
]


def sanitize_for_public(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Default-deny: only the whitelisted display fields survive."""
    return {field: settings.get(field) for field in PUBLIC_FIELDS}


async def verify_agent_exists(agent_id: str) -> None:
    from models.sql_models import ChatbotDetails
    from chatbot_management.services.sqlmodel_session import get_async_session
    from sqlmodel import select, or_

    async for session in get_async_session():
        result = await session.execute(
            select(ChatbotDetails).where(
                or_(ChatbotDetails.agent_id == agent_id, ChatbotDetails.chatbot_id == agent_id)
            )
        )
        if not result.scalars().first():
            raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")


def _row_to_dict(row) -> Dict[str, Any]:
    return {
        "heading": row.heading,
        "sub_heading": row.sub_heading,
        "greet_message": row.greet_message,
        "color": row.color,
        "show_sources": row.show_sources,
        "widget_icon": row.widget_icon,
        "widget_avatar": row.widget_avatar,
        "user_id": row.user_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def get_widget_settings(agent_id: str) -> Optional[Dict[str, Any]]:
    """The agent's saved settings, or None when it has never been configured."""
    from models.sql_models import WidgetsSettings
    from agent.services.sqlmodel_session import get_async_session
    from sqlmodel import select, and_, or_

    async for session in get_async_session():
        result = await session.execute(
            select(WidgetsSettings).where(
                and_(
                    WidgetsSettings.deleted == False,
                    or_(
                        WidgetsSettings.agent_id == agent_id,
                        WidgetsSettings.chatbot_id == agent_id,
                    ),
                )
            ).order_by(WidgetsSettings.id.desc())
        )
        row = result.scalars().first()
        return _row_to_dict(row) if row else None


async def upsert_widget_settings(
    agent_id: str,
    acting_user: Optional[str],
    heading: Optional[str] = None,
    sub_heading: Optional[str] = None,
    greet_message: Optional[str] = None,
    color: Optional[str] = None,
    show_sources: Optional[bool] = None,
    widget_icon: Optional[str] = None,
    widget_avatar: Optional[str] = None,
) -> Dict[str, Any]:
    """Create the row on first save, patch it after.

    Only fields the caller actually supplied are written, so saving one field does not silently
    reset the others. `user_id` is the owner and is set once at creation; later edits record the
    actor in `updated_by` instead.
    """
    from models.sql_models import WidgetsSettings
    from agent.services.sqlmodel_session import get_async_session
    from sqlmodel import select, and_, or_

    supplied = {
        "heading": heading,
        "sub_heading": sub_heading,
        "greet_message": greet_message,
        "color": color,
        "show_sources": show_sources,
        "widget_icon": widget_icon,
        "widget_avatar": widget_avatar,
    }
    supplied = {k: v for k, v in supplied.items() if v is not None}

    async for session in get_async_session():
        result = await session.execute(
            select(WidgetsSettings).where(
                and_(
                    WidgetsSettings.deleted == False,
                    or_(
                        WidgetsSettings.agent_id == agent_id,
                        WidgetsSettings.chatbot_id == agent_id,
                    ),
                )
            ).order_by(WidgetsSettings.id.desc())
        )
        row = result.scalars().first()

        if row:
            for key, value in supplied.items():
                setattr(row, key, value)
            row.updated_at = datetime.utcnow()
            row.updated_by = acting_user
            await session.commit()
            await session.refresh(row)
            logger.info(
                f"Updated widget settings for agent {agent_id} "
                f"({', '.join(supplied.keys()) or 'no fields'}) by {acting_user}"
            )
            return {"created": False, "settings": _row_to_dict(row)}

        # First save: unsupplied fields take the documented defaults rather than NULL, so a
        # freshly created row renders the same widget the GET fallback describes.
        values = {**DEFAULT_SETTINGS, **supplied}
        row = WidgetsSettings(
            agent_id=agent_id,
            chatbot_id=agent_id,
            user_id=acting_user,
            created_at=datetime.utcnow(),
            deleted=False,
            **values,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        logger.info(f"Created widget settings for agent {agent_id} by {acting_user}")
        return {"created": True, "settings": _row_to_dict(row)}


async def delete_widget_settings(agent_id: str, deleted_by: Optional[str]) -> bool:
    """Soft delete. False when there was nothing to delete."""
    from models.sql_models import WidgetsSettings
    from agent.services.sqlmodel_session import get_async_session
    from sqlmodel import select, and_, or_

    async for session in get_async_session():
        result = await session.execute(
            select(WidgetsSettings).where(
                and_(
                    WidgetsSettings.deleted == False,
                    or_(
                        WidgetsSettings.agent_id == agent_id,
                        WidgetsSettings.chatbot_id == agent_id,
                    ),
                )
            )
        )
        rows = result.scalars().all()
        if not rows:
            return False

        now = datetime.utcnow()
        for row in rows:
            row.deleted = True
            row.deleted_at = now
            row.deleted_by = deleted_by
        await session.commit()
        logger.info(f"Soft-deleted widget settings for agent {agent_id} by {deleted_by}")
        return True
