from database_connection.services.logger import logger
import json
import os
 
import asyncpg
from datetime import datetime, timedelta
import time
from typing import List, Dict, Any, Optional
import uuid
from fastapi import HTTPException
import asyncio
from sqlmodel import SQLModel, Field, create_engine, select, Session, delete, update, and_, or_, desc, func, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker
from sqlalchemy import Column, String, Boolean, Integer, Float, DateTime, Text, LargeBinary, JSON, case, Numeric, join
from models.sql_models import *

# Validate and construct database URL
from runtime_config import metadata_url

DATABASE_URL = metadata_url("asyncpg").render_as_string(hide_password=False)
SYNC_DATABASE_URL = metadata_url("psycopg2").render_as_string(hide_password=False)

# Create async engine
engine = create_async_engine(DATABASE_URL, echo=False, hide_parameters=True, future=True)

# Create sync engine for backward compatibility
sync_engine = create_engine(SYNC_DATABASE_URL, echo=False, hide_parameters=True)

# Create async session factory using SQLAlchemy's async_sessionmaker
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Create sync session factory for backward compatibility
sync_session = sessionmaker(bind=sync_engine, class_=Session, expire_on_commit=False)

# Keep the old pool for backward compatibility during transition
global pool

async def init_db_pool():
    """Initialize the database connection pool."""
    global pool
    if 'pool' not in globals():
        address = metadata_url("asyncpg")
        pool = await asyncpg.create_pool(
            dsn=address.set(drivername="postgresql").render_as_string(hide_password=False),
            min_size=10, max_size=40,
        )
        logger.info("Database connection pool created")
    else:
        logger.info("Database connection pool reused")
    return pool

# Add this function to provide access to the connection pool
async def get_connection_pool():
    """Returns the database connection pool, initializing it if necessary."""
    global pool
    if 'pool' not in globals():
        pool = await init_db_pool()
    return pool

async def get_async_session():
    """
    Dependency that provides async database session.
    Use with FastAPI Depends() or async for loop.
    """
    async with async_session() as session:
        yield session

def get_sync_session():
    """Get synchronous session for SQLModel operations."""
    with sync_session() as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

# Alternative function if you need to get session directly
async def get_session() -> AsyncSession:
    """
    Get a database session directly (not for FastAPI dependency injection).
    Remember to close the session manually.
    """
    return async_session()