"""
API routes for RAG operations, including real-time SSE streaming and WebSockets.
"""

import json
from fastapi import APIRouter, UploadFile, File, Header, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, AIMessage

from pydantic import BaseModel
from typing import Optional
from src.memory.chat_history_mongo import ChatHistory
from src.models.query_request import QueryRequest
from src.rag.document_upload import documents
from src.rag.graph_builder import builder
from src.rag.stream_handler import stream_adaptive_rag
from src.llms.provider import get_active_provider_status, switch_provider

class ModelSwitchRequest(BaseModel):
    provider: str
    model: Optional[str] = None

router = APIRouter()


@router.post("/rag/query")
async def rag_query(req: QueryRequest):
    """
    Process a standard (synchronous) RAG query and return the full result.
    """
    chat_history = ChatHistory.get_session_history(req.session_id)
    await chat_history.add_message(HumanMessage(content=req.query))

    messages = await chat_history.get_messages()
    result = builder.invoke({
        "messages": messages
    })
    output_text = result["messages"][-1].content

    await chat_history.add_message(AIMessage(content=output_text))

    return {"result": result["messages"][-1]}


@router.post("/rag/query/stream")
async def rag_query_stream(req: QueryRequest):
    """
    Process a RAG query and stream tokens word-by-word via Server-Sent Events (SSE).
    Emits intermediate agent status events followed by token chunks.
    """
    async def event_generator():
        async for event in stream_adaptive_rag(req.query, req.session_id):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.websocket("/rag/ws/query")
async def rag_query_websocket(websocket: WebSocket):
    """
    Bidirectional WebSocket endpoint for word-by-word streaming.
    Client sends: {"query": "...", "session_id": "..."}
    Server streams: {"type": "status"|"token"|"done"|"error", ...}
    """
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            query = data.get("query")
            session_id = data.get("session_id", "default_session")
            if not query:
                await websocket.send_json({
                    "type": "error",
                    "message": "Missing required field: query",
                })
                continue

            async for event in stream_adaptive_rag(query, session_id):
                await websocket.send_json(event)

    except WebSocketDisconnect:
        pass


@router.post("/rag/documents/upload")
async def upload_file(
    file: UploadFile = File(...),
    description: str = Header(..., alias="X-Description"),
):
    """
    Upload a document for RAG processing (PDF or TXT).
    """
    status_upload = documents(description, file)
    return {"status": status_upload}


@router.get("/rag/models/status")
async def get_models_status():
    """Return local model discovery status and active model configuration."""
    return get_active_provider_status()


@router.post("/rag/models/switch")
async def switch_model(payload: ModelSwitchRequest):
    """Dynamically switch between local AI models and cloud AI."""
    updated = switch_provider(payload.provider, payload.model)
    return {"status": "success", "active": updated}
