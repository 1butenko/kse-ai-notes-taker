import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import courses, files, notes, plans, syllabus, uploads
from app.session import SessionMiddleware, end_session, sweep_forever

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings.uploads_root.mkdir(parents=True, exist_ok=True)
    if not settings.sessions:
        yield
        return
    sweeper = asyncio.create_task(
        sweep_forever(settings.uploads_root, settings.session_ttl_minutes * 60)
    )
    yield
    sweeper.cancel()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(SessionMiddleware, enabled=settings.sessions)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(courses.router)
app.include_router(uploads.router)
app.include_router(syllabus.router)
app.include_router(plans.router)
app.include_router(files.router)
app.include_router(notes.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}


@app.post("/session/end", status_code=204)
def end(session: str) -> None:
    """Called by the browser when its tab closes or reloads: the demo forgets its files."""
    if settings.sessions:
        end_session(settings.uploads_root, session)
