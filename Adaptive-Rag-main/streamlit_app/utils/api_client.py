"""
API client for communicating with backend services, including real-time SSE streaming.
"""

import json
import logging
import os
from typing import Generator, Callable, Optional
import requests

logger = logging.getLogger(__name__)

# Backend service URLs
# AUTH_SERVICE_BASE_URL points to the Python auth_service / gateway on port 8080
AUTH_SERVICE_BASE_URL = os.getenv("AUTH_SERVICE_URL", "http://localhost:8080/api")
PYTHON_BASE_URL = os.getenv("PYTHON_BASE_URL", "http://127.0.0.1:8000")


def create_user(username: str, password: str, api_token: str) -> bool:
    """Create a new user account through the gateway."""
    headers = {
        "X-API-TOKEN": api_token,
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(
            f"{AUTH_SERVICE_BASE_URL}/create_user",
            json={"username": username, "password": password},
            headers=headers,
        )
        if response.status_code == 200:
            return True
        logger.error("Create user failed: %s - %s", response.status_code, response.text)
        return False
    except requests.RequestException as e:
        logger.exception("Request to /create_user failed: %s", e)
        return False


def login_user(username: str, password: str, api_token: str) -> Optional[dict]:
    """Authenticate user login and receive JWT."""
    headers = {
        "X-API-TOKEN": api_token,
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(
            f"{AUTH_SERVICE_BASE_URL}/login",
            json={"username": username, "password": password},
            headers=headers,
        )
        if response.status_code == 200:
            return response.json()
    except requests.RequestException as e:
        logger.exception("Login request failed: %s", e)
    return None


def get_api_token() -> Optional[str]:
    """Get an initial session API token from the gateway."""
    try:
        response = requests.post(f"{AUTH_SERVICE_BASE_URL}/init")
        if response.status_code == 200:
            return response.json().get("api_token")
    except requests.RequestException as e:
        logger.exception("Init request failed: %s", e)
    return None


def query_backend(query: str, session_id: str) -> str:
    """Synchronous query (fallback)."""
    url = f"{PYTHON_BASE_URL}/rag/query"
    try:
        response = requests.post(
            url,
            json={"query": query, "session_id": session_id},
            timeout=60,
        )
        if response.status_code == 200:
            return response.json()["result"]["content"]
        return f"Error: {response.status_code} - {response.text}"
    except Exception as e:
        return f"Request failed: {e}"


def stream_chat_backend(
    query: str,
    jwt_token: str,
    on_status: Optional[Callable[[str], None]] = None,
) -> Generator[str, None, None]:
    """
    Stream chat response word-by-word via Server-Sent Events (SSE) from the gateway.
    Yields string token chunks suitable for st.write_stream().
    Calls on_status(message) when intermediate agent status events arrive.
    """
    url = f"{AUTH_SERVICE_BASE_URL}/chat/stream"
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Content-Type": "application/json",
    }

    try:
        with requests.post(
            url,
            json={"query": query},
            headers=headers,
            stream=True,
            timeout=120,
        ) as response:
            if response.status_code != 200:
                yield f"⚠️ Server Error ({response.status_code}): {response.text}"
                return

            for line in response.iter_lines():
                if line:
                    decoded = line.decode("utf-8").strip()
                    if decoded.startswith("data: "):
                        data_json = decoded[6:]
                        try:
                            event = json.loads(data_json)
                            ev_type = event.get("type")

                            if ev_type == "status":
                                if on_status:
                                    on_status(event.get("text", ""))
                            elif ev_type == "token":
                                yield event.get("content", "")
                            elif ev_type == "error":
                                yield f"\n\n⚠️ Error: {event.get('message', 'Unknown error')}"
                            elif ev_type == "done":
                                break
                        except json.JSONDecodeError:
                            continue

    except requests.RequestException as e:
        logger.exception("Error connecting to streaming endpoint: %s", e)
        yield f"\n\n⚠️ Connection Error: {e}"


def document_upload_rag(file, description: str) -> bool:
    """Upload a document to the RAG system."""
    headers = {"X-Description": description}
    url = f"{PYTHON_BASE_URL}/rag/documents/upload"

    if file:
        files = {"file": (file.name, file, file.type)}
        try:
            response = requests.post(url, files=files, headers=headers)
            if response.status_code == 200:
                return True
        except requests.RequestException as e:
            logger.exception("Upload error: %s", e)

    return False


def get_model_status() -> dict:
    """Fetch status of local AI models and cloud AI providers."""
    url = f"{AUTH_SERVICE_BASE_URL}/models/status"
    try:
        resp = requests.get(url, timeout=3.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass

    try:
        resp = requests.get(f"{PYTHON_BASE_URL}/rag/models/status", timeout=3.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass

    try:
        from src.llms.provider import get_active_provider_status
        return get_active_provider_status()
    except Exception as e:
        return {"error": str(e), "is_local": False, "active_provider": "unknown"}


def switch_model_provider(provider: str, model: Optional[str] = None) -> dict:
    """Switch AI provider between local and cloud."""
    url = f"{AUTH_SERVICE_BASE_URL}/models/switch"
    try:
        resp = requests.post(url, json={"provider": provider, "model": model}, timeout=5.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass

    try:
        from src.llms.provider import switch_provider
        return {"status": "success", "active": switch_provider(provider, model)}
    except Exception as e:
        return {"error": str(e)}

