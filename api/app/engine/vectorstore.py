from langchain_core.documents import Document
from langchain_core.vectorstores import InMemoryVectorStore, VectorStore

from app.engine.llm import build_embeddings


def build_vector_store(all_splits: list[Document]) -> VectorStore:
    """Index the chunks in memory (stand-in for Amazon S3 Vectors while API calls are disabled)."""
    vector_store = InMemoryVectorStore(build_embeddings())
    if all_splits:
        vector_store.add_documents(documents=all_splits)
    return vector_store
