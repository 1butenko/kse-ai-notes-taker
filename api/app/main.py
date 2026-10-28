from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import course_info, courses, files, notes, plans, syllabus, uploads

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def published_book_cors(request, call_next):
    """Normalize final wire headers only for successfully served book assets."""
    response = await call_next(request)
    if (
        request.method == "GET"
        and response.status_code in (200, 206)
        and response.headers.get("x-book-published") == "1"
    ):
        del response.headers["x-book-published"]
        response.headers["access-control-allow-origin"] = "*"
        if "access-control-allow-credentials" in response.headers:
            del response.headers["access-control-allow-credentials"]
        if "vary" in response.headers:
            values = [item.strip() for item in response.headers["vary"].split(",")]
            values = [item for item in values if item.lower() != "origin"]
            if values:
                response.headers["vary"] = ", ".join(values)
            else:
                del response.headers["vary"]
    return response


app.include_router(courses.router)
app.include_router(course_info.router)
app.include_router(uploads.router)
app.include_router(syllabus.router)
app.include_router(plans.router)
app.include_router(files.router)
app.include_router(notes.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}
