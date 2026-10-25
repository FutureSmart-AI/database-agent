"""
Qdrant integration for few-shot examples storage and retrieval.
"""
import logging
from typing import List, Dict, Any, Optional
from agent.utils.qdrant_async_client import make_async_qdrant_client
from qdrant_client.http.models import VectorParams, Distance, PointStruct, Filter, FieldCondition, MatchValue, UpdateStatus
from qdrant_client.http import models
from langchain_openai import OpenAIEmbeddings
from fastapi import HTTPException
from dotenv import load_dotenv
from agent.utils.embedding_config import FEWSHOT_EMBEDDING_MODEL, FEWSHOT_EMBEDDING_SIZE, verify_vector_size
import os
from uuid import uuid4
from knowledge.services.logger import logger

load_dotenv()

# Load environment variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
QDRANT_URL = os.getenv("qdrant_url")
QDRANT_API_KEY = os.getenv("qdrant_api_key")

logger = logging.getLogger(__name__)

class QdrantFewShotStore:
    def __init__(self):
        # qdrant_api_key is optional: an internal/self-hosted Qdrant runs without auth.
        if not all([OPENAI_API_KEY, QDRANT_URL]):
            raise ValueError("Missing required environment variables: OPENAI_API_KEY, qdrant_url")

        self.collection_name = "few-shot-examples"
        self.client = make_async_qdrant_client(
            url=QDRANT_URL,
            api_key=QDRANT_API_KEY or None,
            timeout=10,
        )
        
    @property
    def embedding_function(self) -> OpenAIEmbeddings:
        """Built per use, not once at startup: the key is the bound owner's on a
        bring-your-own-key workspace, and the environment key otherwise."""
        from agent.utils.provider_key_scope import env_key_for
        return OpenAIEmbeddings(model=FEWSHOT_EMBEDDING_MODEL,
                                api_key=env_key_for("openai", "OPENAI_API_KEY"))

    async def initialize(self):
        """Initialize the Qdrant collection for few-shot examples."""
        try:
            # Check if collection exists
            collections = await self.client.get_collections()
            collection_names = [col.name for col in collections.collections]
            
            logger.info(f"Existing collections: {collection_names}")
            
            if self.collection_name not in collection_names:
                logger.info(f"Creating new collection: {self.collection_name}")
                await self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(size=FEWSHOT_EMBEDDING_SIZE, distance=Distance.COSINE)
                )
                logger.info(f"Successfully created few-shot examples collection: {self.collection_name}")
            else:
                logger.info(f"Collection {self.collection_name} already exists")
                info = await self.client.get_collection(self.collection_name)
                verify_vector_size(getattr(info.config.params.vectors, "size", None),
                                   FEWSHOT_EMBEDDING_SIZE, self.collection_name)
                
        except Exception as e:
            logger.error(f"Error initializing Qdrant collection: {e}")
            raise

    async def add_few_shot_example(self, user_id: str, agent_id: str, example: Dict[str, Any], db_id: Optional[str] = None) -> str:
        """Add a new few-shot example to the store."""
        try:
            logger.info(f"Adding few-shot example for user_id: {user_id}, agent_id: {agent_id}")
            logger.info(f"Example data: {example}")

            # Generate embedding for the example
            text_to_embed = f"{example['question']}\n{example['sql_query']}"
            logger.info(f"Text to embed: {text_to_embed}")

            # Use sync embedding for debugging
            embedding = await self.embedding_function.aembed_query(text_to_embed)
            logger.info(f"Generated embedding with length: {len(embedding) if embedding else 'None'}")

            if not embedding:
                raise ValueError("Failed to generate embedding")

            # Create point for Qdrant with UUID
            point_id = str(uuid4())
            logger.info(f"Generated point_id: {point_id}")

            point = PointStruct(
                id=point_id,
                payload={
                    "user_id": user_id,
                    "agent_id": agent_id,  # Use agent_id instead of chatbot_id
                    "db_id": db_id,
                    "question": example["question"],
                    "sql_query": example["sql_query"],
                    "example_id": example["id"]
                },
                vector=embedding
            )
            
            logger.info(f"Created point structure: {point.id}")
            
            # Upsert to Qdrant
            result = await self.client.upsert(
                collection_name=self.collection_name,
                points=[point]
            )
            
            logger.info(f"Upsert result: {result}")
            
            # Verify the point was added by checking collection info
            collection_info = await self.client.get_collection(self.collection_name)
            logger.info(f"Collection info after upsert: points_count={collection_info.points_count}")
            
            return point_id
            
        except Exception as e:
            logger.error(f"Error adding few-shot example: {e}")
            logger.error(f"Exception type: {type(e)}")
            raise

    async def get_few_shot_examples(self, user_id: str, agent_id: str, db_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve all few-shot examples for a specific agent."""
        try:
            logger.info(f"Retrieving examples for user_id: {user_id}, agent_id: {agent_id}")

            filter_conditions = [
                models.FieldCondition(
                    key="user_id",
                    match=models.MatchValue(value=user_id)
                ),
                models.FieldCondition(
                    key="agent_id",
                    match=models.MatchValue(value=agent_id)
                )
            ]

            if db_id is not None:
                filter_conditions.append(
                    models.FieldCondition(
                        key="db_id",
                        match=models.MatchValue(value=db_id)
                    )
                )
            
            examples: List[Dict[str, Any]] = []
            offset = None
            
            while True:
                # Async client.scroll may return a tuple (points, next_page_offset)
                result = await self.client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=Filter(must=filter_conditions),
                    offset=offset,
                    limit=100,
                    with_payload=True,
                )
                
                points_batch = None
                next_offset = None
                if isinstance(result, tuple):
                    # qdrant_client <=1.7 returns tuple
                    points_batch, next_offset = result
                else:
                    # Newer returns a ScrollResponse
                    points_batch = getattr(result, "points", None)
                    next_offset = getattr(result, "next_page_offset", None)
                
                if not points_batch:
                    break
                
                for point in points_batch:
                    payload = getattr(point, "payload", None)
                    if payload:
                        examples.append(payload)
                
                if not next_offset:
                    break
                offset = next_offset
                
            logger.info(f"Retrieved {len(examples)} examples")
            return examples
            
        except Exception as e:
            logger.error(f"Error retrieving few-shot examples: {e}")
            raise

    async def delete_few_shot_example(self, user_id: str, agent_id: str, example_id: str, db_id: Optional[str] = None) -> bool:
        """Delete a specific few-shot example."""
        try:
            if not isinstance(example_id, str):
                logger.error(f"Invalid example_id type: {type(example_id)}. Converting to string.")
                example_id = str(example_id)

            logger.info(f"Deleting example for user_id: {user_id}, agent_id: {agent_id}, example_id: {example_id}")

            # Create filter to find the specific example
            filter_conditions = [
                FieldCondition(key="user_id", match=MatchValue(value=user_id)),
                FieldCondition(key="agent_id", match=MatchValue(value=agent_id)),
                FieldCondition(key="question", match=MatchValue(value=example_id))
            ]

            if db_id is not None:
                filter_conditions.append(
                    FieldCondition(key="db_id", match=MatchValue(value=db_id))
                )

            # Delete points matching the filter
            result = await self.client.delete(
                collection_name=self.collection_name,
                points_selector=Filter(must=filter_conditions)
            )

            logger.info(f"Delete result: {result}")
            return True

        except Exception as e:
            logger.error(f"Error deleting few-shot example: {e}")
            raise

    async def update_few_shot_example(self, user_id: str, agent_id: str, example: Dict[str, Any], db_id: Optional[str] = None) -> bool:
        """Update an existing few-shot example."""
        try:
            logger.info(f"Updating example for user_id: {user_id}, agent_id: {agent_id}")

            # First delete the old example
            await self.delete_few_shot_example(user_id, agent_id, example["id"], db_id=db_id)
            # Then add the updated example
            await self.add_few_shot_example(user_id, agent_id, example, db_id=db_id)
            return True

        except Exception as e:
            logger.error(f"Error updating few-shot example: {e}")
            raise

    async def get_similar_examples(self, query: str, user_id: str, agent_id: str, limit: int = 3, db_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve similar few-shot examples based on query similarity."""
        try:
            logger.info(f"Getting similar examples for query: {query}")

            query_embedding = await self.embedding_function.aembed_query(query)

            # Build filter conditions - user_id is optional
            filter_conditions = [
                models.FieldCondition(
                    key="agent_id",
                    match=models.MatchValue(value=agent_id)
                )
            ]
            if db_id is not None:
                filter_conditions.append(
                    models.FieldCondition(
                        key="db_id",
                        match=models.MatchValue(value=db_id)
                    )
                )
            # Only add user_id filter if provided
            if user_id:
                filter_conditions.append(
                    models.FieldCondition(
                        key="user_id",
                        match=models.MatchValue(value=user_id)
                    )
                )

            # Use query_points with raw vector and named params
            response = await self.client.query_points(
                collection_name=self.collection_name,
                query=query_embedding,
                limit=limit,
                query_filter=models.Filter(must=filter_conditions),
                with_payload=True,
            )
            
            points = response.points or []
            results = [point.payload for point in points]
            logger.info(f"Found {len(results)} similar examples")
            return results
            
        except Exception as e:
            logger.error(f"Error retrieving similar examples: {e}")
            raise

    async def check_collection_status(self):
        """Debug method to check collection status."""
        try:
            collections = await self.client.get_collections()
            logger.info(f"All collections: {[col.name for col in collections.collections]}")
            
            if self.collection_name in [col.name for col in collections.collections]:
                collection_info = await self.client.get_collection(self.collection_name)
                logger.info(f"Collection '{self.collection_name}' info: {collection_info}")
                return True
            else:
                logger.warning(f"Collection '{self.collection_name}' not found")
                return False
                
        except Exception as e:
            logger.error(f"Error checking collection status: {e}")
            return False