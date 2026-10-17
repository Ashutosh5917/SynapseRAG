"""
Real-time streaming handler for the Adaptive RAG pipeline.
Supports token-by-token streaming via SSE and WebSockets with intermediate agent step reporting
and grounded source citations (file names, page numbers, and web URLs).
"""

from __future__ import annotations
import json
import logging
from typing import AsyncGenerator, Dict, Any
from langchain_community.tools import TavilySearchResults
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.prompts import PromptTemplate

from src.config.settings import Config
from src.llms.openai import llm
from src.memory.chat_history_mongo import ChatHistory
from src.models.grade import Grade
from src.models.route_identifier import RouteIdentifier
from src.rag.reAct_agent import agent_executor
from src.rag.retriever_setup import get_retriever

logger = logging.getLogger("src.rag.stream_handler")
config = Config()


async def stream_adaptive_rag(query: str, session_id: str) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Executes the adaptive RAG workflow with real-time SSE / WebSocket streaming.
    Yields status updates during intermediate agent reasoning, followed by
    smooth token-by-token generation for the final answer and source citations.
    """
    try:
        # Step 1: Manage chat history
        chat_history = ChatHistory.get_session_history(session_id)
        await chat_history.add_message(HumanMessage(content=query))
        messages = await chat_history.get_messages()

        # Step 2: Route classification
        yield {
            "type": "status",
            "stage": "analyzing",
            "text": "Analyzing query and checking uploaded document context...",
        }

        retriever = get_retriever()
        candidate_docs = retriever.invoke(query)
        logger.info("Retrieved candidate context from vector store: %s", candidate_docs)

        llm_with_structured_output = llm.with_structured_output(RouteIdentifier)
        classify_prompt = PromptTemplate(
            template=config.prompt("classify_prompt"),
            input_variables=["question", "context"],
        )
        chain = classify_prompt | llm_with_structured_output
        route_result = await chain.ainvoke({"question": query, "context": candidate_docs})
        route = route_result.route
        logger.info("Query routing decision: %s", route)

        full_text = ""

        # Step 3: Branch execution based on route
        if route == "index":
            yield {
                "type": "status",
                "stage": "retrieving",
                "text": "Searching document vector store for relevant passages...",
            }
            agent_result = await agent_executor.ainvoke({"input": query})
            retrieved_context = agent_result.get("output", "")

            # Grade retrieved documents
            yield {
                "type": "status",
                "stage": "grading",
                "text": "Evaluating relevance of retrieved passages...",
            }
            grading_prompt = PromptTemplate(
                template=config.prompt("grading_prompt"),
                input_variables=["question", "context"],
            )
            llm_with_grade = llm.with_structured_output(Grade)
            chain_graded = grading_prompt | llm_with_grade
            grade_result = await chain_graded.ainvoke(
                {"question": query, "context": retrieved_context}
            )

            # If grade is 'no', trigger self-correction rewrite loop
            if grade_result.binary_score != "yes":
                yield {
                    "type": "status",
                    "stage": "rewriting",
                    "text": "Passages were incomplete. Reformulating query for better retrieval...",
                }
                rewrite_prompt = PromptTemplate(
                    template=config.prompt("rewrite_prompt"),
                    input_variables=["query"],
                )
                rewrite_chain = rewrite_prompt | llm
                rewrite_res = await rewrite_chain.ainvoke({"query": query})
                rewritten_query = rewrite_res.content
                logger.info("Rewritten query: %s", rewritten_query)

                # Re-retrieve with optimized search query
                agent_result = await agent_executor.ainvoke({"input": rewritten_query})
                retrieved_context = agent_result.get("output", "")

            # Stream token generation from document context
            yield {
                "type": "status",
                "stage": "generating",
                "text": "Synthesizing answer from retrieved documents...",
            }
            generate_prompt = PromptTemplate(
                template=config.prompt("generate_prompt"),
                input_variables=["context"],
            )
            generate_chain = generate_prompt | llm
            async for chunk in generate_chain.astream({"context": retrieved_context}):
                token = chunk.content if hasattr(chunk, "content") else str(chunk)
                if token:
                    full_text += token
                    yield {"type": "token", "content": token}

            # Extract source citations from candidate docs
            citations = []
            if isinstance(candidate_docs, list):
                seen_citations = set()
                for doc in candidate_docs:
                    if hasattr(doc, "metadata") and doc.metadata:
                        source = doc.metadata.get("source")
                        page = doc.metadata.get("page")
                        if source and source != "initialization":
                            cite_key = f"{source}:{page}"
                            if cite_key not in seen_citations:
                                seen_citations.add(cite_key)
                                page_str = f" (Page {page})" if page else ""
                                citations.append(f"- 📄 `{source}`{page_str}")

            if citations:
                citation_text = "\n\n**Grounded Sources:**\n" + "\n".join(citations)
                full_text += citation_text
                yield {"type": "token", "content": citation_text}

        elif route == "search":
            yield {
                "type": "status",
                "stage": "searching",
                "text": "Executing live web search via Tavily for real-time information...",
            }
            search_tool = TavilySearchResults()
            search_result = await search_tool.ainvoke(query)
            contents = [item["content"] for item in search_result if "content" in item]
            web_context = "\n\n".join(contents)

            yield {
                "type": "status",
                "stage": "generating",
                "text": "Synthesizing answer from live web search results...",
            }
            generate_prompt = PromptTemplate(
                template=config.prompt("generate_prompt"),
                input_variables=["context"],
            )
            generate_chain = generate_prompt | llm
            async for chunk in generate_chain.astream({"context": web_context}):
                token = chunk.content if hasattr(chunk, "content") else str(chunk)
                if token:
                    full_text += token
                    yield {"type": "token", "content": token}

            # Add web citations
            web_links = [
                f"- 🌐 [{item.get('url', 'Source')}]({item.get('url')})"
                for item in search_result
                if "url" in item
            ]
            if web_links:
                citation_text = "\n\n**Live Web Sources:**\n" + "\n".join(web_links[:3])
                full_text += citation_text
                yield {"type": "token", "content": citation_text}

        else:
            # General knowledge / conversational chit-chat
            yield {
                "type": "status",
                "stage": "generating",
                "text": "Responding using general intelligence...",
            }
            async for chunk in llm.astream(messages):
                token = chunk.content if hasattr(chunk, "content") else str(chunk)
                if token:
                    full_text += token
                    yield {"type": "token", "content": token}

        # Step 4: Persist AI response in chat history
        await chat_history.add_message(AIMessage(content=full_text))

        # Step 5: Send completion event
        yield {"type": "done", "content": full_text}

    except Exception as e:
        logger.exception("Error during streaming adaptive RAG: %s", e)
        yield {"type": "error", "message": str(e)}
