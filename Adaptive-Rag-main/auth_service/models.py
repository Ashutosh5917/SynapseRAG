"""
Pydantic data schemas for request and response payloads.
"""

from typing import Optional
from pydantic import BaseModel


class CreateUserRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    api_token: Optional[str] = None
    jwt: Optional[str] = None


class ChatRequest(BaseModel):
    query: str


class ChatResponse(BaseModel):
    answer: str
