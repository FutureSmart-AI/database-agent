"""
Service to handle few-shot examples using Qdrant.
"""
from typing import List, Dict, Any
from fastapi import HTTPException
from knowledge.utils.qdrant_few_shot_store_utils import QdrantFewShotStore
from knowledge.services.logger import logger
import asyncio

class FewShotService:
    def __init__(self):
        self.store = None
        self._initialized = False
        
    async def initialize(self):
        """Initialize the Qdrant store."""
        if not self._initialized:
            try:
                logger.info("Initializing QdrantFewShotStore...")
                self.store = QdrantFewShotStore()
                await self.store.initialize()
                self._initialized = True
                logger.info("QdrantFewShotStore initialized successfully")
                
                # Debug: Check collection status
                status = await self.store.check_collection_status()
                logger.info(f"Collection status check: {status}")
                
            except Exception as e:
                logger.error(f"Failed to initialize QdrantFewShotStore: {e}")
                self._initialized = False
                raise
        
    async def ensure_initialized(self):
        """Ensure the service is initialized before use."""
        if not self._initialized or self.store is None:
            await self.initialize()
        
    async def add_example(self, user_id: str, agent_id: str, example: Dict[str, Any], db_id: str | None = None) -> str:
        """Add a new few-shot example."""
        try:
            await self.ensure_initialized()
            logger.info(f"Adding example via service: user_id={user_id}, agent_id={agent_id}")
            result = await self.store.add_few_shot_example(user_id, agent_id, example, db_id=db_id)
            logger.info(f"Example added successfully with ID: {result}")
            return result
        except Exception as e:
            logger.error(f"Error adding few-shot example: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def get_examples(self, user_id: str, agent_id: str, db_id: str | None = None) -> List[Dict[str, Any]]:
        """Get all few-shot examples for an agent."""
        try:
            await self.ensure_initialized()
            return await self.store.get_few_shot_examples(user_id, agent_id, db_id=db_id)
        except Exception as e:
            logger.error(f"Error retrieving few-shot examples: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def delete_example(self, user_id: str, agent_id: str, example_id: str, db_id: str | None = None) -> bool:
        """Delete a specific few-shot example."""
        try:
            await self.ensure_initialized()
            return await self.store.delete_few_shot_example(user_id, agent_id, example_id, db_id=db_id)
        except Exception as e:
            logger.error(f"Error deleting few-shot example: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def update_example(self, user_id: str, agent_id: str, example: Dict[str, Any], db_id: str | None = None) -> bool:
        """Update an existing few-shot example."""
        try:
            await self.ensure_initialized()
            return await self.store.update_few_shot_example(user_id, agent_id, example, db_id=db_id)
        except Exception as e:
            logger.error(f"Error updating few-shot example: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def get_similar_examples(self, query: str, user_id: str, agent_id: str, limit: int = 3, db_id: str | None = None) -> List[Dict[str, Any]]:
        """Get similar few-shot examples based on the query."""
        try:
            await self.ensure_initialized()
            return await self.store.get_similar_examples(query, user_id, agent_id, limit, db_id=db_id)
        except Exception as e:
            logger.error(f"Error retrieving similar examples: {e}")
            raise HTTPException(status_code=500, detail=str(e))

# Global instance
few_shot_service = None
_service_lock = asyncio.Lock()

async def get_few_shot_service() -> FewShotService:
    """Get or create the few-shot service instance."""
    global few_shot_service
    
    async with _service_lock:
        if few_shot_service is None:
            logger.info("Creating new FewShotService instance")
            few_shot_service = FewShotService()
            await few_shot_service.initialize()
            logger.info("FewShotService instance created and initialized")
        else:
            # Ensure it's initialized even if the instance exists
            await few_shot_service.ensure_initialized()
            
    return few_shot_service