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

class ChatbotCreateRequestAuth(BaseModel):
    user_id: Optional[str] = None
    chatbot_name: str
    prompt: Optional[str] = "You are an assistant for question-answering tasks.Use the following pieces of retrieved context and user information to answer the question.If you don't find the answer of the query,then just say I don't have that information at hand. Please provide more details or check your sources."
    llm_provider: str = "openai"  # Default provider
    model: Optional[str] = None  # Model will default based on provider if not provided
    temperature: float = 0.7
    collect_user_info: bool = True
    show_sources: bool = True
    follow_up: bool = False

    VALID_MODELS: ClassVar[dict[str, set[str]]] = {
        "openai": {"gpt-4.1-mini", "gpt-4.1"},
        "anthropic": {"claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022", "claude-3-opus-20240229"},
        "google":{"gemini-1.5-flash","gemini-1.5-flash-8b","gemini-2.0-flash-exp"},
        "groq":{"llama-3.3-70b-versatile","llama-3.1-8b-instant"}
    }

    @model_validator(mode='before')
    def set_default_model(cls, values):
        # Access `llm_provider` and `model` from the `values` dictionary-like object directly
        llm_provider = values.get('llm_provider', 'openai')  # Fallback to 'openai' if not provided
        model = values.get('model')

        # If the model is not provided, set it based on the provider
        if model is None:
            if llm_provider == "openai":
                values['model'] = "gpt-4.1-mini"  # Default model for openai
            elif llm_provider == "anthropic":
                values['model'] = "claude-3-5-haiku-20241022"  # Default model for anthropic
            elif llm_provider == "google":
                values['model'] = "gemini-1.5-flash" 
            # elif llm_provider == "mixtral":
            #     values['model'] = "ministral-8b-latest"
            elif llm_provider == "groq":
                values['model'] = "llama-3.3-70b-versatile"
            else:
                raise ValueError(f"Unsupported LLM provider: {llm_provider}")

        # Validate the model after setting a default
        model = values['model']
        if model not in cls.VALID_MODELS.get(llm_provider, []):
            raise ValueError(f"Invalid model '{model}' for provider '{llm_provider}'. Choose from {', '.join(cls.VALID_MODELS.get(llm_provider, []))}.")

        return values

    @field_validator('prompt')
    def check_and_correct_prompt(cls, value):
        # Match and replace words surrounded by single curly braces with double curly braces
        corrected_prompt = re.sub(r'(?<!{)\{(\w+)\}(?!})', r'{{\1}}', value)
        
        if corrected_prompt != value:
            print(f"Prompt corrected: {value} -> {corrected_prompt}")
        
        return corrected_prompt
    
    @field_validator('model')
    def validate_model(cls, value, info):
        llm_provider = info.data.get('llm_provider', 'openai')

        # Validate the model against valid models for the provider
        if value not in cls.VALID_MODELS.get(llm_provider, []):
            raise ValueError(f"Invalid model name '{value}' for provider '{llm_provider}'. Choose from {', '.join(cls.VALID_MODELS.get(llm_provider, []))}.")

        return value
    
    @model_validator(mode='before')
    def validate_user_id(cls, values):
        # Validate user_id if session_data dependency is disabled
        if not ENABLE_GOOGLE_AUTH and not values.get("user_id"):
            raise ValueError("user_id is required when session_data is not enabled.")
        return values

class GetChatbotParamsRequest(BaseModel):
    user_id: Optional[str] = None
    chatbot_id: str
    
    @model_validator(mode='before')
    def validate_user_id(cls, values):
        # Validate user_id if session_data dependency is disabled
        if not ENABLE_GOOGLE_AUTH and not values.get("user_id"):
            raise ValueError("user_id is required when session_data is not enabled.")
        return values

    
class GetChatbotsRequest(BaseModel):
    user_id: Optional[str] = None
    
    @model_validator(mode='before')
    def validate_user_id(cls, values):
        # Validate user_id if session_data dependency is disabled
        if not ENABLE_GOOGLE_AUTH and not values.get("user_id"):
            raise ValueError("user_id is required when session_data is not enabled.")
        return values

