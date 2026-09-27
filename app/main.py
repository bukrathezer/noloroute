from fastapi import FastAPI

from app.api.v1 import routes_auth, routes_city, routes_poi, routes_route

app = FastAPI(title="NoloRoute API", version="0.1.0")

API_V1_PREFIX = "/api/v1"
for module in (routes_auth, routes_city, routes_poi, routes_route):
    app.include_router(module.router, prefix=API_V1_PREFIX)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}
