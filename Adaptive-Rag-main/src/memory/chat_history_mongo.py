"""
Chat history storage with MongoDB backend and automatic in-memory fallback.
"""

from __future__ import annotations
import asyncio
import logging
from datetime import datetime
from typing import List

from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import BaseMessage

from src.memory.chathistory_in_memory import ChatInMemoryHistory

logger = logging.getLogger("src.memory.chat_history")

# Try to get mongo collection, handling missing mongo client gracefully
_mongo_available = True
try:
    from src.db.mongo_client import db
    collection = db["chat_history"]
except Exception as e:
    logger.warning("MongoDB client initialization failed: %s. Using in-memory fallback.", e)
    _mongo_available = False
    collection = None


class MongoDBChatMessageHistory(BaseChatMessageHistory):
    """
    Chat history backed by MongoDB with automatic in-memory fallback if DB is unreachable.
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._fallback_history = ChatInMemoryHistory.get_session_history(session_id)

    async def add_message(self, message: BaseMessage) -> None:
        """Save a message to MongoDB with fast timeout fallback."""
        global _mongo_available
        if _mongo_available and collection is not None:
            try:
                # 2-second timeout to avoid freezing requests
                await asyncio.wait_for(
                    collection.insert_one({
                        "session_id": self.session_id,
                        "type": message.type,
                        "content": message.content,
                        "additional_kwargs": message.additional_kwargs,
                        "timestamp": datetime.utcnow(),
                    }),
                    timeout=2.0,
                )
                return
            except Exception as e:
                logger.warning(
                    "MongoDB write failed for session %s (%s). Falling back to in-memory store.",
                    self.session_id,
                    e,
                )
                _mongo_available = False

        # Fallback to in-memory history
        self._fallback_history.add_message(message)

    async def get_messages(self) -> List[BaseMessage]:
        """Load all messages for a session from MongoDB with fallback."""
        global _mongo_available
        if _mongo_available and collection is not None:
            try:
                from langchain_core.messages import messages_from_dict

                cursor = collection.find({"session_id": self.session_id}).sort("timestamp", 1)
                docs = await asyncio.wait_for(cursor.to_list(length=1000), timeout=2.0)

                return messages_from_dict([
                    {
                        "type": d["type"],
                        "data": {
                            "content": d["content"],
                            "additional_kwargs": d.get("additional_kwargs", {}),
                        },
                    }
                    for d in docs
                ])
            except Exception as e:
                logger.warning(
                    "MongoDB read failed for session %s (%s). Falling back to in-memory store.",
                    self.session_id,
                    e,
                )
                _mongo_available = False

        # Fallback to in-memory history
        return self._fallback_history.messages

    async def clear(self) -> None:
        """Delete all messages for a session."""
        if _mongo_available and collection is not None:
            try:
                await asyncio.wait_for(
                    collection.delete_many({"session_id": self.session_id}),
                    timeout=2.0,
                )
            except Exception:
                pass
        ChatInMemoryHistory.clear_history(self.session_id)


class ChatHistory:
    """Factory for MongoDB-backed chat history."""

    @classmethod
    def get_session_history(
        cls,
        session_id: str,
        config: dict = None,
    ) -> MongoDBChatMessageHistory:
        return MongoDBChatMessageHistory(session_id)
