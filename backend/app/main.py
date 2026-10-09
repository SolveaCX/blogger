from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models
from app.core.config import settings
from app.db import Base, engine
from app.routers import access_keys, assets, auth, categories, integration, meta, posts, sites, uploads, users
from app.schema_guard import ensure_schema

app = FastAPI(title="Blogger API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(access_keys.router)
app.include_router(meta.router)
app.include_router(sites.router)
app.include_router(categories.router)
app.include_router(posts.router)
app.include_router(integration.router)
app.include_router(uploads.router)
app.include_router(assets.router)


@app.on_event("startup")
def create_tables() -> None:
    if settings.auto_create_tables:
        Base.metadata.create_all(bind=engine)
        ensure_schema()


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/healthz")
async def api_healthz() -> dict[str, str]:
    return {"status": "ok"}
