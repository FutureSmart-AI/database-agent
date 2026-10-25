from fastapi import Form, UploadFile, File
from pydantic import BaseModel, field_validator, model_validator
from typing import Optional, List, ClassVar
from datetime import datetime
from enum import Enum
from dotenv import load_dotenv
import os
import re
load_dotenv(override=False)

ENABLE_GOOGLE_AUTH = os.getenv("ENABLE_GOOGLE_AUTH")
# class ChatbotCreateRequest(BaseModel):
#     user_id: str
#     chatbot_name: str
#     prompt: str = None
#     llm_provider: str = "openai"  
#     model: str = "gpt-4o-mini"
#     temperature: float = 0.7
#     collect_user_info: bool = True
    
#     VALID_MODELS: ClassVar[set[str]] = {"gpt-3.5", "gpt-4", "gpt-4-turbo", "gpt-4o-mini", "gpt-4o","claude-3-5-sonnet-20241022","claude-3-5-haiku-20241022","claude-3-opus-20240229"}  

#     @field_validator('model')
#     def validate_model(cls, value):
#         if value not in cls.VALID_MODELS:
#             raise ValueError(f"Invalid model name '{value}'. Choose from {', '.join(cls.VALID_MODELS)}.")
#         return value

class SessionTitleRequestAuth(BaseModel):
    user_id: Optional[str] = None
    chatbot_id: str
    session_title: str
    session_id: str
    
    @model_validator(mode='before')
    def validate_user_id(cls, values):
        # Validate user_id if session_data dependency is disabledhget
        if not ENABLE_GOOGLE_AUTH and not values.get("user_id"):
            raise ValueError("user_id is required when session_data is not enabled.")
        return values

class GetSessionsRequest(BaseModel):
    user_id: Optional[str] = None
    chatbot_id: str
    show_guests_session: Optional[bool] = False
    email: Optional[str] = None
    
    @model_validator(mode='before')
    def validate_user_id(cls, values):
        # Validate user_id if session_data dependency is disabled
        if not ENABLE_GOOGLE_AUTH and not values.get("user_id") and not values.get("email"):
            raise ValueError("Either user_id or email is required when session_data is not enabled.")
        return values

class GetSessionParamsRequest(BaseModel):
    user_id: Optional[str] = None
    chatbot_id: str
    session_id: str
    
    @model_validator(mode='before')
    def validate_user_id(cls, values):
        # Validate user_id if session_data dependency is disabled
        if not ENABLE_GOOGLE_AUTH and not values.get("user_id"):
            raise ValueError("user_id is required when session_data is not enabled.")
        return values

class GetSessionDataRequest(BaseModel):
    user_id: Optional[str] = None
    chatbot_id: str
    session_id: str
    email: Optional[str] = None
    
    @model_validator(mode='before')
    def validate_user_id(cls, values):
        # Validate user_id if session_data dependency is disabled
        if not ENABLE_GOOGLE_AUTH and not values.get("user_id"):
            raise ValueError("user_id is required when session_data is not enabled.")
        return values

class DeleteSessionRequest(BaseModel):
    user_id: Optional[str] = None
    chatbot_id: str
    session_id: str
    
    @model_validator(mode='before')
    def validate_user_id(cls, values):
        # Validate user_id if session_data dependency is disabled
        if not ENABLE_GOOGLE_AUTH and not values.get("user_id"):
            raise ValueError("user_id is required when session_data is not enabled.")
        return values

class SessionData(BaseModel):
    session_id: str
    timestamp: str
    
class DeleteSessionRequest(BaseModel):
    user_id: Optional[str] = None
    chatbot_id: str
    session_id: str
    
    @model_validator(mode='before')
    def validate_user_id(cls, values):
        # Validate user_id if session_data dependency is disabled
        if not ENABLE_GOOGLE_AUTH and not values.get("user_id"):
            raise ValueError("user_id is required when session_data is not enabled.")
        return values