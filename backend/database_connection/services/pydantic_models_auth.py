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

class GetDbConnectionRequest(BaseModel):
    user_id: Optional[str] = None
    chatbot_id: str
    
    @model_validator(mode='before')
    def validate_user_id(cls, values):
        # Validate user_id if session_data dependency is disabled
        if not ENABLE_GOOGLE_AUTH and not values.get("user_id"):
            raise ValueError("user_id is required when session_data is not enabled.")
        return values