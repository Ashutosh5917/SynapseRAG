"""
Document upload and processing module with metadata preservation and document cataloging.
"""

from __future__ import annotations
import json
import os
import tempfile
import logging
from datetime import datetime

from fastapi import UploadFile, File, HTTPException
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.rag.retriever_setup import retriever_chain, CATALOG_PATH
from src.tools.common_tools import enhance_description_with_llm

logger = logging.getLogger("src.rag.document_upload")


def update_document_catalog(filename: str, description: str, chunk_count: int):
    """Save document metadata to the persistent JSON catalog."""
    catalog = {}
    if os.path.exists(CATALOG_PATH):
        try:
            with open(CATALOG_PATH, "r", encoding="utf-8") as f:
                catalog = json.load(f)
        except Exception as e:
            logger.warning("Could not read document catalog: %s", e)

    catalog[filename] = {
        "description": description,
        "chunks": chunk_count,
        "uploaded_at": datetime.utcnow().isoformat(),
    }

    try:
        with open(CATALOG_PATH, "w", encoding="utf-8") as f:
            json.dump(catalog, f, indent=2)
        logger.info("Updated document catalog with %s (%d chunks)", filename, chunk_count)
    except Exception as e:
        logger.error("Failed to write document catalog: %s", e)


def documents(description: str, file: UploadFile = File(...)):
    """
    Process and upload a document for RAG.
    Validates file format, chunks with source metadata, indexes into vectorstore,
    and updates the persistent document catalog.
    """
    filename = file.filename
    if not filename.endswith(".pdf") and not filename.endswith(".txt"):
        raise HTTPException(
            status_code=400,
            detail="Unsupported format: Only .pdf and .txt files are supported for indexing.",
        )

    file_bytes = file.file.read()

    with tempfile.NamedTemporaryFile(
        delete=False,
        suffix=os.path.splitext(filename)[1],
    ) as tmp_file:
        tmp_file.write(file_bytes)
        tmp_path = tmp_file.name

    try:
        if filename.endswith(".pdf"):
            loader = PyPDFLoader(tmp_path)
        else:
            loader = TextLoader(tmp_path, encoding="utf-8")
        docs = loader.load()
    except Exception as e:
        logger.exception("Error reading file %s: %s", filename, e)
        raise HTTPException(
            status_code=500,
            detail=f"Error reading and loading document: {e}",
        )
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    # Enhance description using LLM
    description_llm = enhance_description_with_llm(description)

    # Save description.txt for backward compatibility
    with open("description.txt", "w", encoding="utf-8") as f:
        f.write(description_llm)

    # Split documents into chunks with rich source metadata
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=150,
    )
    chunks = splitter.split_documents(docs)

    # Ensure every chunk carries exact filename and page metadata
    for i, chunk in enumerate(chunks):
        chunk.metadata["source"] = filename
        if "page" not in chunk.metadata:
            chunk.metadata["page"] = i + 1

    # Ingest into vector store
    success = retriever_chain(chunks)

    if success:
        # Update persistent catalog
        update_document_catalog(filename, description_llm, len(chunks))

    return success