class DeleteChatbotRequest(BaseModel):
    user_id: Optional[str] = None
    chatbot_id: str
    
    @model_validator(mode='before')
    def validate_user_id(cls, values):
        # Validate user_id if session_data dependency is disabled
        if not ENABLE_GOOGLE_AUTH and not values.get("user_id"):
            raise ValueError("user_id is required when session_data is not enabled.")
        return values
    
class ScrapeUsing(str, Enum):
    option1 = "Newspaper"
    option2 = "FireCrawl"
    option3 = "LangChain"

class TranscribeUsing(str, Enum):
    option1 = "openai"
    option2 = "groq"


class ChatbotData(BaseModel):
    user_id: str
    chatbot_id: str
    text: Optional[str] = None
    weblink: Optional[str] = None
    use_llama_parse: Optional[bool] = False
    scrape_using: Optional[ScrapeUsing] = ScrapeUsing.option1
    transcript_provider: Optional[TranscribeUsing] = TranscribeUsing.option1
    contextualise_chunks: Optional[bool] = False
    chunk_size: Optional[int] = None


class AddChatbotKnowledge(BaseModel):
    user_id: Optional[str] = Form(...)        
    chatbot_id: str = Form(...)                  
    text: Optional[str] = Form(None)
    file: Optional[UploadFile] = File(None),                   
    use_llama_parse: Optional[bool] = Form(False)
    transcript_provider: TranscribeUsing = Form(default=TranscribeUsing.option1)
    weblink: Optional[str] = Form(None) 
    scrape_using: ScrapeUsing = Form(default=ScrapeUsing.option1)
    contextualise_chunks: Optional[bool] = Form(False)
    chunk_size: Optional[int] = Form(None)

    
    @model_validator(mode='before')
    def validate_user_id(cls, values):
        # Validate user_id if session_data dependency is disabled
        if not ENABLE_GOOGLE_AUTH and not values.get("user_id"):
            raise ValueError("user_id is required when session_data is not enabled.")
        return values
    
class GetChatbotKnowledgeParamsAuth(BaseModel):
    user_id: Optional[str] = None
    chatbot_id: str

    @model_validator(mode='before')
    def validate_user_id(cls, values):
        # Validate user_id if session_data dependency is disabled
        if not ENABLE_GOOGLE_AUTH and not values.get("user_id"):
            raise ValueError("user_id is required when session_data is not enabled.")
        return values
    
class KnowledgeItem(BaseModel):
    id: str
    knowledge_id: Optional[str] = None
    file_name: Optional[str] = None
    content: Optional[str] = None
    url: Optional[str] = None
    created_time: datetime

class GetChatbotKnowledgeResponse(BaseModel):
    knowledge: List[KnowledgeItem]
    message: Optional[str] = None

