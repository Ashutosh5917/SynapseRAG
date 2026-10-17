"""
FastAPI application entrypoint for the Authentication & Gateway Service.
Serves on port 8080 by default.
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from auth_service.config import AUTH_SERVICE_HOST, AUTH_SERVICE_PORT
from auth_service.database import init_db
from auth_service.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("auth_service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Authentication & Gateway Service...")
    init_db()
    logger.info("Service running on %s:%s", AUTH_SERVICE_HOST, AUTH_SERVICE_PORT)
    yield
    logger.info("Authentication & Gateway Service shutting down.")


app = FastAPI(
    title="Adaptive RAG - Authentication & Gateway Service",
    description="Enterprise Authentication, Session Identity & Gateway Proxy Service",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS for Streamlit frontend and external consumers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "auth_service"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("auth_service.main:app", host=AUTH_SERVICE_HOST, port=AUTH_SERVICE_PORT, reload=True)
