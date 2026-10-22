"""
Pydantic schemas for Database Connection endpoints
"""
from pydantic import BaseModel, Field
from typing import Optional


class DatabaseConnectionResponse(BaseModel):
    """Response model for database connection details"""
    agent_id: str
    owner_id: str
    database_connection: dict
    
    
class DatabaseConnectionRequest(BaseModel):
    """Request model for updating database connection"""
    # user_id: Optional[str] = Field(None, description="User ID (optional if using auth token)")
    db_host: str = Field(..., description="Database host address")
    db_name: str = Field(..., description="Database name")
    db_user: str = Field(..., description="Database username")
    db_password: str = Field(..., description="Database password")
    db_port: int = Field(3306, description="Database port (default: 3306 for MySQL)")
    db_engine: str = Field("mysql", description="Database engine (mysql, postgresql, sqlite)")


class TestDatabaseConnectionRequest(BaseModel):
    """Request model for testing database connection"""
    # user_id: Optional[str] = Field(None, description="User ID (optional if using auth token)")
    db_host: str = Field(..., description="Database host address")
    db_name: str = Field(..., description="Database name")
    db_user: str = Field(..., description="Database username")
    db_password: str = Field(..., description="Database password")
    db_port: int = Field(3306, description="Database port (default: 3306 for MySQL)")
    db_engine: str = Field("mysql", description="Database engine (mysql, postgresql, sqlite)")

