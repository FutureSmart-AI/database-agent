"""
Pydantic schemas for widget settings endpoints
"""
from pydantic import BaseModel, Field
from typing import List, Optional


class WidgetSettings(BaseModel):
    """The widget's appearance.

    Owner/timestamp fields are absent for anonymous callers — see `PUBLIC_FIELDS` in
    `api/v1/utils/widgets_helper.py`.
    """
    heading: Optional[str] = None
    sub_heading: Optional[str] = None
    greet_message: Optional[str] = None
    color: Optional[str] = None
    show_sources: Optional[bool] = None
    widget_icon: Optional[str] = None
    widget_avatar: Optional[str] = None
    user_id: Optional[str] = Field(None, description="Owner; omitted for public callers")
    created_at: Optional[str] = Field(None, description="Omitted for public callers")
    updated_at: Optional[str] = Field(None, description="Omitted for public callers")


class WidgetSettingsResponse(BaseModel):
    """Response for reading widget settings"""
    widget_settings: WidgetSettings


class WidgetSettingsSaveResponse(BaseModel):
    """Response for creating or updating widget settings"""
    message: str
    widget_settings: WidgetSettings


class WidgetImage(BaseModel):
    url: str


class WidgetIconsResponse(BaseModel):
    widget_icons: List[WidgetImage]


class WidgetAvatarsResponse(BaseModel):
    widget_avatars: List[WidgetImage]
