import time
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import logging
from sqlmodel import select
from models.sql_models import FewShotExamples
from session.services.sqlmodel_session import get_async_session
from agent.db_utils.database_db_utils import get_primary_db_id
from uuid import uuid4
import os

# ==== Few-Shot Example Database (PostgreSQL) ==== #
async def upload_to_db_few_shot(user_id, chatbot_id, few_shot_examples, file_name=''):
    try:
        async with get_async_session() as session:
            res = await session.execute(
                select(FewShotExamples).where(
                    FewShotExamples.user_id == user_id,
                    FewShotExamples.chatbot_id == chatbot_id
                )
            )
            record = res.first()
            if record:
                record = record[0]  # Unpack ORM object from tuple
                record.file_name = file_name
                record.few_shot_examples = few_shot_examples
            else:
                record = FewShotExamples(
                    user_id=user_id,
                    chatbot_id=chatbot_id,
                    db_id=(await get_primary_db_id(chatbot_id)) or chatbot_id,
                    agent_id=chatbot_id,  # Sync both IDs for consistency
                    file_name=file_name,
                    few_shot_examples=few_shot_examples
                )
                session.add(record)
            await session.commit()
            return {"message": "Few-shot examples uploaded successfully", "status": True}
    except Exception as e:
        logging.error(f"Exception in upload_to_db_few_shot: {str(e)}")
        return {"message": f"Error in upload_to_db_few_shot: {str(e)}", "status": False}

async def list_fewshot_examples_from_db(user_id: str, chatbot_id: str):
    try:
        async with get_async_session() as session:
            res = await session.execute(
                select(FewShotExamples.few_shot_examples, FewShotExamples.created_at).where(
                    FewShotExamples.user_id == user_id,
                    FewShotExamples.chatbot_id == chatbot_id
                )
            )
            record = res.first()
            if record:
                return {"record": {"few_shot_examples": record[0], "created_at": record[1]}, "message": "Few-shot examples listed successfully", "status": True}
            else:
                return {"record": None, "message": "No few-shot examples found", "status": False}
    except Exception as e:
        logging.error(f"Exception in list_fewshot_examples_from_db: {str(e)}")
        return {"message": f"Error in list_fewshot_examples_from_db: {str(e)}", "status": False}

# ==== Qdrant Few-Shot Logic (Vector DB) with Local Imports ==== #
from agent.utils.qdrant_async_client import make_async_qdrant_client
from qdrant_client.http.models import VectorParams, Distance, PointStruct, Filter, FieldCondition, MatchValue
from langchain_openai import OpenAIEmbeddings
from fastapi import HTTPException

class QdrantFewShotStore:
    def __init__(self):
        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
        self.QDRANT_URL = os.getenv("qdrant_url")
        self.QDRANT_API_KEY = os.getenv("qdrant_api_key")
        if not all([self.OPENAI_API_KEY, self.QDRANT_URL, self.QDRANT_API_KEY]):
            raise ValueError("Missing required environment variables.")
        self.embedding_function = OpenAIEmbeddings(
            model="text-embedding-3-large",
            api_key=self.OPENAI_API_KEY
        )
        self.collection_name = "few-shot-examples"
        self.client = make_async_qdrant_client(
            url=self.QDRANT_URL,
            api_key=self.QDRANT_API_KEY,
            timeout=10,
        )
    async def initialize(self):
        try:
            collections = await self.client.get_collections()
            collection_names = [col.name for col in collections.collections]
            if self.collection_name not in collection_names:
                await self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(size=3072, distance=Distance.COSINE)
                )
        except Exception as e:
            logging.error(f"Error initializing Qdrant collection: {e}")
            raise
    async def add_few_shot_example(self, user_id: str, chatbot_id: str, example: Dict[str, Any]) -> str:
        try:
            # Handle old format: question as key, SQL as value
            if len(example) == 1:
                question = list(example.keys())[0]
                sql_query = list(example.values())[0]
            else:
                # Fallback for new format if needed
                question = example.get("question", "")
                sql_query = example.get("sql_query", "")
            
            text_to_embed = f"{question}\n{sql_query}"
            embedding = await self.embedding_function.aembed_query(text_to_embed)
            if not embedding:
                raise ValueError("Failed to generate embedding")
            point_id = str(uuid4())
            point = PointStruct(
                id=point_id,
                payload={
                    "user_id": user_id,
                    "chatbot_id": chatbot_id,
                    "question": question,
                    "sql_query": sql_query
                },
                vector=embedding
            )
            await self.client.upsert(
                collection_name=self.collection_name,
                points=[point]
            )
            return point_id
        except Exception as e:
            logging.error(f"Error adding few-shot example to Qdrant: {e}")
            raise

class FewShotService:
    def __init__(self):
        self.store = None
        self._initialized = False
    async def initialize(self):
        if not self._initialized:
            self.store = QdrantFewShotStore()
            await self.store.initialize()
            self._initialized = True
    async def ensure_initialized(self):
        if not self._initialized or self.store is None:
            await self.initialize()
    async def add_example(self, user_id: str, chatbot_id: str, example: Dict[str, Any]) -> str:
        await self.ensure_initialized()
        return await self.store.add_few_shot_example(user_id, chatbot_id, example)

# Singleton access for FewShotService in session.
few_shot_service = None
import asyncio
_service_lock = asyncio.Lock()
async def get_few_shot_service() -> FewShotService:
    global few_shot_service
    async with _service_lock:
        if few_shot_service is None:
            few_shot_service = FewShotService()
            await few_shot_service.initialize()
        return few_shot_service
