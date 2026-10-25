from typing import Optional
import random
import uuid
import re
import csv
# import sqlparse
# from sqlparse.sql import IdentifierList, Identifier
# from sqlparse.tokens import Keyword, DML

from logger import logger

def generate_bot_id() -> str:
    unique_str = str(uuid.uuid4()).split("-")[0]
    return f"NL2SQL_{unique_str}".upper()
