"""Encryption utilities for owner provider-key (BYOK) storage.

- Fernet symmetric encryption of the key itself (needs APP_MASTER_KEY)
- HMAC-SHA256 with a server-side salt (HASH_SALT) for duplicate detection without
  decrypting, and not reversible back to the key
- A masked form ("sk-...48sA") so the UI never handles the real key

Ported VERBATIM from fs-agent-usage-limits (`utils/encryption.py`) — only the logger
import changed. The algorithms, encodings and hash construction must stay byte-identical:
rows copied over from that service were encrypted by this exact code, and any drift makes
them undecryptable rather than merely incompatible.

APP_MASTER_KEY and HASH_SALT must therefore match that service's values. Both are read
from the process environment, never from a file in this repo — this repo's `.env.*` files
are tracked in git, and committing the master key next to the ciphertext would defeat the
encryption entirely.
"""

import os
import hmac
import hashlib
from cryptography.fernet import Fernet
from typing import Tuple
from logger import logger


def get_master_key() -> bytes:
    """
    Get the master encryption key from environment variable.

    Returns:
        bytes: The master key for Fernet encryption

    Raises:
        ValueError: If APP_MASTER_KEY is not set in environment
    """
    master_key = os.environ.get("APP_MASTER_KEY")
    if not master_key:
        raise ValueError("APP_MASTER_KEY environment variable is not set")

    # Ensure the key is properly formatted for Fernet (32 url-safe base64-encoded bytes)
    return master_key.encode('utf-8')


def get_hash_salt() -> bytes:
    """
    Get the server-side secret salt for HMAC hashing.

    Returns:
        bytes: The secret salt for HMAC

    Raises:
        ValueError: If HASH_SALT is not set in environment
    """
    hash_salt = os.environ.get("HASH_SALT")
    if not hash_salt:
        raise ValueError("HASH_SALT environment variable is not set")

    return hash_salt.encode('utf-8')


def encrypt_api_key(api_key: str) -> Tuple[str, str]:
    """
    Encrypt an API key using Fernet symmetric encryption and generate HMAC hash.

    Args:
        api_key: The plaintext API key to encrypt

    Returns:
        Tuple[str, str]: (encrypted_key, key_hash)
            - encrypted_key: Fernet ciphertext (base64-encoded string)
            - key_hash: HMAC-SHA256 hash of the key with server-side salt (hex string, 64 chars)

    Raises:
        ValueError: If master key or hash salt is not configured
        Exception: If encryption fails
    """
    try:
        master_key = get_master_key()
        hash_salt = get_hash_salt()

        # Create Fernet cipher
        fernet = Fernet(master_key)

        # Encrypt the API key
        encrypted_bytes = fernet.encrypt(api_key.encode('utf-8'))
        encrypted_key = encrypted_bytes.decode('utf-8')

        # Generate HMAC-SHA256 hash with server-side secret salt for duplicate detection
        key_hash = hmac.new(
            hash_salt,
            api_key.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        logger.info(f"Successfully encrypted API key (hash: {key_hash[:8]}...)")
        return encrypted_key, key_hash

    except Exception as e:
        logger.error(f"Encryption failed: {str(e)}", exc_info=True)
        raise


def decrypt_api_key(encrypted_key: str) -> str:
    """
    Decrypt an API key using Fernet symmetric encryption.
    
    Args:
        encrypted_key: The Fernet ciphertext (base64-encoded string)
        
    Returns:
        str: The decrypted plaintext API key
        
    Raises:
        ValueError: If master key is not configured
        Exception: If decryption fails (invalid key, corrupted data, etc.)
    """
    try:
        master_key = get_master_key()
        
        # Create Fernet cipher
        fernet = Fernet(master_key)
        
        # Decrypt the API key
        decrypted_bytes = fernet.decrypt(encrypted_key.encode('utf-8'))
        api_key = decrypted_bytes.decode('utf-8')
        
        logger.info("Successfully decrypted API key")
        return api_key
        
    except Exception as e:
        logger.error(f"Decryption failed: {str(e)}", exc_info=True)
        raise


def generate_key_hash(api_key: str) -> str:
    """
    Generate HMAC-SHA256 hash of an API key with server-side salt for duplicate detection.

    Args:
        api_key: The plaintext API key

    Returns:
        str: HMAC-SHA256 hash (hex string, 64 characters)

    Raises:
        ValueError: If hash salt is not configured
    """
    hash_salt = get_hash_salt()
    return hmac.new(
        hash_salt,
        api_key.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()


def mask_api_key(api_key: str) -> str:
    """
    Create a masked version of an API key for display.

    Format: First 3 characters + "..." + Last 4 characters

    Args:
        api_key: The plaintext API key

    Returns:
        str: Masked key (e.g., "sk-...48sA")

    Examples:
        >>> mask_api_key("example-value")
        "exa...alue"
    """
    if len(api_key) <= 7:
        # Key is too short to mask meaningfully
        return api_key

    return f"{api_key[:3]}...{api_key[-4:]}"

