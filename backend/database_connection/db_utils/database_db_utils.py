import pymysql
import psycopg2
from psycopg2 import OperationalError as PgOperationalError, DatabaseError as PgDatabaseError
from psycopg2 import OperationalError as PgOperationalError, DatabaseError as PgDatabaseError

import time
from datetime import datetime, timedelta

from database_connection.services.logger import logger
from database_connection.utils.exceptions import DatabaseConnectionError
from typing import Optional, Dict, Any


from sqlmodel import select
from models.sql_models import ChatbotConnection
from database_connection.services.sqlmodel_session import get_async_session
from datetime import datetime
import os

DATABASE_URL = os.getenv("DATABASE_URL")


async def _friendly_db_error(db_engine: str, exc: Exception) -> str:
    """
    Return a user-friendly error string with a short category prefix.
    Prefixes are used by the API layer to map to HTTP status codes.
    
    Uses PostgreSQL SQLSTATE codes for precise error identification:
    - 28P01: Invalid password
    - 28000: Invalid authorization (often wrong username)  
    - 3D000: Invalid database name
    - 08001/08006: Connection failure
    """
    raw = str(exc) or exc.__class__.__name__
    lower = raw.lower()
    engine = (db_engine or "").lower()
    
    # Enhanced logging to help diagnose error detection
    logger.info(f"DB Connection Error | Engine: {engine} | Exception Type: {type(exc).__name__}")
    logger.info(f"Full Error Message: {raw}")
    
    # ---- Check for hostname/DNS validation errors FIRST (common to all databases) ----
    # These occur before database connection is even attempted
    if isinstance(exc, UnicodeError) or "UnicodeError" in type(exc).__name__:
        # UnicodeError with IDNA codec = invalid hostname format (e.g., double dots, invalid characters)
        if "label empty or too long" in lower or "idna" in lower:
            return f"HOST_INVALID: Invalid hostname format for {engine}: contains invalid characters (such as '..') or is malformed. Please verify the database hostname."
        return f"HOST_INVALID: Invalid hostname format for {engine}. Please verify the database hostname."
    
    # Check for general hostname resolution errors
    if "getaddrinfo failed" in lower or "name or service not known" in lower:
        return f"HOST_INVALID: Cannot resolve {engine} hostname. Please verify the database hostname."
    
    # For PostgreSQL, also check pgerror attribute which has the full server error
    pgerror = None
    if isinstance(exc, (PgOperationalError, PgDatabaseError)):
        pgcode = getattr(exc, 'pgcode', None)
        pgerror = getattr(exc, 'pgerror', None)
        logger.info(f"PostgreSQL SQLSTATE Code: {pgcode}")
        if pgerror:
            logger.info(f"PostgreSQL Server Error (pgerror): {pgerror}")
            # Use pgerror for pattern matching as it's more complete
            lower = (pgerror or raw).lower()

    # ---- MySQL specific error code checking ----
    if engine == "mysql" and hasattr(exc, 'args') and len(exc.args) > 0:
        # MySQL errors have error code as first element in args tuple
        error_code = exc.args[0] if isinstance(exc.args[0], int) else None
        
        if error_code == 1045:  # Access denied for user
            # Error 1045 message format: "Access denied for user 'username'@'hostname' (using password: YES/NO)"
            # NOTE: MySQL returns this error for BOTH wrong username AND wrong password
            # Similar to PostgreSQL, MySQL doesn't distinguish for security (prevents user enumeration)
            error_msg = str(exc)
            logger.info(f"MySQL 1045 error details: {error_msg[:200]}")
            
            # Check for explicit password indication in the message
            if "using password: no" in lower or "using password:no" in lower:
                # If no password was provided, it's definitely a username issue
                return f"AUTH_USER: Invalid MySQL user: user account does not exist or password is required. Please verify the username."
            elif "accessing with an empty password" in lower or "requires a password" in lower:
                return f"AUTH_USER: Invalid MySQL user: user account does not exist or authentication method mismatch. Please verify the username."
            
            # For "using password: yes", we CANNOT reliably distinguish between wrong username and wrong password
            # MySQL intentionally returns the same error to prevent user enumeration attacks
            # So we must advise checking both credentials
            return f"AUTH_GENERIC: Authentication failed for MySQL: username or password is incorrect. Please verify both credentials."
        
        elif error_code == 1044:  # Access denied to database
            return f"AUTH_GENERIC: Insufficient privileges for MySQL: user does not have access to the specified database. Check MySQL user privileges."
        
        elif error_code == 1049:  # Unknown database
            return f"DB_NOT_FOUND: MySQL database not found: the specified database does not exist. Please verify the database name."
        
        elif error_code == 2003:  # Can't connect to MySQL server
            # MySQL error 2003 can be due to wrong host, wrong port, or network issues
            # We need to check the error message to distinguish
            error_msg = str(exc).lower()
            logger.info(f"MySQL 2003 error message: {error_msg[:300]}")
            
            if "connection refused" in error_msg or "refused" in error_msg:
                # Connection refused = port is likely wrong or service not running
                return "PORT_OR_NETWORK: Connection refused by MySQL server. Please verify the port number or ensure MySQL is running on that port."
            elif "timed out" in error_msg or "timeout" in error_msg:
                # Timeout = connection attempt took too long, likely wrong port or firewall
                return "PORT_OR_NETWORK: MySQL connection timeout. Please verify the port number and network settings."
            elif "no route to host" in error_msg or "host unreachable" in error_msg:
                # Network routing issue
                return "PORT_OR_NETWORK: Cannot reach MySQL server due to network/firewall/VPN issues. Please verify network connectivity."
            else:
                # Generic connection issue - could be multiple reasons
                return "PORT_OR_NETWORK: Cannot connect to MySQL server. Please verify the hostname, port number, and network settings."
        
        elif error_code == 2005:  # Unknown MySQL server host
            return "HOST_INVALID: MySQL hostname is invalid or cannot be resolved. Please verify the database hostname."
        
        elif error_code == 1064:  # SQL syntax error
            return f"DB_ERROR: MySQL query syntax error. Please verify the query syntax."
        
        elif error_code == 2002:  # Can't connect through socket
            return "PORT_OR_NETWORK: Cannot connect to MySQL server via socket. Please verify MySQL is running and the socket is accessible."

    # ---- Check for user/role existence errors (before generic auth checks) ----
    # This applies to both MySQL and PostgreSQL
    if "does not exist" in lower and ("user" in lower or "role" in lower):
        return f"AUTH_USER: Invalid {engine} user: account does not exist. Please verify the username."
    
    if "unknown user" in lower or "invalid user" in lower:
        return f"AUTH_USER: Invalid {engine} user: account does not exist. Please verify the username."

    # ---- SQLite specific error checking ----
    if engine == "sqlite":
        # SQLite errors are simpler since it's file-based
        logger.info(f"SQLite error type: {type(exc).__name__}")
        
        if "unable to open database file" in lower or "no such file or directory" in lower:
            return f"DB_NOT_FOUND: SQLite database file not found: the specified file does not exist. Please verify the database file path."
        
        elif "disk i/o error" in lower or "disk full" in lower:
            return f"DB_ERROR: SQLite disk I/O error: insufficient disk space or file system issue. Please verify disk space and file permissions."
        
        elif "database is locked" in lower or "locked" in lower:
            return f"DB_ERROR: SQLite database is locked: another process is currently using the database. Please try again later."
        
        elif "permission denied" in lower or "access denied" in lower:
            return f"DB_ERROR: SQLite permission denied: cannot access the database file. Please verify file permissions."
        
        elif "not a database" in lower or "file is encrypted" in lower or "corrupted" in lower:
            return f"DB_ERROR: SQLite database file is corrupted or invalid: the file is not a valid SQLite database. Please verify the file integrity."
        
        elif "readonly database" in lower or "read-only" in lower:
            return f"DB_ERROR: SQLite database is read-only: cannot write to the database. Please verify file permissions."

    # ---- Check for user/role existence errors FIRST (most specific) ----
    # PostgreSQL may return "role does not exist" or "user does not exist"
    # Check multiple patterns to catch all variations
    if "does not exist" in lower:
        # Check if it's about a role/user
        if "role" in lower or "user" in lower:
            return f"AUTH_USER: Invalid PostgreSQL user: account does not exist. Please verify the username."
        # Could be database, check later
    
    # Also check for "no such user" or "unknown user" patterns
    if ("no such" in lower and "user" in lower) or ("unknown" in lower and "user" in lower):
        return f"AUTH_USER: Invalid PostgreSQL user: account does not exist. Please verify the username."
    
    # ---- PostgreSQL specific error code checking ----
    if engine == "postgresql" and isinstance(exc, (PgOperationalError, PgDatabaseError)):
        # Check for PostgreSQL SQLSTATE error codes
        pgcode = getattr(exc, 'pgcode', None)
        logger.debug(f"PostgreSQL pgcode for detailed checking: {pgcode}")
        
        if pgcode == '3D000':  # Invalid database name
            return f"DB_NOT_FOUND: PostgreSQL database not found: the specified database does not exist. Please verify the database name."
        
        elif pgcode == '28000':  # Invalid authorization specification
            # This usually means the user doesn't exist or lacks privileges
            return f"AUTH_USER: Invalid PostgreSQL user or insufficient privileges: account does not exist or lacks permissions. Please verify the username."
        
        elif pgcode == '28P01':  # Invalid password/authentication
            # IMPORTANT: PostgreSQL returns this code for BOTH wrong password AND wrong username
            # for security (prevents user enumeration). Check message for clues.
            logger.info(f"28P01 error - checking message content: {lower[:100]}")
            
            # Check for authentication method issues
            if any(pattern in lower for pattern in ["no password", "ident", "peer", "trust"]):
                return f"AUTH_GENERIC: PostgreSQL authentication error: authentication method mismatch. Please check PostgreSQL pg_hba.conf settings or contact your database administrator."
            
            # If "does not exist" wasn't caught earlier, but we have 28P01, 
            # it's likely wrong password, but could also be wrong username
            # (PostgreSQL hides username validity for security)
            return f"AUTH_GENERIC: PostgreSQL authentication failed: username or password is incorrect. Please verify both credentials."
        
        elif pgcode in ('08001', '08006'):  # Connection failure
            return "PORT_OR_NETWORK: Cannot reach PostgreSQL server. Please verify the hostname, port number, network connectivity, VPN, and firewall settings."
        
        elif pgcode is None:
            # When pgcode is None, AWS RDS PostgreSQL doesn't provide specific error codes
            # This happens for BOTH wrong username AND wrong password (security by obscurity)
            # RDS tries multiple auth methods and often shows "no pg_hba.conf entry" for both cases
            
            if "password authentication failed" in lower:
                # Unfortunately, we CANNOT reliably distinguish between wrong username 
                # and wrong password when pgcode is None on AWS RDS PostgreSQL
                # Both scenarios produce similar error patterns
                logger.info("pgcode=None with password auth failed - cannot distinguish username vs password error")
                return f"AUTH_GENERIC: PostgreSQL authentication failed: username or password is incorrect. Please verify both credentials."
            
            # Check for pg_hba.conf issues alone (connection method problems)
            if "pg_hba.conf" in lower or "no pg_hba.conf entry" in lower:
                return f"AUTH_GENERIC: PostgreSQL authentication rejected: connection method not allowed by server configuration. Please contact your database administrator to check pg_hba.conf settings."

    # MySQL specific: Access denied errors
    if "access denied for user" in lower:
        # MySQL provides more details in the error message
        if "using password: yes" in lower:
            return f"AUTH_PASSWORD: Incorrect MySQL password: the password for this user is incorrect. Please verify the password."
        elif "using password: no" in lower:
            return f"AUTH_PASSWORD: MySQL password required: no password was provided but one is required. Please verify the password."
        else:
            return f"AUTH_PASSWORD: Access denied for {engine}: please verify the username and password."

    # Password authentication failures (fallback when specific codes not available)
    if "password authentication failed" in lower:
        # For PostgreSQL, this usually means wrong password when user exists
        # (wrong username would have been caught by "role does not exist" above)
        if engine == "postgresql":
            return f"AUTH_PASSWORD: Incorrect PostgreSQL password: the password for this user is incorrect. Please verify the password."
        return f"AUTH_PASSWORD: Incorrect {engine} password: the password is incorrect. Please verify the password."
    
    if "authentication failed for user" in lower:
        # If we reached here, it's likely a password issue (user existence was checked above)
        return f"AUTH_PASSWORD: Incorrect {engine} password: please verify the password."

    # Generic auth failure fallback
    if (
        "authentication failed" in lower
        or "invalid authorization specification" in lower
        or "access denied" in lower
        or "login failed" in lower
    ):
        return f"AUTH_GENERIC: {engine.capitalize()} authentication failed: please verify the username and password."

    # ---- Database name issues ----
    if ("does not exist" in lower and "database" in lower) or "unknown database" in lower:
        return f"DB_NOT_FOUND: {engine.capitalize()} database not found: the specified database does not exist. Please verify the database name."

    # ---- Host vs port / network issues ----
    # Hostname cannot be resolved
    if (
        "could not translate host name" in lower
        or "name or service not known" in lower
        or "getaddrinfo failed" in lower
        or "unknown host" in lower
    ):
        return f"HOST_INVALID: Database hostname is invalid or cannot be resolved for {engine}. Please verify the database hostname."

    # Host reachable but port / service issue (connection refused, timeout, etc.)
    if (
        "connection refused" in lower
        or "could not connect to server" in lower
        or "refused" in lower
    ):
        return f"PORT_OR_NETWORK: Connection refused by {engine} server. Please verify the port number or ensure the database service is running."
    
    if (
        "timed out" in lower
        or "timeout expired" in lower
        or "connection timeout" in lower
    ):
        return f"PORT_OR_NETWORK: {engine.capitalize()} connection timeout. Please verify the port number and network/firewall settings."
    
    if (
        "no route to host" in lower
        or "network is unreachable" in lower
        or "host unreachable" in lower
    ):
        return f"PORT_OR_NETWORK: Cannot reach {engine} server due to network/firewall/VPN issues. Please verify network connectivity."
    
    if (
        "server closed the connection unexpectedly" in lower
        or "lost connection" in lower
    ):
        return f"PORT_OR_NETWORK: Lost connection to {engine} server. Please verify network stability or server status."

    # ---- Fallback ----
    return f"CONNECTION_FAILED: {engine.capitalize()} connection failed. Please verify the hostname, port number, database name, username, and password."


