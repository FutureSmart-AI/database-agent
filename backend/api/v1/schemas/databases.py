"""
Pydantic schemas for the Multi-DB `databases` collection.
See docs/multi-db-spec.md §8.
"""
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, List


class BulkDeleteDatabasesRequest(BaseModel):
    """Delete multiple databases (and their scoped metadata) in a single action."""
    db_ids: List[str] = Field(..., min_length=1, description="Database IDs to delete",
                              examples=[["DB_3F9A1C2B", "DB_5C1E9A22"]])

    @field_validator("db_ids")
    @classmethod
    def _dedupe_nonempty(cls, v):
        cleaned = [x.strip() for x in (v or []) if isinstance(x, str) and x.strip()]
        # preserve order, drop duplicates
        seen, out = set(), []
        for x in cleaned:
            if x not in seen:
                seen.add(x); out.append(x)
        if not out:
            raise ValueError("db_ids must contain at least one non-empty id")
        return out


# A port default belongs to the engine, not to a constant. Defaulting every request to 3306
# pointed PostgreSQL requests at MySQL's port, where the connect can only time out — and the
# RDS dialog has no port field at all, so nothing overrode it.
_DEFAULT_PORT_BY_ENGINE = {"mysql": 3306, "postgresql": 5432}


class _EnginePortDefault(BaseModel):
    """Resolves an omitted `db_port` from `db_engine`. An explicit port always wins."""

    @model_validator(mode="after")
    def _port_from_engine(self):
        if self.db_port is None:
            engine = (self.db_engine or "mysql").lower()
            self.db_port = _DEFAULT_PORT_BY_ENGINE.get(engine, 3306)
        return self


class AddDatabaseRequest(_EnginePortDefault):
    """Add a database to an agent. `description` is OPTIONAL — leave blank to auto-generate it
    after adding (the DB is saved inactive until a description exists)."""
    db_host: str = Field(..., description="Database host address")
    db_name: str = Field(..., description="Database name")
    db_user: str = Field(..., description="Database username")
    db_password: str = Field(..., description="Database password")
    db_port: Optional[int] = Field(None, description="Database port (default: the engine's — 3306 MySQL, 5432 PostgreSQL)")
    db_engine: str = Field("mysql", description="Database engine (mysql, postgresql)")
    description: Optional[str] = Field(None, description="Routing description (optional — blank → auto-generate)")


class UpdateDatabaseRequest(BaseModel):
    """Partial update of a database. Any field may be omitted."""
    db_host: Optional[str] = None
    db_name: Optional[str] = None
    db_user: Optional[str] = None
    db_password: Optional[str] = None
    db_port: Optional[int] = None
    db_engine: Optional[str] = None
    description: Optional[str] = None

    @field_validator("description")
    @classmethod
    def _non_empty_if_present(cls, v):
        if v is not None and not v.strip():
            raise ValueError("description is required")
        return v


class DatabaseStatusRequest(BaseModel):
    is_active: bool = Field(..., description="Enable (true) or disable (false) the database")


class DatabaseDescriptionRequest(BaseModel):
    description: str = Field(..., min_length=1, description="Routing description")

    @field_validator("description")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("description is required")
        return v


class RdsListRequest(_EnginePortDefault):
    """List databases available on an RDS instance (RDS connect flow, step 1)."""
    db_host: str
    db_engine: str = Field("mysql", description="mysql | postgresql")
    db_user: str
    db_password: str
    db_port: Optional[int] = Field(None, description="Database port (default: the engine's — 3306 MySQL, 5432 PostgreSQL)")


class TestConnectionRequest(_EnginePortDefault):
    """Test a database connection without saving it (Add modal 'Test', RDS step 2, Retry)."""
    db_host: str = Field(..., description="Database host address")
    db_name: str = Field(..., description="Database name")
    db_user: str = Field(..., description="Database username")
    db_password: str = Field(..., description="Database password")
    db_port: Optional[int] = Field(None, description="Database port (default: the engine's — 3306 MySQL, 5432 PostgreSQL)")
    db_engine: str = Field("mysql", description="Database engine (mysql, postgresql)")
