"""
Configuration settings for the Authentication & Gateway Service.
"""

import os

# Server configuration
AUTH_SERVICE_HOST = os.getenv("AUTH_SERVICE_HOST", "127.0.0.1")
AUTH_SERVICE_PORT = int(os.getenv("AUTH_SERVICE_PORT", "8080"))

# Target Python RAG backend
PYTHON_RAG_URL = os.getenv("PYTHON_RAG_URL", "http://127.0.0.1:8000/rag/query")
PYTHON_RAG_STREAM_URL = os.getenv("PYTHON_RAG_STREAM_URL", "http://127.0.0.1:8000/rag/query/stream")
PYTHON_RAG_WS_URL = os.getenv("PYTHON_RAG_WS_URL", "ws://127.0.0.1:8000/rag/ws/query")

# JWT configuration
JWT_SECRET = os.getenv("JWT_SECRET", "super_secret_jwt_key")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_SECONDS = 3600  # 1 hour

# Database path (compatible with existing users.db)
DB_PATH = os.getenv("AUTH_DB_PATH", os.path.abspath("users.db"))
