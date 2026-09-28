# NoloRoute — Personalized Travel Itinerary Planner

[![CI](https://github.com/bukrathezer/noloroute/actions/workflows/ci.yml/badge.svg)](https://github.com/bukrathezer/noloroute/actions/workflows/ci.yml)

**Live demo:** https://noloroute-api-bymcvopkyq-ew.a.run.app · **API docs:** https://noloroute-api-bymcvopkyq-ew.a.run.app/docs

Generates a custom day-by-day travel route based on where you're staying,
how many days you have, and your budget.

## Why this project?
Most travel guide sites show the same static list to everyone. This app
personalizes the route to the traveler's accommodation, trip length, and
budget instead.

## MVP Scope
- Cities: Paris and Istanbul
- Input: accommodation location (lat/lng), trip length (days), budget
- Output: points of interest split into days, ordered to minimize travel distance/time
- User accounts with saved routes
- POI categories: museums, landmarks, parks, religious sites, viewpoints, markets

## Tech Stack
- **Backend:** Python, FastAPI, SQLAlchemy 2.0
- **Database:** PostgreSQL
- **POI data:** Google Places API (New)
- **Routing:** Google Routes API (waypoint optimization)
- **Frontend:** React + TypeScript (Vite), Leaflet with OpenStreetMap tiles, Turkish/English UI
- **CI/CD:** GitHub Actions
- **Deployment:** Google Cloud Platform — Cloud Run + Cloud SQL

## Local Development
Requires Python 3.12+ and a running PostgreSQL instance.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows (use `source .venv/bin/activate` on macOS/Linux)
pip install -r requirements.txt
cp .env.example .env            # then fill in DATABASE_URL and GOOGLE_PLACES_API_KEY
alembic upgrade head            # create/update DB tables
python -m scripts.ingest_places # load Paris & Istanbul POIs from Google Places (re-runnable)
uvicorn app.main:app --reload
```

Health check: `GET http://localhost:8000/health` · API docs: `http://localhost:8000/docs`

The web app lives in `frontend/` (Node 22+). Its dev server proxies `/api` to the API above:

```bash
cd frontend
npm install
npm run dev                     # http://localhost:5173
```

Run the tests (no database or Google API key needed):

```bash
pip install -r requirements-dev.txt
pytest
```

## How route planning works
`POST /api/v1/routes/plan` with a city, the accommodation's coordinates, trip length and an
optional budget returns a day-by-day plan:

```json
{"city_id": "paris", "accommodation": {"lat": 48.859, "lng": 2.347}, "duration_days": 2, "travel_mode": "WALK"}
```

1. **Select** — every POI gets a score: popularity (rating × log of review count), discounted by
   distance from the accommodation. The best POIs are picked greedily until the trip's time
   (8 h/day) or budget runs out; each pick lowers the score of its category to keep days varied.
2. **Split into days** — a *sweep*: stops are sorted by direction from the accommodation and the
   circle is cut into slices of roughly equal time, so each day heads one way.
3. **Order each day** — the Google Routes API optimizes the visiting order of the
   accommodation → stops → accommodation loop and returns real travel times. If Google is
   unavailable, a nearest-neighbour order with straight-line estimates is used instead.

## Deployment
Every merge to `main` runs the GitHub Actions pipeline: lint, frontend build, tests against a
throwaway PostgreSQL, then deploy:

1. One Docker image is built with the API and the compiled web app (served from the same origin)
   and pushed to Artifact Registry.
2. Alembic migrations run as a Cloud Run job against Cloud SQL.
3. The new revision is deployed to Cloud Run and smoke-tested.

GitHub authenticates to Google Cloud with Workload Identity Federation (no stored keys);
secrets (database URL, Maps API key) live in Secret Manager. POI ingestion runs on demand as
the `noloroute-ingest` Cloud Run job.

## Roadmap
- Weather-aware route suggestions
- City insights (crowd levels, price analysis)
- Mobile app (React Native)
