"""
Authentication and cryptographic utilities for the Authentication & Gateway Service.
Uses Argon2id hashing and PyJWT tokens (100% cryptographic compatibility).
"""

from __future__ import annotations
import time
import logging
from typing import Optional, Dict, Any
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHash

from auth_service.config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRATION_SECONDS

logger = logging.getLogger("auth_service.auth")
hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2id."""
    return hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against an Argon2 hash."""
    try:
        return hasher.verify(hashed_password, plain_password)
    except (VerificationError, InvalidHash) as e:
        logger.warning("Password verification failed: %s", e)
        return False
    except Exception as e:
        logger.error("Unexpected error during password verification: %s", e)
        return False


def generate_jwt(username: str) -> str:
    """Generate a signed JWT token valid for 1 hour."""
    now = int(time.time())
    payload = {
        "sub": username,
        "exp": now + JWT_EXPIRATION_SECONDS,
        "iat": now,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def validate_jwt(token: str) -> Optional[Dict[str, Any]]:
    """Validate and decode a JWT token. Returns payload dict if valid, else None."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.PyJWTError as e:
        logger.warning("JWT validation failed: %s", e)
        return None
