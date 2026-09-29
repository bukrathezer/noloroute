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
cp .env.example .env            # then fill in DATABASE_URL, GOOGLE_PLACES_API_KEY and JWT_SECRET_KEY
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
   For public transport (`"travel_mode": "TRANSIT"`) the order is computed differently, see below.

## Trip dates, opening hours and weather
With a `start_date`, every day gets a date:

- Stops are only placed on days they are open long enough for a visit (Google opening hours,
  checked against 09:00–20:00); a stop closed on its day moves to the least busy day it is open
  on, or is dropped. Each stop shows that day's hours.
- Each day shows the weather from [Open-Meteo](https://open-meteo.com): a forecast up to 16 days
  ahead, beyond that the average of the same dates over the past 5 years. On rainy days outdoor
  stops (parks, viewpoints) move to a dry day when possible, and a rainy trip favours indoor
  sights. If the weather service is down, the plan is made without it.

## Public transport
With `"travel_mode": "TRANSIT"` every leg is either walked or taken by public transport, whichever
is better (`app/services/transit_planner.py`):

1. Two Route Matrix calls give walking and transit times between every pair of points (the
   accommodation and the day's stops), using that day's timetable at midday.
2. For each pair: walks of up to 10 minutes are always walked, and transit is chosen only when it
   saves at least 5 minutes (waiting, stairs and tickets make a close call not worth it).
3. The Routes API can't optimize the order of transit waypoints, so the day is ordered by our own
   travelling-salesman solver (`app/services/tsp.py`): Held-Karp dynamic programming finds the
   exact best order for up to 10 stops; longer days use nearest neighbour improved with 2-opt.
4. Each leg of the final order is routed again at the time the traveller would actually leave
   (09:00 local time, plus the travel and visits before it). That gives the street path and the
   lines to take (line, direction, stops); the plan also shows the option not taken, e.g. "on foot: 45 min".

Timetables are read in the city's time zone (stored per city). Google publishes transit only a few
weeks ahead, so for later trips the same weekday in the coming week is used. Where Google has no
transit data, every leg is walked and the plan says so. Transit plans cost the most Google calls
(two route matrices per day), so they are rate-limited per client.

## Editing a plan and finding the accommodation
- `POST /api/v1/routes/plan/remove-stop` drops a stop and re-routes only that day.
- `GET /api/v1/places/autocomplete` and `GET /api/v1/places/{place_id}` find a hotel or address
  by name through Google Places Autocomplete, proxied so the API key stays on the server. One
  session token covers all keystrokes and the final pick, which Google bills as a single session.

## Accounts and saved routes
Users register with an email and password (`POST /api/v1/auth/register`) or log in with the OAuth2
password flow (`POST /api/v1/auth/login`) and receive a JWT, sent as `Authorization: Bearer <token>`
(the **Authorize** button in `/docs` uses the same flow).

- Passwords are stored only as Argon2id hashes; login gives the same answer, with similar timing,
  for an unknown email and a wrong password.
- Tokens are HS256-signed with `JWT_SECRET_KEY` and expire after a week; the API refuses to start
  without a sufficiently long key.
- `POST/GET /api/v1/routes` and `GET/PUT/DELETE /api/v1/routes/{id}` save, list, open, update and
  delete the current user's routes; `DELETE /api/v1/auth/me` deletes the account (password required).
- Login, registration and place search are rate-limited per client (in memory, per instance). A saved route keeps a snapshot of the plan as shown (travel times, street
  paths), so reopening it needs no new Routes API calls; another user's route answers 404.

## Deployment
Every merge to `main` runs the GitHub Actions pipeline: lint, frontend build, tests against a
throwaway PostgreSQL, then deploy:

1. One Docker image is built with the API and the compiled web app (served from the same origin)
   and pushed to Artifact Registry.
2. Alembic migrations run as a Cloud Run job against Cloud SQL.
3. The new revision is deployed to Cloud Run and smoke-tested.

GitHub authenticates to Google Cloud with Workload Identity Federation (no stored keys);
secrets (database URL, Maps API key, JWT signing key) live in Secret Manager. POI ingestion runs on demand as
the `noloroute-ingest` Cloud Run job.

## Roadmap
- City insights (crowd levels, price analysis)
- Mobile app (React Native)
