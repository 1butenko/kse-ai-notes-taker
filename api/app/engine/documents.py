from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.engine.config import BOOKS_DIR, CHUNK_OVERLAP, CHUNK_SIZE


def load_documents(pdf_path: str | Path) -> list[Document]:
    loader = PyPDFLoader(str(pdf_path))
    return loader.load()


def book_paths(books_dir: Path = BOOKS_DIR) -> list[Path]:
    return sorted(books_dir.glob("*.pdf"))


def load_books(paths: list[Path] | None = None) -> list[Document]:
    docs: list[Document] = []
    for path in paths if paths is not None else book_paths():
        docs.extend(load_documents(path))
    return docs


def split_documents(docs: list[Document]) -> list[Document]:
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )
    return text_splitter.split_documents(docs)
