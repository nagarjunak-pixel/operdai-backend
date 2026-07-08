"""KB Agent — RAG over the client's knowledge base using pgvector."""

from __future__ import annotations

import uuid
from datetime import UTC
from typing import Any

from sqlalchemy import select, text

from app.agents.base import BaseAgent
from app.agents.schemas import AgentStepResult, KBQueryInput, KBQueryOutput
from app.config import settings
from app.database import async_session_factory


class KBAgent(BaseAgent):
    name = "kb_agent"
    model = settings.llm_worker_model  # Haiku
    input_schema = KBQueryInput
    output_schema = KBQueryOutput
    temperature = 0.1

    system_prompt = """You are a knowledge base retrieval agent.

Given the search results from the client's knowledge base, your job is to:

1. Extract the most relevant FACTS that answer the user's query.
2. Cite the source for each fact (source_title and source_id).
3. Rate your confidence that the retrieved facts fully answer the query.
4. If no relevant facts are found, set confidence to 0.0 and return empty facts.

IMPORTANT: Only return facts that are DIRECTLY from the knowledge base.
DO NOT infer, extrapolate, or generate new information.
If the KB doesn't have the answer, say so honestly.

Search results:
{search_results}
"""

    async def search_kb(
        self, query: str, client_id: str, max_results: int = 5
    ) -> list[dict]:
        """
        Search the client's KB using pgvector similarity search.
        Falls back to keyword search if no embeddings exist yet.
        """
        from sqlalchemy import func

        from app.models.kb import KBChunk, KBDocument
        from app.services.embeddings import get_embedding

        async with async_session_factory() as db:
            # Check if any chunks with embeddings exist for this client
            chunk_count_result = await db.execute(
                select(func.count(KBChunk.id))
                .where(KBChunk.client_id == uuid.UUID(client_id), KBChunk.embedding != None)
            )
            chunk_count = chunk_count_result.scalar() or 0

            if chunk_count > 0:
                # Calculate query embedding
                query_vector = await get_embedding(query)

                # Perform pgvector similarity search (cosine distance)
                stmt = (
                    select(KBChunk, KBChunk.embedding.cosine_distance(query_vector).label("distance"))
                    .where(KBChunk.client_id == uuid.UUID(client_id))
                    .order_by(text("distance"))
                    .limit(max_results)
                )

                results = await db.execute(stmt)
                search_results = []
                for chunk, distance in results.all():
                    # Cosine distance ranges from 0 (closest) to 2 (farthest)
                    # Convert to a similarity score (1 - distance) or similar
                    relevance = 1.0 - (distance or 0.0)
                    relevance = max(0.0, min(1.0, relevance))

                    search_results.append({
                        "content": chunk.content,
                        "source_title": chunk.chunk_metadata.get("doc_title", "Unknown Doc"),
                        "source_id": str(chunk.document_id),
                        "doc_type": chunk.chunk_metadata.get("doc_type", "general"),
                        "relevance": relevance,
                    })

                # Inject Graph RAG semantic facts
                try:
                    from app.services.graph_rag import execute_graph_search
                    graph_facts = await execute_graph_search(uuid.UUID(client_id), query)
                    for fact in graph_facts:
                        search_results.append({
                            "content": fact,
                            "source_title": "Semantic Knowledge Graph",
                            "source_id": "graph-rag-entity-linking",
                            "doc_type": "knowledge_graph",
                            "relevance": 1.0,
                        })
                except Exception:
                    pass

                return search_results

            # Fallback: simple keyword search on documents if no chunks exist
            results = await db.execute(
                select(KBDocument)
                .where(
                    KBDocument.client_id == uuid.UUID(client_id),
                    KBDocument.is_active == True,  # noqa: E712
                )
                .limit(max_results)
            )
            docs = results.scalars().all()

            # Filter by query relevance (basic keyword match)
            search_results = []
            query_terms = set(query.lower().split())
            for doc in docs:
                content_lower = doc.content.lower()
                matches = sum(1 for term in query_terms if term in content_lower)
                if matches > 0 or len(docs) <= max_results:
                    search_results.append({
                        "content": doc.content[:800],  # Truncate for context window
                        "source_title": doc.title,
                        "source_id": str(doc.id),
                        "doc_type": doc.doc_type,
                        "relevance": matches / max(len(query_terms), 1),
                    })

            # Sort by relevance
            search_results.sort(key=lambda x: x["relevance"], reverse=True)
            search_results = search_results[:max_results]

            # Inject Graph RAG semantic facts
            try:
                from app.services.graph_rag import execute_graph_search
                graph_facts = await execute_graph_search(uuid.UUID(client_id), query)
                for fact in graph_facts:
                    search_results.append({
                        "content": fact,
                        "source_title": "Semantic Knowledge Graph",
                        "source_id": "graph-rag-entity-linking",
                        "doc_type": "knowledge_graph",
                        "relevance": 1.0,
                    })
            except Exception:
                pass

            return search_results

    async def run(
        self,
        input_data: KBQueryInput | dict,
        context: dict[str, Any] | None = None,
    ) -> tuple[KBQueryOutput | None, AgentStepResult]:
        """Override run to include KB search step before LLM call."""
        import time
        from datetime import datetime

        if isinstance(input_data, dict):
            input_data = KBQueryInput(**input_data)

        start = time.monotonic()

        # Step 1: Search KB
        search_results = await self.search_kb(
            query=input_data.query,
            client_id=input_data.client_id,
            max_results=input_data.max_results,
        )

        if not search_results:
            # No KB docs found — return empty result without LLM call
            output = KBQueryOutput(facts=[], confidence=0.0, query_understood=True)
            step = AgentStepResult(
                agent=self.name,
                input_data=input_data.model_dump(),
                output_data=output.model_dump(),
                model="none",
                tokens_in=0,
                tokens_out=0,
                cost_cents=0.0,
                duration_ms=int((time.monotonic() - start) * 1000),
                timestamp=datetime.now(UTC).isoformat(),
            )
            return output, step

        # Step 2: Use LLM to extract and structure facts from search results
        import json
        context = context or {}
        context["search_results"] = json.dumps(search_results, indent=2)

        return await super().run(input_data, context=context)
