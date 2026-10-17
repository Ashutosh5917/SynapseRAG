"""
Retriever setup and vector store configuration with disk persistence and append support.
"""

from __future__ import annotations
import json
import os
import logging
from typing import Optional

from langchain_core.documents import Document
from langchain_core.tools import create_retriever_tool
from langchain_community.vectorstores import FAISS
from src.llms.provider import get_embeddings

logger = logging.getLogger("src.rag.retriever_setup")
embeddings = get_embeddings()

# Directory for persisting FAISS vectorstore to disk
FAISS_INDEX_DIR = os.getenv("FAISS_INDEX_DIR", "faiss_index")
CATALOG_PATH = os.getenv("DOCUMENTS_CATALOG_PATH", "documents_catalog.json")

# Global in-memory reference to the active FAISS vectorstore
_faiss_vectorstore: Optional[FAISS] = None


def load_persistent_vectorstore() -> Optional[FAISS]:
    """Load existing FAISS index from disk if available."""
    global _faiss_vectorstore
    if os.path.exists(FAISS_INDEX_DIR) and os.path.exists(os.path.join(FAISS_INDEX_DIR, "index.faiss")):
        try:
            vectorstore = FAISS.load_local(
                FAISS_INDEX_DIR,
                embeddings,
                allow_dangerous_deserialization=True,
            )
            logger.info("Successfully loaded persistent FAISS vectorstore from %s", FAISS_INDEX_DIR)
            return vectorstore
        except Exception as e:
            logger.warning("Could not load local FAISS index from %s: %s", FAISS_INDEX_DIR, e)
    return None


def get_all_document_descriptions() -> str:
    """Aggregate descriptions for all uploaded documents."""
    descriptions = []
    if os.path.exists(CATALOG_PATH):
        try:
            with open(CATALOG_PATH, "r", encoding="utf-8") as f:
                catalog = json.load(f)
                for fname, desc in catalog.items():
                    descriptions.append(f"• {fname}: {desc}")
        except Exception as e:
            logger.warning("Error reading document catalog: %s", e)

    if not descriptions and os.path.exists("description.txt"):
        try:
            with open("description.txt", "r", encoding="utf-8") as f:
                descriptions.append(f.read().strip())
        except Exception:
            pass

    if descriptions:
        return "\n".join(descriptions)
    return "User uploaded business documents and knowledge resources."


def retriever_chain(chunks: list[Document]) -> bool:
    """
    Store documents in FAISS vector database.
    Appends to existing vectorstore and persists to disk.
    """
    global _faiss_vectorstore

    try:
        if _faiss_vectorstore is None:
            _faiss_vectorstore = load_persistent_vectorstore()

        if _faiss_vectorstore is not None:
            # Append new chunks to existing vectorstore (prevents overwriting previous docs)
            _faiss_vectorstore.add_documents(chunks)
            logger.info("Appended %d chunks to existing FAISS vector store", len(chunks))
        else:
            # Initialize brand new vectorstore
            _faiss_vectorstore = FAISS.from_documents(
                documents=chunks,
                embedding=embeddings,
            )
            logger.info("Created new FAISS vector store with %d chunks", len(chunks))

        # Persist to disk so data survives server restarts
        try:
            _faiss_vectorstore.save_local(FAISS_INDEX_DIR)
            logger.info("Saved FAISS vector store to disk at '%s'", FAISS_INDEX_DIR)
        except Exception as e:
            logger.error("Failed to save FAISS index to disk: %s", e)

        return True

    except Exception as e:
        logger.exception("Error storing documents in FAISS: %s", e)
        return False


def get_retriever():
    """
    Get or create a LangChain retriever tool connected to the FAISS vector store.
    """
    global _faiss_vectorstore

    try:
        if _faiss_vectorstore is None:
            _faiss_vectorstore = load_persistent_vectorstore()

        if _faiss_vectorstore is not None:
            retriever = _faiss_vectorstore.as_retriever(search_kwargs={"k": 4})
        else:
            # Placeholder initialization document
            from langchain_core.documents import Document as LangChainDocument
            dummy_doc = LangChainDocument(
                page_content="No documents have been uploaded yet. Please upload a document first.",
                metadata={"source": "initialization"},
            )
            _faiss_vectorstore = FAISS.from_documents(
                documents=[dummy_doc],
                embedding=embeddings,
            )
            retriever = _faiss_vectorstore.as_retriever(search_kwargs={"k": 2})

        all_descriptions = get_all_document_descriptions()

        retriever_tool = create_retriever_tool(
            retriever,
            "retriever_customer_uploaded_documents",
            f"Use this tool to search information in uploaded documents:\n{all_descriptions}\n"
            "Only use this tool when the query relates to these indexed topics.",
        )

        return retriever_tool

    except Exception as e:
        logger.exception("Error initializing retriever tool: %s", e)
        raise e