async def get_db_connection_by_agent_id(agent_id: str) -> Optional[ChatbotConnection]:
    """
    Fetch database connection details by agent_id.
    """
    try:
        async for session in get_async_session():
            # Multi-DB: prefer the primary connection (an agent may now have many).
            result = await session.execute(
                select(ChatbotConnection)
                .where(
                    ChatbotConnection.agent_id == agent_id,
                    ChatbotConnection.deleted == False,  # noqa: E712 — never use a detached DB
                )
                .order_by(ChatbotConnection.is_active.desc(), ChatbotConnection.created_at)
            )
            return result.scalars().first()
    except Exception as e:
        logger.error(f"Error getting database connection by agent_id: {str(e)}")
        return None

async def upsert_db_connection_in_db(agent_id: str, db_details: Dict[str, Any], user_id: str, owner_id: Optional[str] = None) -> ChatbotConnection:
    """
    Create or update database connection details for an agent.

    owner_id: the owning agent's owner email, stored explicitly so a connection row is
    attributable without joining chatbot_details.
    """
    try:
        async for session in get_async_session():
            # Check if a (primary) connection exists — multi-DB targets the primary row.
            result = await session.execute(
                select(ChatbotConnection)
                .where(
                    ChatbotConnection.agent_id == agent_id,
                    ChatbotConnection.deleted == False,  # noqa: E712 — never revive a tombstone
                )
                .order_by(ChatbotConnection.is_active.desc(), ChatbotConnection.created_at)
            )
            connection = result.scalars().first()

            if connection:
                # Update existing
                connection.db_host = db_details.get("db_host")
                connection.db_name = db_details.get("db_name")
                connection.db_user = db_details.get("db_user")
                connection.db_password = db_details.get("db_password")
                connection.db_port = db_details.get("db_port")
                connection.db_engine = db_details.get("db_engine")
                if not connection.agent_id:
                    connection.agent_id = agent_id
            else:
                # Create new — becomes the agent's primary DB.
                from agent.db_utils.database_db_utils import generate_db_id
                connection = ChatbotConnection(
                    db_id=generate_db_id(),
                    user_id=user_id,
                    owner_id=owner_id,
                    chatbot_id=agent_id,
                    agent_id=agent_id,
                    db_host=db_details.get("db_host"),
                    db_name=db_details.get("db_name"),
                    db_user=db_details.get("db_user"),
                    db_password=db_details.get("db_password"),
                    db_port=db_details.get("db_port"),
                    db_engine=db_details.get("db_engine"),
                    is_active=True, status="connected",
                )
                session.add(connection)

            await session.commit()
            await session.refresh(connection)
            return connection
    except Exception as e:
        logger.error(f"Error upserting database connection: {str(e)}")
        raise

