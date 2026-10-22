"""
RESTful API endpoints for per-agent widget settings

`GET .../widget/settings` is the one NL2SQL route an anonymous caller can reach: it first tries
normal authentication and, only if there is none, falls back to the public gate, which requires the
agent to have opted that surface in and the caller's Origin to match its allowlist. Public callers
get a whitelisted subset of the fields. Writing and deleting always require authentication.
"""
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Security, UploadFile
from fastapi.security import APIKeyHeader
from starlette.requests import Request
import traceback

from chatbot_management.utils.api_validation import get_api_key_or_session
from chatbot_management.services.logger import logger
from agent.utils.authorization import require_agent_permission
from agent.utils.public_agent_gate import require_public_agent
from agent.utils.widget_image_utils import resolve_widget_image, validate_hex_color, validate_image
from api.v1.schemas.widgets import (
    WidgetSettingsResponse,
    WidgetSettingsSaveResponse,
    WidgetIconsResponse,
    WidgetAvatarsResponse,
)
from api.v1.utils.widgets_helper import (
    DEFAULT_AVATARS,
    DEFAULT_ICONS,
    DEFAULT_SETTINGS,
    delete_widget_settings,
    get_widget_settings,
    sanitize_for_public,
    upsert_widget_settings,
    verify_agent_exists,
)

router = APIRouter(prefix="/v1")

_widget_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def _try_authenticate(request: Request, api_key: Optional[str]) -> Optional[dict]:
    """Authenticate if possible, else None — never raises, so the caller can fall back to public."""
    try:
        return await get_api_key_or_session(request, api_key)
    except HTTPException:
        return None


@router.post("/agents/{agent_id}/widget/settings", response_model=WidgetSettingsSaveResponse)
async def save_widget_settings(
    agent_id: str = Path(..., description="Agent ID"),
    heading: Optional[str] = Form(None),
    sub_heading: Optional[str] = Form(None),
    greet_message: Optional[str] = Form(None),
    color: Optional[str] = Form(None),
    show_sources: Optional[bool] = Form(None),
    widget_icon: Optional[UploadFile] = File(None),
    widget_avatar: Optional[UploadFile] = File(None),
    widget_icon_url: Optional[str] = Form(None),
    widget_avatar_url: Optional[str] = Form(None),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("write")),
):
    """
    Create or update the agent's widget settings

    Multipart. Every field is optional and only what is sent is written, so saving one field
    leaves the rest untouched. An uploaded file takes precedence over the matching `_url`.
    """
    try:
        if color is not None:
            validate_hex_color(color)
        validate_image(widget_icon)
        validate_image(widget_avatar)

        await verify_agent_exists(agent_id)

        icon = await resolve_widget_image(widget_icon, widget_icon_url, agent_id, is_icon=True)
        avatar = await resolve_widget_image(widget_avatar, widget_avatar_url, agent_id, is_icon=False)

        result = await upsert_widget_settings(
            agent_id=agent_id,
            acting_user=auth.get("user_id"),
            heading=heading,
            sub_heading=sub_heading,
            greet_message=greet_message,
            color=color,
            show_sources=show_sources,
            widget_icon=icon,
            widget_avatar=avatar,
        )

        return {
            "message": (
                "Added widget settings successfully"
                if result["created"]
                else "Updated widget settings successfully"
            ),
            "widget_settings": result["settings"],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving widget settings: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/agents/{agent_id}/widget/settings", response_model=WidgetSettingsResponse)
async def retrieve_widget_settings(
    agent_id: str = Path(..., description="Agent ID"),
    request: Request = None,
    api_key: Optional[str] = Security(_widget_api_key_header),
):
    """
    Get the agent's widget settings

    Authenticated callers get the full record. Anonymous callers are allowed only when the agent
    has opted this surface in (`is_public`, or `fullscreen_is_public` with `?from_full_screen=true`)
    and their Origin matches the matching allowlist; they receive display fields only.

    An agent that has never been configured returns the documented defaults rather than 404.
    """
    auth = await _try_authenticate(request, api_key)
    is_public_caller = auth is None

    if is_public_caller:
        # Raises 401/403 unless this surface is open to this caller.
        await require_public_agent(request, agent_id)
    else:
        await verify_agent_exists(agent_id)

    try:
        settings = await get_widget_settings(agent_id)
        if not settings:
            settings = dict(DEFAULT_SETTINGS)

        if is_public_caller:
            settings = sanitize_for_public(settings)

        return {"widget_settings": settings}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting widget settings for agent {agent_id}: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/agents/{agent_id}/widget/settings")
async def remove_widget_settings(
    agent_id: str = Path(..., description="Agent ID"),
    request: Request = None,
    auth: dict = Depends(get_api_key_or_session),
    user: dict = Depends(require_agent_permission("delete")),
):
    """
    Delete the agent's widget settings

    Soft delete: the row is kept with `deleted_at`/`deleted_by` so the change stays auditable, and
    the agent falls back to the default appearance.
    """
    try:
        await verify_agent_exists(agent_id)

        deleted = await delete_widget_settings(agent_id, deleted_by=auth.get("user_id"))
        if not deleted:
            raise HTTPException(status_code=404, detail="No widget settings to delete for this agent")

        return {"message": "Successfully deleted widget settings"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting widget settings: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/widgets/icons/defaults", response_model=WidgetIconsResponse)
async def list_default_icons(auth: dict = Depends(get_api_key_or_session)):
    """List the built-in widget icons the settings screen offers."""
    return {"widget_icons": [{"url": url} for url in DEFAULT_ICONS]}


@router.get("/widgets/avatars/defaults", response_model=WidgetAvatarsResponse)
async def list_default_avatars(auth: dict = Depends(get_api_key_or_session)):
    """List the built-in widget avatars the settings screen offers."""
    return {"widget_avatars": [{"url": url} for url in DEFAULT_AVATARS]}
