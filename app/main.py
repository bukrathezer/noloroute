from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

from app.api.v1 import routes_auth, routes_city, routes_places, routes_poi, routes_route, routes_suggestions
from app.core.config import get_settings
from app.services.events import EventsClient
from app.services.place_search import PlaceSearchClient
from app.services.routes_client import RoutesClient
from app.services.weather import WeatherClient

MIN_JWT_KEY_LENGTH = 32


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Fail at startup rather than on the first login if the token signing key is missing or weak.
    jwt_key = get_settings().jwt_secret_key
    if not jwt_key or len(jwt_key) < MIN_JWT_KEY_LENGTH:
        raise RuntimeError(f"JWT_SECRET_KEY must be set to a random string of at least {MIN_JWT_KEY_LENGTH} characters")

    # Shared HTTP clients for Google APIs (they reuse connections across requests). Without an
    # API key, route planning falls back to straight-line estimates and place search is off.
    api_key = get_settings().google_places_api_key
    app.state.routes_client = RoutesClient(api_key) if api_key else None
    app.state.place_search_client = PlaceSearchClient(api_key) if api_key else None
    app.state.weather_client = WeatherClient()  # Open-Meteo needs no key
    ticketmaster_key = (get_settings().ticketmaster_api_key or "").strip()
    app.state.events_client = EventsClient(ticketmaster_key) if ticketmaster_key else None
    yield
    clients = (
        app.state.routes_client,
        app.state.place_search_client,
        app.state.weather_client,
        app.state.events_client,
    )
    for client in clients:
        if client is not None:
            await client.aclose()


app = FastAPI(title="NoloRoute API", version="0.1.0", lifespan=lifespan)
# Compress larger responses (the frontend bundle, route plans): Cloud Run doesn't do it for us.
app.add_middleware(GZipMiddleware, minimum_size=1024)

API_V1_PREFIX = "/api/v1"
for module in (routes_auth, routes_city, routes_places, routes_poi, routes_route, routes_suggestions):
    app.include_router(module.router, prefix=API_V1_PREFIX)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


class FrontendFiles(StaticFiles):
    """The built frontend, with caching that lets visitors see a new deploy at once.

    Vite puts a content hash in every file name under assets/, so those can be cached for good.
    index.html keeps its name across deploys: browsers must check it each time (a cheap 304
    while it hasn't changed), or they keep running last week's bundle.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if Path(path).parts[:1] == ("assets",):  # path uses the OS's separators
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response


# The built web frontend (frontend/dist) is served from the same origin as the API, so one
# Cloud Run service hosts both and no CORS setup is needed. Mounted last: API routes win.
FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    app.mount("/", FrontendFiles(directory=FRONTEND_DIST, html=True), name="frontend")
