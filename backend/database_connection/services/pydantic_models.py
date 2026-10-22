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

class UpdateConnection(BaseModel):
    user_id: Optional[str] = None 
    chatbot_id: str
    db_host: str
    db_name: str
    db_user: str
    db_password: str
    db_port: Optional[int] = Field(default=3306)
    db_engine: str = Field(default="mysql")

class TestDbConnection(BaseModel):
    user_id: Optional[str] = None 
    db_host: str
    db_name: str
    db_user: str
    db_password: str
    db_port: Optional[int] = Field(default=3306)
    db_engine: str = Field(default="mysql")
