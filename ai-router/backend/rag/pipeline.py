"""
RAG is shaped differently from a normal chat route: it's a two-stage
pipeline (retrieve, then generate), not a single provider call. This
module wires Cohere's embed + rerank against a pluggable vector store,
then hands the retrieved context to Gemini (falling back to Groq) for
the final answer.

Swap `VectorStore` for a real one (Chroma, Pinecone, pgvector, etc.) —
this in-memory version exists so the pipeline runs end-to-end without
extra infra for testing.
"""
import numpy as np
from config import RAG_ROUTE
from providers.cohere_provider import CohereProvider
from providers.gemini_provider import GeminiProvider
from providers.groq_provider import GroqProvider
from utils.errors import ProviderError


class VectorStore:
    """Minimal in-memory store. Replace with a real vector DB for production."""

    def __init__(self):
        self.texts: list[str] = []
        self.vectors: list[list[float]] = []

    def add(self, texts: list[str], vectors: list[list[float]]):
        self.texts.extend(texts)
        self.vectors.extend(vectors)

    def search(self, query_vector: list[float], top_k: int = 10) -> list[str]:
        if not self.vectors:
            return []
        mat = np.array(self.vectors)
        q = np.array(query_vector)
        sims = mat @ q / (np.linalg.norm(mat, axis=1) * np.linalg.norm(q) + 1e-8)
        top_idx = np.argsort(-sims)[:top_k]
        return [self.texts[i] for i in top_idx]


class RAGPipeline:
    def __init__(self, store: VectorStore = None):
        self.cohere = CohereProvider()
        self.gemini = GeminiProvider()
        self.groq = GroqProvider()
        self.store = store or VectorStore()

    def ingest(self, chunks: list[str]):
        """Embed and store document chunks (e.g. lecture notes split into paragraphs)."""
        vectors = self.cohere.embed(chunks, input_type="search_document")
        self.store.add(chunks, vectors)

    def answer(self, question: str, top_k: int = 10, top_n: int = 4) -> dict:
        # 1. Embed the query and pull candidates from the vector store.
        query_vec = self.cohere.embed([question], input_type="search_query")[0]
        candidates = self.store.search(query_vec, top_k=top_k)

        if not candidates:
            return {"answer": "No relevant content found in the knowledge base.", "sources": []}

        # 2. Rerank candidates for precision.
        reranked = self.cohere.rerank(question, candidates, top_n=top_n)
        context_chunks = [candidates[r["index"]] for r in reranked]
        context = "\n\n---\n\n".join(context_chunks)

        # 3. Generate the answer from the retrieved context.
        messages = [
            {
                "role": "system",
                "content": (
                    "Answer the question using only the provided context. "
                    "If the context doesn't contain the answer, say so."
                ),
            },
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
        ]

        try:
            answer = self.gemini.chat(messages)
            provider_used = RAG_ROUTE["generation"]
        except ProviderError:
            answer = self.groq.chat(messages)
            provider_used = RAG_ROUTE["generation_fallback"]

        return {"answer": answer, "sources": context_chunks, "provider": provider_used}
