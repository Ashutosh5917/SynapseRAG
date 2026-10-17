"""
API route controllers for the Authentication & Gateway Service.
Provides endpoints for session initialization, user management, login,
standard chat, Server-Sent Events (SSE) streaming, WebSockets,
and built-in rate limiting protection.
"""

from __future__ import annotations
import json
import time
import uuid
import logging
from typing import Optional, Set, Tuple, Dict, Any, List
import httpx
from fastapi import APIRouter, Header, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from auth_service.config import PYTHON_RAG_URL, PYTHON_RAG_STREAM_URL
from auth_service.database import create_user_record, get_user_password_hash
from auth_service.auth import hash_password, verify_password, generate_jwt, validate_jwt
from auth_service.models import CreateUserRequest, LoginRequest, TokenResponse, ChatRequest, ChatResponse

logger = logging.getLogger("auth_service.routes")
router = APIRouter(prefix="/api")

# In-memory storage of valid API session tokens
active_api_tokens: Set[str] = set()

# Rate limiting storage (Max 30 requests per minute per user/token)
RATE_LIMIT_WINDOW = 60.0
RATE_LIMIT_MAX_REQUESTS = 30
_request_timestamps: Dict[str, List[float]] = {}


def check_rate_limit(client_id: str):
    """Enforce rate limits to protect backend resources and LLM API quotas."""
    now = time.time()
    timestamps = _request_timestamps.get(client_id, [])
    # Prune outdated timestamps
    timestamps = [t for t in timestamps if now - t < RATE_LIMIT_WINDOW]
    if len(timestamps) >= RATE_LIMIT_MAX_REQUESTS:
        logger.warning("Rate limit exceeded for client %s", client_id)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded: Maximum 30 requests per minute.",
        )
    timestamps.append(now)
    _request_timestamps[client_id] = timestamps


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
    Standard synchronous chat proxy with rate limiting.
    """
    token, _ = require_jwt(authorization)
    check_rate_limit(token)

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


@router.post("/chat/stream")
async def chat_stream(
    payload: ChatRequest,
    authorization: Optional[str] = Header(None),
):
    """
    Word-by-word streaming proxy via Server-Sent Events (SSE) with rate limiting.
    """
    token, _ = require_jwt(authorization)
    check_rate_limit(token)

    request_body = {
        "query": payload.query,
        "session_id": token,
    }
    logger.info("Opening SSE streaming proxy to RAG service (%s)", PYTHON_RAG_STREAM_URL)

    async def event_proxy():
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream("POST", PYTHON_RAG_STREAM_URL, json=request_body) as response:
                    if response.status_code != 200:
                        yield f"data: {json.dumps({'type': 'error', 'message': f'Upstream error: {response.status_code}'})}\n\n"
                        return

                    async for chunk in response.aiter_lines():
                        if chunk:
                            yield f"{chunk}\n\n"
        except Exception as e:
            logger.exception("Error proxying SSE stream: %s", e)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_proxy(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.websocket("/chat/ws")
async def chat_websocket(websocket: WebSocket):
    """
    Real-time bidirectional WebSocket endpoint for streaming chat with rate limiting.
    """
    await websocket.accept()
    try:
        init_data = await websocket.receive_json()
        token = init_data.get("token")
        query = init_data.get("query")

        if not token or not validate_jwt(token):
            await websocket.send_json({"type": "error", "message": "Unauthorized: Invalid or missing JWT"})
            await websocket.close()
            return

        check_rate_limit(token)

        if not query:
            await websocket.send_json({"type": "error", "message": "Missing required field: query"})
            return

        request_body = {"query": query, "session_id": token}
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", PYTHON_RAG_STREAM_URL, json=request_body) as response:
                async for line in response.aiter_lines():
                    if line and line.startswith("data: "):
                        data_content = line[6:].strip()
                        await websocket.send_text(data_content)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.exception("WebSocket gateway error: %s", e)
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass


@router.get("/models/status")
async def get_models_status(authorization: Optional[str] = Header(None)):
    """Return local model discovery status and active model configuration."""
    target_url = PYTHON_RAG_URL.replace("/rag/query", "/rag/models/status")
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(target_url)
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        logger.debug("Upstream RAG models status unreachable: %s", e)

    try:
        from src.llms.provider import get_active_provider_status
        return get_active_provider_status()
    except Exception:
        from src.llms.model_discovery import discover_all_local_providers
        return {
            "is_local": False,
            "discovered_local_providers": discover_all_local_providers(),
            "active_provider": "auto",
        }


@router.post("/models/switch")
async def switch_model(payload: Dict[str, Any], authorization: Optional[str] = Header(None)):
    """Dynamically switch between local AI models and cloud AI."""
    target_url = PYTHON_RAG_URL.replace("/rag/query", "/rag/models/switch")
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(target_url, json=payload)
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        logger.debug("Upstream RAG model switch unreachable: %s", e)

    try:
        from src.llms.provider import switch_provider
        updated = switch_provider(payload.get("provider", "auto"), payload.get("model"))
        return {"status": "success", "active": updated}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

