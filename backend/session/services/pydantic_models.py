# All the Pydantic Schema will be defined here.
from pydantic import BaseModel, Field, field_validator, ValidationError  ,model_validator
from typing import ClassVar, Optional, Union, Dict, Any
from enum import Enum
from typing import Annotated, Sequence, TypedDict, List,Tuple
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage
from fastapi import Form
import operator
from dotenv import load_dotenv
import os
load_dotenv()

DEFAULT_OPENAI_KEY = os.getenv("OPENAI_API_KEY")



class FeedbackRequest(BaseModel):
    session_id: str
    chat_id: str
    feedback: bool


class SessionTitleRequest(BaseModel):
    user_id: Optional[str] = None
    chatbot_id: str
    session_title: str
    session_id: str


class FeedbackNL2SQLRequest(BaseModel):
    user_id: Optional[str] = None
    chatbot_id: str
    session_id: str
    chat_id: str
    user_query: str
    generated_query: str
    label: str  # 'accepted' or 'rejected'
    corrected_query: Optional[str] = None
  


