from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[2]

# Course books (PDF) to index; every PDF in this folder is loaded.
BOOKS_DIR = API_ROOT / "data" / "books"
# Generated Quarto notes.
QMD_OUTPUT_DIR = API_ROOT / "output" / "qmd"
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

# Same dimension as voyage-4, the embedding model the engine will use once API calls are wired.
EMBEDDING_DIMENSION = 1024

CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200
SEARCH_K = 4
MAX_CONCURRENT_ANALYSTS = 3

EXAMPLE_QUERY = "Give me the definiton of eigenvalues and eigenvectors. Give me an example."
