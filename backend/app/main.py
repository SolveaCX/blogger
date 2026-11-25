from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.routing import Route

from app import models
from app.blog_mcp import MCP_PATH, mcp, mcp_app
from app.core.config import settings
from app.db import Base, engine
from app.routers import access_keys, assets, auth, categories, integration, meta, posts, sites, uploads, users
from app.schema_guard import ensure_schema


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.auto_create_tables:
        Base.metadata.create_all(bind=engine)
        ensure_schema()
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="Blogger API", version="0.1.0", lifespan=lifespan)

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


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/healthz")
async def api_healthz() -> dict[str, str]:
    return {"status": "ok"}


app.router.routes.append(Route(MCP_PATH, endpoint=mcp_app))
