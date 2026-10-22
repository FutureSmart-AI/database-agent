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

class AddNewBot(BaseModel):
    user_id: Optional[str] = None
    chatbot_name: Optional[str] = None
    system_prompt: Optional[str] = None
    greet_message: Optional[str] = None
    provider: Optional[str] = "openai"
    model: Optional[str] = "gpt-4.1"
    temperature: Optional[float] = Field(0.0)
    VALID_MODELS: ClassVar[dict[str, set[str]]] = {
        "openai": {"gpt-4.1", "gpt-4.1-mini"},
        "anthropic": {"claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022", "claude-3-opus-20240229","claude-3-7-sonnet-20250219"},
        "google":{"gemini-1.5-flash","gemini-1.5-flash-8b","gemini-2.0-flash","gemini-2.0-flash-lite"},
        
    }
    @model_validator(mode='before')
    def set_default_model(cls, values):
        provider = values.get('provider', 'openai').lower()  # Normalize to lowercase
        model = values.get('model')
        if model is None:
            if provider == "openai":
                values['model'] = "gpt-4.1-mini"
            elif provider == "anthropic":
                values['model'] = "claude-3-5-haiku-20241022"
            elif provider == "google":
                values['model'] = "gemini-1.5-flash"
            else:
                raise ValueError(f"Unsupported LLM provider: {provider}")
        model = values['model']
        if model not in cls.VALID_MODELS.get(provider, []):
            raise ValueError(f"Invalid model '{model}' for provider '{provider}'. Choose from {', '.join(cls.VALID_MODELS.get(provider, []))}.")
        return values

    @field_validator('model')
    def validate_model(cls, value, info):
        provider = info.data.get('provider', 'openai').lower()  # Normalize to lowercase
        if value not in cls.VALID_MODELS.get(provider, []):
            raise ValueError(f"Invalid model name '{value}' for provider '{provider}'. Choose from {', '.join(cls.VALID_MODELS.get(provider, []))}.")
        return value
   
class DeleteChatbot(BaseModel):
    user_id: Optional[str] = None
    chatbot_id: str
class UpdateParams(BaseModel):
    user_id: Optional[str] = None 
    chatbot_id: str
    chatbot_name: Optional[str] = None
    system_prompt: Optional[str] = None
    greet_message: Optional[str] = None
    provider: Optional[str] = "openai"
    model: Optional[str] = "gpt-4.1"
    temperature: Optional[float] = Field(0.0)
    VALID_MODELS: ClassVar[dict[str, set[str]]] = {
        "openai": {"gpt-4.1-mini", "gpt-4.1"},
        "anthropic": {"claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022", "claude-3-opus-20240229","claude-3-7-sonnet-20250219"},
        "google":{"gemini-1.5-flash","gemini-1.5-flash-8b","gemini-2.0-flash","gemini-2.0-flash-lite"}
        
    }

    @model_validator(mode='before')
    def set_default_model(cls, values):
        provider = values.get('provider', 'openai').lower()  # Normalize to lowercase
        model = values.get('model')
        if model is None:
            if provider == "openai":
                values['model'] = "gpt-4.1-mini"
            elif provider == "anthropic":
                values['model'] = "claude-3-5-haiku-20241022"
            elif provider == "google":
                values['model'] = "gemini-1.5-flash"
            else:
                raise ValueError(f"Unsupported LLM provider: {provider}")
        model = values['model']
        if model not in cls.VALID_MODELS.get(provider, []):
            raise ValueError(f"Invalid model '{model}' for provider '{provider}'. Choose from {', '.join(cls.VALID_MODELS.get(provider, []))}.")
        return values

    @field_validator('model')
    def validate_model(cls, value, info):
        provider = info.data.get('provider', 'openai').lower()  # Normalize to lowercase
        if value not in cls.VALID_MODELS.get(provider, []):
            raise ValueError(f"Invalid model name '{value}' for provider '{provider}'. Choose from {', '.join(cls.VALID_MODELS.get(provider, []))}.")
        return value



