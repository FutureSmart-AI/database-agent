import pymysql
import aiomysql
import asyncio
import os
from datetime import time
from sqlmodel import select
from database_connection.services.sqlmodel_session import get_async_session
from datetime import datetime
from database_connection.services.logger import logger


def get_connection():
    host = os.getenv("DB_HOST")
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    db = os.getenv("DB_NAME")
    con = pymysql.connect(host=host, user=user, passwd=password, db=db, cursorclass=pymysql.cursors.DictCursor)
    return con

async def get_async_connection():
    # Replace with your actual database connection parameters
    port = os.getenv("DB_PORT")
    return await aiomysql.connect(
        host = os.getenv("DB_HOST"),
        user = os.getenv("DB_USER"),
        password = os.getenv("DB_PASSWORD"),
        db = os.getenv("DB_NAME"),
        port=int(port),
    )