async def test_db_connection(host: str, user: str, password: str, db: str, port: int, db_engine: str):
    try:
        if db_engine.lower() == 'mysql':
            logger.info(f"MySQL connection attempt")
            con = pymysql.connect(host=host, user=user, passwd=password, db=db, port=port)
            con.close()
            return {"message": "MySQL connection successful.", "status": True}
        
        elif db_engine.lower() == 'postgresql':
            logger.info(f"PostgreSQL connection attempt")
            con = psycopg2.connect(host=host, user=user, password=password, dbname=db, port=port)
            con.close()
            return {"message": "PostgreSQL connection successful.", "status": True}
        
        elif db_engine.lower() == 'sqlite':
            logger.info(f"SQLite connection attempt")
            import sqlite3
            con = sqlite3.connect(db)
            con.close()
            return {"message": "SQLite connection successful.", "status": True}
        
        else:
            logger.info("Unsupported database engine: %s", db_engine)
            return {"message": "UNSUPPORTED_ENGINE: Unsupported database engine. Use mysql, postgresql, or sqlite.", "status": False}

    except Exception as e:
        # Log full details for debugging, but return a friendly message to clients.
        logger.exception("Database connection test failed | engine=%s host=%s port=%s db=%s user=%s", db_engine, host, port, db, user)
        raise DatabaseConnectionError(await _friendly_db_error(db_engine, e))
        # Log full details for debugging, but return a friendly message to clients.
        logger.exception("Database connection test failed | engine=%s host=%s port=%s db=%s user=%s", db_engine, host, port, db, user)
        raise DatabaseConnectionError(await _friendly_db_error(db_engine, e))

async def get_all_tables(db_config):
    """Fetch all table names from the given database."""
    tables = []
    if db_config["db_engine"] == "mysql":
        connection = pymysql.connect(
            host=db_config["db_host"],
            user=db_config["db_user"],
            password=db_config["db_password"],
            database=db_config["db_name"],
            port=db_config["db_port"]
        )
        try:
            with connection.cursor() as cursor:
                cursor.execute("SHOW TABLES")
                tables = cursor.fetchall()
                tables = [table[0] for table in tables]
        finally:
            connection.close()
    elif db_config["db_engine"] == "postgresql":
        connection = psycopg2.connect(
            host=db_config["db_host"],
            user=db_config["db_user"],
            password=db_config["db_password"],
            database=db_config["db_name"],
            port=db_config["db_port"]
        )
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
                tables = cursor.fetchall()
                tables = [table[0] for table in tables]
        finally:
            connection.close()
    return tables
