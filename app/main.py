from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1 import routes_auth, routes_city, routes_poi, routes_route
from app.core.config import get_settings
from app.services.routes_client import RoutesClient


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # One shared HTTP client for the Routes API (reuses connections across requests).
    # Without an API key, route planning falls back to straight-line estimates.
    api_key = get_settings().google_places_api_key
    app.state.routes_client = RoutesClient(api_key) if api_key else None
    yield
    if app.state.routes_client is not None:
        await app.state.routes_client.aclose()


app = FastAPI(title="NoloRoute API", version="0.1.0", lifespan=lifespan)
# Compress larger responses (the frontend bundle, route plans): Cloud Run doesn't do it for us.
app.add_middleware(GZipMiddleware, minimum_size=1024)

API_V1_PREFIX = "/api/v1"
for module in (routes_auth, routes_city, routes_poi, routes_route):
    app.include_router(module.router, prefix=API_V1_PREFIX)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


# The built web frontend (frontend/dist) is served from the same origin as the API, so one
# Cloud Run service hosts both and no CORS setup is needed. Mounted last: API routes win.
FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