class ChatbotUpdateRequestAuth(BaseModel):
    user_id: Optional[str] = None  
    chatbot_id: str  
    chatbot_name: Optional[str] = None 
    llm_provider: Optional[str] = None   
    model: Optional[str] = None  
    prompt: Optional[str] = None  
    temperature: Optional[float] = None  
    collect_user_info: Optional[bool] = True 
    show_sources: Optional[bool] = False
    follow_up: bool = False 
    
    VALID_MODELS: ClassVar[dict[str, set[str]]] = {
        "openai": {"gpt-4o-mini", "gpt-4o"},
        "anthropic": {"claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022", "claude-3-opus-20240229"},
        "google":{"gemini-1.5-flash","gemini-1.5-flash-8b","gemini-2.0-flash-exp"},
        # "mixtral":{"mistral-large-latest","ministral-3b-latest","mistral-small-latest","ministral-8b-latest"},
        "groq":{"llama-3.3-70b-versatile","llama-3.1-8b-instant"}
    }
    
    @model_validator(mode='before')
    def validate_update_fields(cls, values):
        llm_provider = values.get('llm_provider')
        model = values.get('model')

        # If either llm_provider or model is provided, the other must also be provided
        if llm_provider and not model:
            raise ValueError("Model is required when llm_provider is provided.")
        if model and not llm_provider:
            raise ValueError("llm_provider is required when model is provided.")

        # If both llm_provider and model are provided, validate the model for the provider
        if llm_provider and model:
            if model not in cls.VALID_MODELS.get(llm_provider, []):
                raise ValueError(f"Invalid model '{model}' for provider '{llm_provider}'. Choose from {', '.join(cls.VALID_MODELS.get(llm_provider, []))}.")

        return values
    
    @field_validator('model')
    def validate_model(cls, value, info):
        llm_provider = info.data.get('llm_provider')

        # If llm_provider is provided and model is provided, validate the model
        if llm_provider and value not in cls.VALID_MODELS.get(llm_provider, []):
            raise ValueError(f"Invalid model name '{value}' for provider '{llm_provider}'. Choose from {', '.join(cls.VALID_MODELS.get(llm_provider, []))}.")

        return value
    
    @field_validator('prompt')
    def check_and_correct_prompt(cls, value):
        # Match and replace words surrounded by single curly braces with double curly braces
        corrected_prompt = re.sub(r'(?<!{)\{(\w+)\}(?!})', r'{{\1}}', value)
        
        if corrected_prompt != value:
            print(f"Prompt corrected: {value} -> {corrected_prompt}")
        
        return corrected_prompt 
    
    @model_validator(mode='before')
    def validate_user_id(cls, values):
        # Validate user_id if session_data dependency is disabled
        if not ENABLE_GOOGLE_AUTH and not values.get("user_id"):
            raise ValueError("user_id is required when session_data is not enabled.")
        return values

class SessionTitleRequestAuth(BaseModel):
    user_id: Optional[str] = None
    chatbot_id: str
    session_title: str
    session_id: str
    
    @model_validator(mode='before')
    def validate_user_id(cls, values):
        # Validate user_id if session_data dependency is disabled
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

class DeleteChatbotDataRequestAuth(BaseModel):
    user_id: Optional[str] = None
    chatbot_id: str
    knowledge_id: Optional[List[str]] = None 

class ChatRequestNoAuth(BaseModel):
    user_id: Optional[str] = None
    chatbot_id: str
    query: str
    session_id: Optional[str] = None
    no_of_chunks: Optional[int] = 3
    use_user_info: Optional[bool] = False  
    stream: Optional[bool] = False
    
# class ChatRequest(BaseModel):
#     user_id: Optional[str] = None
#     chatbot_id: str
#     query: str
#     session_id: Optional[str] = None
#     no_of_chunks: Optional[int] = 3
#     use_user_info: Optional[bool] = False
 
    
#     @model_validator(mode='before')
#     def validate_user_id(cls, values):
#         # Validate user_id if session_data dependency is disabled
#         if not ENABLE_GOOGLE_AUTH and not values.get("user_id"):
#             raise ValueError("user_id is required when session_data is not enabled.")
#         return values

# Define request model
# class ChatRequestAuth(BaseModel):
#     user_id: Optional[str] = None
#     chatbot_id: str
#     query: str
#     session_id: Optional[str] = None
#     no_of_chunks: Optional[int] = 3
#     use_user_info: Optional[bool] = False


#     @model_validator(mode='before')
#     def validate_user_id(cls, values):
#         # Validate user_id if session_data dependency is disabled
#         if not ENABLE_GOOGLE_AUTH and not values.get("user_id"):
#             raise ValueError("user_id is required when session_data is not enabled.")
#         return values


class ChatResponse(BaseModel):
    response: str
    session_id: str
    chat_id: str
    debug_info: Optional[dict] = None
    graph_ouput: Optional[dict] = None

class DebugInfoSource(BaseModel):
    file_name: str
    context: str

class SessionData(BaseModel):
    session_id: str
    timestamp: str
    
class InsightResponse(BaseModel):
    sessions: List[SessionData]

class GetDbConnectionRequest(BaseModel):
    user_id: Optional[str] = None
    chatbot_id: str
    
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