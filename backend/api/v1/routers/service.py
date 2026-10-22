"""
RESTful API endpoints for NL2SQL Service Validation
Provides lightweight validation endpoints for Agent Registry integration
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from chatbot_management.utils.api_validation import get_api_key_or_session
from chatbot_management.services.logger import logger
import traceback

# Import schemas from centralized location
from api.v1.schemas.service import (
    ValidateServiceResponse,
    ListServicesResponse,
)
from api.v1.utils.service_helper import validate_nl2sql_service, list_nl2sql_services

router = APIRouter(prefix="/v1")


# ============================================================================
# NL2SQL Service Validation Endpoints
# ============================================================================

@router.get("/validate")
async def validate_service(
    owner_id: str = Query(..., description="Owner/user identifier"),
    service_id: str = Query(..., description="Service identifier (agent_id)"),
    auth: dict = Depends(get_api_key_or_session)
):
    """
    Validate if an NL2SQL service exists and belongs to the specified owner.

    """
    try:
        if auth.get("auth_type") == "session":
            session_user = auth.get("user_id")
            if owner_id and owner_id.lower() != session_user.lower():
                logger.warning(f"Validation owner mismatch: provided={owner_id}, session={session_user}")
                return ValidateServiceResponse(valid=False)

        logger.info(f"Validating NL2SQL service: owner_id={owner_id}, service_id={service_id}")
        valid = await validate_nl2sql_service(owner_id, service_id)
        return ValidateServiceResponse(valid=valid)

    except Exception as e:
        logger.error(f"Error validating NL2SQL service: {str(e)}")
        traceback.print_exc()
        return ValidateServiceResponse(valid=False)


@router.get("/service", response_model=ListServicesResponse)
async def list_services(
    owner_id: Optional[str] = Query(None, description="Owner/user identifier to filter results"),
    auth: dict = Depends(get_api_key_or_session)
):
    """
    List NL2SQL services. If owner_id is provided, returns services for that owner.
    If not provided, returns all non-deleted services.
    """
    try:
        if auth.get("auth_type") == "session":
            session_user = auth.get("user_id")
            if owner_id and owner_id.lower() != session_user.lower():
                raise HTTPException(status_code=403, detail="You can only list your own services")
            owner_id = session_user

        logger.info(f"Listing NL2SQL services, filter by owner_id: {owner_id}, auth_type: {auth.get('auth_type')}")
        service_ids = await list_nl2sql_services(owner_id)

        if owner_id:
            return ListServicesResponse(owner_id=owner_id, service_ids=service_ids, count=len(service_ids))
        return ListServicesResponse(service_ids=service_ids, count=len(service_ids))

    except Exception as e:
        logger.error(f"Error listing NL2SQL services: {str(e)}")
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred while listing services: {str(e)}"
        )
