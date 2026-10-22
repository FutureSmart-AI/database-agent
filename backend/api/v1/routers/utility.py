"""
RESTful API utility endpoints
Provides system-level information and health checks
"""

from fastapi import APIRouter, HTTPException, Depends
from chatbot_management.utils.api_validation import get_api_key_or_session
from chatbot_management.services.logger import logger


router = APIRouter(prefix="/v1")


@router.get("/")
async def root(auth: dict = Depends(get_api_key_or_session)):
    """
    Root endpoint - Welcome message
    """
    return {"message": "Welcome to nl2sql agent"}


@router.get("/models")
async def get_available_models(auth: dict = Depends(get_api_key_or_session)):

    logger.info(f"Received request to get Providers and Models")
    try:
        # Use the same response structure as the old /get-models endpoint
        response_data = {
                        "providers": [
                            {
                            "provider_name": "openai",
                            "models": [
                                { "model_name": "gpt-5.6-sol" },
                                { "model_name": "gpt-5.6-terra" },
                                { "model_name": "gpt-5.6-luna" },
                                { "model_name": "gpt-5.4" },
                                { "model_name": "gpt-5.4-mini" },
                                { "model_name": "gpt-5.4-nano" },
                                { "model_name": "gpt-5.2" },
                                { "model_name": "gpt-5.1" },
                                { "model_name": "gpt-5" },
                                { "model_name": "gpt-5-mini" }
                            ],
                            "default_model": "gpt-5.4-mini"
                            },
                            {
                            "provider_name": "anthropic",
                            "models": [
                                { "model_name": "claude-opus-4-6" },
                                { "model_name": "claude-opus-4-5" },
                                { "model_name": "claude-sonnet-4-6" },
                                { "model_name": "claude-sonnet-4-5" },
                                { "model_name": "claude-haiku-4-5" }
                            ],
                            "default_model": "claude-sonnet-4-6"
                            },
                            {
                            "provider_name": "google",
                            "models": [
                                { "model_name": "gemini-3.1-pro-preview" },
                                { "model_name": "gemini-3-flash-preview" },
                                { "model_name": "gemini-3.8-flash" },
                                { "model_name": "gemini-3.6-flash" },
                                { "model_name": "gemini-3.5-flash-lite" },
                                { "model_name": "gemini-2.5-pro" },
                                { "model_name": "gemini-2.5-flash" },
                                { "model_name": "gemini-2.5-flash-lite" }
                            ],
                            "default_model": "gemini-2.5-flash"
                            },
                            {
                            "provider_name": "groq",
                            "models": [
                                { "model_name": "openai/gpt-oss-120b" },
                                { "model_name": "openai/gpt-oss-20b" },
                                { "model_name": "meta-llama/llama-4-scout-17b-16e-instruct" },
                                { "model_name": "qwen/qwen3-32b" }
                            ],
                            "default_model": "openai/gpt-oss-120b"
                            },
                            {
                            "provider_name": "deepseek",
                            "models": [
                                { "model_name": "deepseek-v4-flash" },
                                { "model_name": "deepseek-v4-pro" }
                            ],
                            "default_model": "deepseek-v4-flash"
                            },
                            {
                            "provider_name": "minimax",
                            "models": [
                                { "model_name": "MiniMax-M3" },
                                { "model_name": "MiniMax-M2.7-highspeed" }
                            ],
                            "default_model": "MiniMax-M3"
                            }
                        ]
                        }
        if response_data is None:
            raise HTTPException(status_code=404, detail="Providers not found")
        return response_data
    except Exception as e:
        logger.error(f"An unexpected error occurred while fetching providers: {e}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred while fetching providers {e}")


@router.get("/health")
async def health_check(auth: dict = Depends(get_api_key_or_session)):
    """
    Health check endpoint
    """
    return {"status": "ok"}


@router.get("/metrics")
async def get_metrics(auth: dict = Depends(get_api_key_or_session)):
    """
    Get Prometheus metrics endpoint
    """
    from prometheus_client import REGISTRY, generate_latest
    from fastapi.responses import Response
    logger.info("Serving Prometheus metrics")

    # Generate and return Prometheus metrics
    metrics = generate_latest(REGISTRY)
    return Response(content=metrics, media_type="text/plain; version=0.0.4; charset=utf-8")

