from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from fastapi import Form, UploadFile, File

class UploadTableDesc(BaseModel):
    user_id: Optional[str] = None
    chatbot_id: str = Form(...)
    url: Optional[str] = Form(...)

class DeleteTableDesc(BaseModel):
    user_id: Optional[str] = None
    chatbot_id: str
    table_names: list

class ExculdeInclude(BaseModel):
    user_id: Optional[str] = None
    chatbot_id: str
    table_names: list
    value: bool

class TableColumns(BaseModel):
    table_name: str
    columns: List[str]

class HighCardinalityColumnsInput(BaseModel):
    cardinality_columns: List[TableColumns]

class GetDbConnectionRequest(BaseModel):
    user_id: Optional[str] = None
    chatbot_id: str
