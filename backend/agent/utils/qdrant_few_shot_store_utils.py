"""Qdrant integration for few-shot examples storage and retrieval."""
import logging
from typing import List, Dict, Any, Optional
from agent.utils.qdrant_async_client import make_async_qdrant_client
from qdrant_client.http.models import VectorParams, Distance, PointStruct, Filter, FieldCondition, MatchValue, UpdateStatus
from qdrant_client.http import models
from langchain_openai import OpenAIEmbeddings
from fastapi import HTTPException
from dotenv import load_dotenv
import os
from uuid import uuid4
import time
from agent.utils.usage_tracking import get_usage_tracker
from agent.utils.embedding_config import FEWSHOT_EMBEDDING_MODEL, FEWSHOT_EMBEDDING_SIZE, verify_vector_size
from agent.utils.model_profiles import ModelConfigurationError

load_dotenv()

# Load environment variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
QDRANT_URL = os.getenv("qdrant_url")
QDRANT_API_KEY = os.getenv("qdrant_api_key")

logger = logging.getLogger(__name__)


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return len(str(text).split())

class QdrantFewShotStore:
    _collection_verified = False

    def __init__(self):
        # qdrant_api_key is optional: an internal/self-hosted Qdrant runs without auth.
        if not all([OPENAI_API_KEY, QDRANT_URL]):
            raise ModelConfigurationError("Missing required environment variables: OPENAI_API_KEY, qdrant_url")
        self.collection_name = "few-shot-examples"
        self.client = make_async_qdrant_client(
            url=QDRANT_URL,
            api_key=QDRANT_API_KEY or None,
            timeout=10,
        )
        
    async def initialize(self):
        """Initialize the Qdrant collection for few-shot examples."""
        if QdrantFewShotStore._collection_verified:
            return

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
                logger.info(
                    f"Successfully created few-shot examples collection: {self.collection_name} "
                    f"({FEWSHOT_EMBEDDING_MODEL}, {FEWSHOT_EMBEDDING_SIZE}-d)"
                )
            else:
                # An existing collection's vector size is fixed. If it was built for a
                # different model, every write is rejected and every search fails — and the
                # symptom (empty few-shots, so worse SQL) is easy to misread as a prompt
                # problem. Say so loudly, with the fix.
                info = await self.client.get_collection(self.collection_name)
                try:
                    current = info.config.params.vectors.size
                except AttributeError:
                    current = None
                verify_vector_size(current, FEWSHOT_EMBEDDING_SIZE, self.collection_name)
            
            QdrantFewShotStore._collection_verified = True
                
        except Exception as e:
            logger.error(f"Error initializing Qdrant collection: {e}")
            raise

    async def add_few_shot_example(
        self,
        user_id: str,
        agent_id: str,
        example: Dict[str, Any],
        owner_id: Optional[str] = None,
        session_id: Optional[str] = None,
        request_id: Optional[str] = None,
        db_id: Optional[str] = None,
    ) -> str:
        """Add a new few-shot example to the store."""
        try:
            logger.info(f"Adding few-shot example for user_id: {user_id}, agent_id: {agent_id}")
            logger.info(f"Example data: {example}")

            from agent.utils.owner_credential_utils import get_owner_api_key_for_provider
            embedding_model = FEWSHOT_EMBEDDING_MODEL
            provider = "openai"
            api_key_to_use = OPENAI_API_KEY
            key_type = "platform-key"
            try:
                if owner_id:
                    key, source = await get_owner_api_key_for_provider(owner_id, provider, return_source=True)
                    if key:
                        api_key_to_use = key
                        key_type = source or "owner-key"
            except Exception:
                key_type = "platform-key"
            embedding_function = OpenAIEmbeddings(model=embedding_model, api_key=api_key_to_use)

            # Generate embedding for the example
            text_to_embed = f"{example['question']}\n{example['sql_query']}"
            logger.info(f"Text to embed: {text_to_embed}")

            start_time = time.time()
            embedding = await embedding_function.aembed_query(text_to_embed)
            duration_ms = float((time.time() - start_time) * 1000.0)
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

            try:
                tracker = get_usage_tracker()
                token_count = _estimate_tokens(text_to_embed)
                metadata = {
                    "provider": "openai",
                    "model": embedding_model,
                    "chunks_only": False,
                }
                metrics = [
                    {"name": "duration_ms", "value": duration_ms},
                    {"name": "total_tokens", "value": float(token_count)},
                    {"name": "examples_indexed", "value": 1.0},
                ]
                usage_payload = {
                    "owner_id": owner_id or user_id,
                    "service_id": agent_id,
                    "service_type": os.getenv("USAGE_SERVICE_TYPE", "nl2sql"),
                    "operation": "embedding_generation",
                    "label": "fewshot_indexing",
                    "session_id": session_id,
                    "request_id": request_id,
                    "operation_id": "fewshot_indexing",
                    "key_type": key_type,
                    "metadata": metadata,
                    "metrics": metrics,
                }
                logger.info(f"Usage (local) fewshot_indexing payload={usage_payload}")
                await tracker.record_event(
                    owner_id=owner_id or user_id,
                    agent_id=agent_id,
                    operation="embedding_generation",
                    label="fewshot_indexing",
                    session_id=session_id,
                    request_id=request_id,
                    operation_id="fewshot_indexing",
                    key_type=key_type,
                    metadata=metadata,
                    metrics=metrics,
                )
            except Exception as e:
                logger.warning(f"Failed to record fewshot_indexing usage event (non-blocking): {e}")
            
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

            if user_id is not None:
                filter_conditions.append(
                    models.FieldCondition(
                        key="user_id",
                        match=models.MatchValue(value=user_id)
                    )
                )
            
            points = []
            offset = None
            
            while True:
                response = await self.client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=Filter(must=filter_conditions),
                    offset=offset,
                    limit=100
                )
                
                if not response.points:
                    break
                    
                points.extend([point.payload for point in response.points])
                
                if not response.next_page_offset:
                    break
                    
                offset = response.next_page_offset
                
            logger.info(f"Retrieved {len(points)} examples")
            return points
            
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
                FieldCondition(key="agent_id", match=MatchValue(value=agent_id)),
                FieldCondition(key="question", match=MatchValue(value=example_id))
            ]

            if db_id is not None:
                filter_conditions.append(
                    FieldCondition(key="db_id", match=MatchValue(value=db_id))
                )

            if user_id is not None:
                filter_conditions.append(
                    FieldCondition(key="user_id", match=MatchValue(value=user_id))
                )
            
            # Use points.delete with filter to remove points
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

    async def get_similar_examples(
        self,
        query: str,
        user_id: str,
        agent_id: str,
        limit: int = 3,
        owner_id: Optional[str] = None,
        session_id: Optional[str] = None,
        request_id: Optional[str] = None,
        db_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve similar few-shot examples based on query similarity."""
        try:
            logger.info(f"Getting similar examples for query: {query}")

            from agent.utils.owner_credential_utils import get_owner_api_key_for_provider
            embedding_model = FEWSHOT_EMBEDDING_MODEL
            provider = "openai"
            api_key_to_use = OPENAI_API_KEY
            key_type = "platform-key"
            try:
                if owner_id:
                    key, source = await get_owner_api_key_for_provider(owner_id, provider, return_source=True)
                    if key:
                        api_key_to_use = key
                        key_type = source or "owner-key"
            except Exception:
                key_type = "platform-key"
            embedding_function = OpenAIEmbeddings(model=embedding_model, api_key=api_key_to_use)

            start_time = time.time()
            query_embedding = await embedding_function.aembed_query(query)

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
            # if user_id:
            #     filter_conditions.append(
            #         models.FieldCondition(
            #             key="user_id",
            #             match=models.MatchValue(value=user_id)
            #         )
            #     )

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

            try:
                tracker = get_usage_tracker()
                duration_ms = float((time.time() - start_time) * 1000.0)
                tokens_from_examples = 0
                for payload in results:
                    question = ""
                    sql_query = ""
                    if isinstance(payload, dict):
                        question = str(payload.get("question", ""))
                        sql_query = str(payload.get("sql_query", ""))
                    tokens_from_examples += _estimate_tokens(f"{question}\n{sql_query}")
                metadata = {
                    "provider": "openai",
                    "model": embedding_model,
                }
                metrics = [
                    {"name": "duration_ms", "value": duration_ms},
                    {"name": "total_tokens", "value": float(tokens_from_examples)},
                    {"name": "examples_returned", "value": float(len(results))},
                ]
                usage_payload = {
                    "owner_id": owner_id or user_id,
                    "service_id": agent_id,
                    "service_type": os.getenv("USAGE_SERVICE_TYPE", "nl2sql"),
                    "operation": "embedding_generation",
                    "label": "fewshot_retrieval",
                    "session_id": session_id,
                    "request_id": request_id,
                    "operation_id": "fewshot_retrieval",
                    "key_type": key_type,
                    "metadata": metadata,
                    "metrics": metrics,
                }
                logger.info(f"Usage (local) fewshot_retrieval payload={usage_payload}")
                await tracker.record_event(
                    owner_id=owner_id or user_id,
                    agent_id=agent_id,
                    operation="embedding_generation",
                    label="fewshot_retrieval",
                    session_id=session_id,
                    request_id=request_id,
                    operation_id="fewshot_retrieval",
                    key_type=key_type,
                    metadata=metadata,
                    metrics=metrics,
                )
            except Exception as e:
                logger.warning(f"Failed to record fewshot_retrieval usage event (non-blocking): {e}")

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
