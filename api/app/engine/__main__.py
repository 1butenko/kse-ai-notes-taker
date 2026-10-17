"""Run the engine from the command line: `uv run python -m app.engine "question"`."""

import argparse

from langchain_core.messages import HumanMessage

from app.engine.agent import build_agent
from app.engine.config import BOOKS_DIR, EXAMPLE_QUERY
from app.engine.documents import book_paths, load_books, split_documents
from app.engine.vectorstore import build_vector_store


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the notes generation engine a question.")
    parser.add_argument("query", nargs="?", default=EXAMPLE_QUERY, help="Question to ask.")
    args = parser.parse_args()

    paths = book_paths()
    docs = load_books(paths)
    print(f"Loaded {len(docs)} pages from {len(paths)} PDFs in {BOOKS_DIR}")

    all_splits = split_documents(docs)
    print(f"Split into {len(all_splits)} chunks.")

    agent = build_agent(build_vector_store(all_splits))
    result = agent.invoke({"messages": [HumanMessage(content=args.query)]})

    for msg in result.get("messages", []):
        if msg.text:
            print(msg.text)


if __name__ == "__main__":
    main()
