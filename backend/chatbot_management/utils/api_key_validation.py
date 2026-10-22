"""Live validation of owner-supplied provider API keys.

Each validator makes one cheap authenticated call to the provider (usually
`GET /v1/models`) and reports whether the key works. Used on the credential write path so
a bad key is rejected before it is stored — otherwise the failure only surfaces later, as
a query that silently fell back to the platform key.

Ported from fs-agent-usage-limits (`utils/api_key_validation.py`). Two differences:
`firecrawl` and `llamaparse` are dropped (NL2SQL has no web-scraping or document-parsing
path, and neither library is installed), while `deepseek`, `minimax` and the `gemini` alias
are added — NL2SQL supports all three (see
`agent/utils/owner_credential_utils.PROVIDER_ENV_MAP`) and upstream does not.

DeepSeek and MiniMax are OpenAI-compatible, so they validate through the same
`/v1/models` + Bearer shape against their own base URLs.
"""

import httpx
from typing import Tuple
from logger import logger
from otel_tracing import track_time

async def validate_openai_key(api_key: str) -> Tuple[bool, str]:
    """
    Validate an OpenAI API key by calling the models.list endpoint.
    
    Args:
        api_key: The OpenAI API key to validate
        
    Returns:
        Tuple[bool, str]: (is_valid, error_message)
            - is_valid: True if key is valid, False otherwise
            - error_message: Empty string if valid, error description if invalid
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://api.openai.com/v1/models",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
            )
            
            if response.status_code == 200:
                logger.info("OpenAI API key validation successful")
                return True, ""
            elif response.status_code == 401:
                error_msg = "Invalid API key or authentication failed"
                logger.warning(f"OpenAI key validation failed: {error_msg}")
                return False, error_msg
            elif response.status_code == 403:
                error_msg = "API key does not have access to OpenAI models"
                logger.warning(f"OpenAI key validation failed: {error_msg}")
                return False, error_msg
            else:
                error_msg = f"Unexpected response: {response.status_code}"
                logger.warning(f"OpenAI key validation failed: {error_msg}")
                return False, error_msg
                
    except httpx.TimeoutException:
        error_msg = "Request timeout while validating OpenAI key"
        logger.error(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"Validation error: {str(e)}"
        logger.error(f"OpenAI key validation error: {error_msg}", exc_info=True)
        return False, error_msg


async def validate_anthropic_key(api_key: str) -> Tuple[bool, str]:
    """
    Validate an Anthropic API key by calling a lightweight endpoint.
    
    Args:
        api_key: The Anthropic API key to validate
        
    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Use the messages endpoint with a minimal request
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "claude-3-haiku-20240307",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "Hi"}]
                }
            )
            
            if response.status_code == 200:
                logger.info("Anthropic API key validation successful")
                return True, ""
            elif response.status_code == 401:
                error_msg = "Invalid API key or authentication failed"
                logger.warning(f"Anthropic key validation failed: {error_msg}")
                return False, error_msg
            elif response.status_code == 403:
                error_msg = "API key does not have access to Anthropic models"
                logger.warning(f"Anthropic key validation failed: {error_msg}")
                return False, error_msg
            else:
                error_msg = f"Unexpected response: {response.status_code}"
                logger.warning(f"Anthropic key validation failed: {error_msg}")
                return False, error_msg
                
    except httpx.TimeoutException:
        error_msg = "Request timeout while validating Anthropic key"
        logger.error(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"Validation error: {str(e)}"
        logger.error(f"Anthropic key validation error: {error_msg}", exc_info=True)
        return False, error_msg



async def validate_google_key(api_key: str) -> Tuple[bool, str]:
    """
    Validate a Google Gemini API key.

    Args:
        api_key: The Gemini API key to validate

    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Use the models list endpoint
            response = await client.get(
                f"https://generativelanguage.googleapis.com/v1/models?key={api_key}"
            )

            if response.status_code == 200:
                logger.info("Gemini API key validation successful")
                return True, ""
            elif response.status_code == 400:
                error_msg = "Invalid API key format"
                logger.warning(f"Gemini key validation failed: {error_msg}")
                return False, error_msg
            elif response.status_code == 403:
                error_msg = "API key does not have access to Gemini models"
                logger.warning(f"Gemini key validation failed: {error_msg}")
                return False, error_msg
            else:
                error_msg = f"Unexpected response: {response.status_code}"
                logger.warning(f"Gemini key validation failed: {error_msg}")
                return False, error_msg

    except httpx.TimeoutException:
        error_msg = "Request timeout while validating Gemini key"
        logger.error(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"Validation error: {str(e)}"
        logger.error(f"Gemini key validation error: {error_msg}", exc_info=True)
        return False, error_msg


async def validate_groq_key(api_key: str) -> Tuple[bool, str]:
    """
    Validate a Groq API key.

    Args:
        api_key: The Groq API key to validate

    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://api.groq.com/openai/v1/models",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
            )

            if response.status_code == 200:
                logger.info("Groq API key validation successful")
                return True, ""
            elif response.status_code == 401:
                error_msg = "Invalid API key or authentication failed"
                logger.warning(f"Groq key validation failed: {error_msg}")
                return False, error_msg
            elif response.status_code == 403:
                error_msg = "API key does not have access to Groq models"
                logger.warning(f"Groq key validation failed: {error_msg}")
                return False, error_msg
            else:
                error_msg = f"Unexpected response: {response.status_code}"
                logger.warning(f"Groq key validation failed: {error_msg}")
                return False, error_msg

    except httpx.TimeoutException:
        error_msg = "Request timeout while validating Groq key"
        logger.error(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"Validation error: {str(e)}"
        logger.error(f"Groq key validation error: {error_msg}", exc_info=True)
        return False, error_msg

async def validate_firecrawl_key(api_key: str) -> Tuple[bool, str]:
    """
    Validate a Firecrawl API key.

    Firecrawl does not expose a validation endpoint.
    Validation is done via format + runtime usage.
    """
    if not api_key:
        return False, "API key is empty"

    # Firecrawl keys are usually long random strings
    if len(api_key) < 20:
        return False, "Invalid Firecrawl API key format"

    logger.info("Firecrawl API key validation successful (soft validation)")
    return True, ""

@track_time("API: Validate External Provider Key")
async def _validate_openai_compatible_key(
    api_key: str, base_url: str, provider_label: str
) -> Tuple[bool, str]:
    """Validate a key against an OpenAI-compatible `/models` endpoint.

    DeepSeek and MiniMax both speak the OpenAI API, so one implementation covers them —
    only the base URL differs.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{base_url}/models",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )

            if response.status_code == 200:
                logger.info(f"{provider_label} API key validation successful")
                return True, ""
            if response.status_code in (401, 403):
                error_msg = "Invalid API key or authentication failed"
                logger.warning(f"{provider_label} key validation failed: {error_msg}")
                return False, error_msg

            error_msg = f"Unexpected response from {provider_label}: HTTP {response.status_code}"
            logger.warning(error_msg)
            return False, error_msg

    except httpx.TimeoutException:
        error_msg = f"Timeout contacting {provider_label}"
        logger.error(error_msg)
        return False, error_msg
    except httpx.RequestError as e:
        error_msg = f"Could not reach {provider_label}: {e}"
        logger.error(error_msg)
        return False, error_msg


async def validate_deepseek_key(api_key: str) -> Tuple[bool, str]:
    """Validate a DeepSeek API key."""
    return await _validate_openai_compatible_key(api_key, "https://api.deepseek.com/v1", "DeepSeek")


async def validate_minimax_key(api_key: str) -> Tuple[bool, str]:
    """Validate a MiniMax API key."""
    return await _validate_openai_compatible_key(api_key, "https://api.minimax.io/v1", "MiniMax")


async def validate_api_key(provider: str, api_key: str) -> Tuple[bool, str]:
    """
    Validate an API key for the specified provider.

    Args:
        provider: Provider name (openai, anthropic, llamaparse, gemini, groq)
        api_key: The API key to validate

    Returns:
        Tuple[bool, str]: (is_valid, error_message)

    Raises:
        ValueError: If provider is not supported
    """
    validators = {
        "openai": validate_openai_key,
        "anthropic": validate_anthropic_key,
        "google": validate_google_key,
        # NL2SQL calls Google's models "gemini" in places (PROVIDER_ENV_MAP, and
        # get_provider_from_model returns "gemini"), so both spellings must resolve or a
        # Gemini key would be rejected as an unsupported provider.
        "gemini": validate_google_key,
        "groq": validate_groq_key,
        "deepseek": validate_deepseek_key,
        "minimax": validate_minimax_key,
    }

    if provider not in validators:
        raise ValueError(f"Unsupported provider: {provider}")

    return await validators[provider](api_key)

