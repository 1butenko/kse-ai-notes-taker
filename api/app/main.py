from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import current_principal, owned_course
from app.config import get_settings
from app.routers import (
    agent,
    auth,
    course_info,
    courses,
    files,
    lecture_notes,
    plans,
    syllabus,
    uploads,
)

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


# Every route needs a signed-in teacher or a service (app/auth.py); course routes also check
# that the course is the teacher's, per route or, where every route has `{course}`, per router.
signed_in = [Depends(current_principal)]
own_course = [*signed_in, Depends(owned_course)]

app.include_router(auth.router, dependencies=signed_in)
app.include_router(courses.router, dependencies=signed_in)
app.include_router(course_info.router, dependencies=signed_in)
app.include_router(uploads.router, dependencies=signed_in)
app.include_router(syllabus.router, dependencies=signed_in)
app.include_router(plans.router, dependencies=own_course)
app.include_router(files.router, dependencies=signed_in)
app.include_router(agent.router, dependencies=own_course)
app.include_router(lecture_notes.router, dependencies=signed_in)
# Published lecture-notes pages are public (an unguessable run id), for the sandboxed iframe.
app.include_router(lecture_notes.site_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}
