"""
API route controllers for the Authentication & Gateway Service.
Provides endpoints for session initialization, user management, login, and chat proxying.
"""

from __future__ import annotations
import uuid
import logging
from typing import Optional, Set, Tuple, Dict, Any
import httpx
from fastapi import APIRouter, Header, HTTPException, status

from auth_service.config import PYTHON_RAG_URL
from auth_service.database import create_user_record, get_user_password_hash
from auth_service.auth import hash_password, verify_password, generate_jwt, validate_jwt
from auth_service.models import CreateUserRequest, LoginRequest, TokenResponse, ChatRequest, ChatResponse

logger = logging.getLogger("auth_service.routes")
router = APIRouter(prefix="/api")

# In-memory storage of valid API session tokens
active_api_tokens: Set[str] = set()


def require_api_token(x_api_token: Optional[str]):
    """Enforce X-API-TOKEN presence and validity."""
    if not x_api_token or x_api_token not in active_api_tokens:
        logger.warning("Unauthorized API token attempt: %s", x_api_token)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API token",
        )


def require_jwt(authorization: Optional[str]) -> Tuple[str, Dict[str, Any]]:
    """Validate Bearer JWT from Authorization header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )
    token = authorization[7:].strip()
    payload = validate_jwt(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid JWT",
        )
    return token, payload


@router.post("/init", response_model=TokenResponse)
async def init_session():
    """
    Public session initialization endpoint.
    Generates and registers an API token for the client session.
    """
    api_token = str(uuid.uuid4())
    active_api_tokens.add(api_token)
    logger.info("Session initialized with API token: %s", api_token)
    return TokenResponse(api_token=api_token, jwt=None)


@router.post("/create_user")
async def create_user(
    payload: CreateUserRequest,
    x_api_token: Optional[str] = Header(None, alias="X-API-TOKEN"),
):
    """
    User registration endpoint.
    Hashes password using Argon2id and stores in SQLite.
    Protected by X-API-TOKEN header.
    """
    require_api_token(x_api_token)

    hashed = hash_password(payload.password)
    logger.info("Creating user: %s", payload.username)

    success = create_user_record(payload.username, hashed)
    if not success:
        logger.warning("User creation failed, user already exists: %s", payload.username)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists",
        )

    return {"status": "created"}


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    x_api_token: Optional[str] = Header(None, alias="X-API-TOKEN"),
):
    """
    User authentication endpoint.
    Verifies Argon2id password hash and returns signed JWT.
    Protected by X-API-TOKEN header.
    """
    require_api_token(x_api_token)

    stored_hash = get_user_password_hash(payload.username)
    if not stored_hash:
        logger.warning("Login failed: User not found: %s", payload.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if not verify_password(payload.password, stored_hash):
        logger.warning("Login failed: Incorrect password for %s", payload.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    jwt_token = generate_jwt(payload.username)
    logger.info("User logged in successfully: %s", payload.username)
    return TokenResponse(api_token=None, jwt=jwt_token)


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    authorization: Optional[str] = Header(None),
):
    """
    Authenticated chat gateway proxy.
    Validates JWT and proxies request to the Python FastAPI RAG core.
    """
    token, _ = require_jwt(authorization)

    request_body = {
        "query": payload.query,
        "session_id": token,
    }
    logger.info("Forwarding chat query to RAG service (%s)", PYTHON_RAG_URL)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(PYTHON_RAG_URL, json=request_body)

        if response.status_code == 200:
            data = response.json()
            result_obj = data.get("result", {})
            if isinstance(result_obj, dict):
                content = result_obj.get("content", "No AI response found")
            else:
                content = str(result_obj)
            return ChatResponse(answer=content)
        else:
            logger.error(
                "Upstream Python RAG error: %s - %s",
                response.status_code,
                response.text,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Python RAG service returned error: {response.status_code}",
            )

    except httpx.RequestError as e:
        logger.error("Failed to connect to Python RAG service: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to contact Python RAG service: {e}",
        )
