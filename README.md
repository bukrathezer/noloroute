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
- Cities: Paris, Istanbul and 30 popular cities abroad (`scripts/city_catalog.py`)
- Input: accommodation location (lat/lng), trip length (days), budget
- Output: points of interest split into days, ordered to minimize travel distance/time
- User accounts with saved routes
- POI categories: museums, landmarks, parks, religious sites, viewpoints, markets

## Tech Stack
- **Backend:** Python, FastAPI, SQLAlchemy 2.0
- **Database:** PostgreSQL
- **POI data:** Google Places API (New); short descriptions from Wikipedia, matched through Wikidata
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
python -m scripts.ingest_places # load Paris & Istanbul POIs from Google Places (re-runnable; see below)
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
2. **Split into days** — *route first, split second*: one round trip through all chosen stops
   (the TSP solver below, on straight-line distances) is cut into consecutive stretches of roughly
   equal time, trying every stop as the start and keeping the cut with the least total distance.
   Neighbouring sights sit next to each other on a round trip, so a cluster stays on one day.
3. **Fill days with room** — selection reserves a fixed travel time per stop, which is too much
   where sights are close together. Each day's time is re-estimated from its real distances, and
   while it has room, the best unchosen sight that still fits (popularity, less for the detour and
   for categories the trip already has) is inserted where it lengthens the day least. This happens
   before routing, so it costs no API calls; on 80 sample plans it took the average day from 7 h
   to 8 h, with no day under 7 h.
4. **Order each day** — the Google Routes API optimizes the visiting order of the
   accommodation → stops → accommodation loop and returns real travel times. If Google is
   unavailable, a nearest-neighbour order with straight-line estimates is used instead.
   For public transport (`"travel_mode": "TRANSIT"`) the order is computed differently, see below.
5. **Keep days realistic** — with real travel times a day may run a little over 8 hours, but not
   past 8½: until it fits, its least popular stop is dropped and the day re-routed (at most three
   times, as each costs a Google request; transit days re-use their travel-time matrices for free).
   The plan lists what was left out.

## Visit times and entry prices
Google Places has neither, so `scripts/sight_details.py` sets them during ingestion:

- **Visit time** comes from the place's Google type (a statue 10 min, a square 20, a palace 90),
  scaled by fame: every 10× more reviews adds 30%, between ×0.75 and ×1.5, since well-known
  places tend to be bigger and busier.
- **Entry price** is zero for types that are free to visit (parks, squares, bridges, mosques,
  churches, markets) and unknown otherwise.
- The **most visited sights** have hand-checked visit times and prices, each with its source.
  Paris uses the adult price for visitors from outside the EU (several museums raised it in
  2026), Istanbul the price for Turkish citizens; plans say which, and when prices were checked.
  Google entries that are part of another sight (the Louvre Pyramid, Napoleon's Tomb) are
  left out so a plan never visits and pays for the same place twice.

## Place descriptions
Each stop shows a sentence or two about the place from Wikipedia (Turkish when there is a Turkish
article, English otherwise) with a link to the article. `scripts/describe_pois.py` looks each place
up once, for free, and the ingestion runs it for the places it adds:

- The place is matched to its **Wikidata** item. English Wikipedia is searched for its name, and an
  article counts if it lies near the place (600 m; parks, viewpoints and districts 1-1.5 km).
  Failing that, the Wikidata items around the place are compared with its name, which finds
  articles under another name ("Kariye Mosque" is "The Chora") or in Turkish only.
- Names must agree word for word, and words for the kind of place must not contradict each other
  or the place's category: "Jardin du Luxembourg" is not the Luxembourg Palace, "Galata Tower" is
  not the Galata neighbourhood, and the gardens along Avenue Foch are not the avenue (a bare name
  only counts when the item's description says what the place is).
- The text is the article's first sentence (two if the first is short), without the parentheses.
  Wikipedia's text is CC BY-SA 4.0, so plans link every description to its article and say that
  it was shortened.

```bash
python -m scripts.describe_pois                            # places not looked up yet
python -m scripts.describe_pois --city paris --dry-run     # print the matches only
```

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

## Places to eat, nightlife and events
Meals and evenings are not planned into the route (when and where to eat or go out is personal);
instead each day can list suggestions, looked up only when the traveller asks
(`app/services/suggestions.py`, `app/services/events.py`):

- **Places to eat along the route** (`POST /api/v1/suggestions/food`): around two stops a third
  and two thirds of the way through the day, the most popular restaurants, bakeries and dessert
  shops within 700 m (no fast food or takeaways), rated 4.2+ with 200+ reviews and open for at
  least an hour at lunch or dinner time that day.
- **Nightlife for the evening** (`POST /api/v1/suggestions/nightlife`): near the accommodation,
  and near the day's last stop if it is 1.5 km+ away, bars, pubs, clubs, live music and comedy
  within 1 km whose main type is one of these (not restaurants that also have a bar), rated 4.2+
  with 100+ reviews and open for at least an hour between 20:00 and 02:00 that night.
- **Events that day** (`POST /api/v1/suggestions/events`, trip dates only): concerts, sports and
  theatre starting that day within 15 km of the accommodation, from the Ticketmaster Discovery
  API (Google has no event data). The 8 most relevant are kept and put in order of time, several
  showings of one show merged. Timed-entry attraction tickets ("Miscellaneous") are left out, or
  they fill the list with half-hourly London Eye slots. Coverage varies a lot: on a Saturday in
  October 2026 it listed 129 events around London, 26 around Istanbul (Biletix is part of
  Ticketmaster), 1 in Rome and none in Paris. Needs `TICKETMASTER_API_KEY` (free, 5,000 calls a day).
- Each food or nightlife lookup is one Nearby Search per anchor. Places are ranked by popularity, listed under the
  nearer anchor, and a chain appears once, with its best branch. Each shows its category, rating,
  price level, that day's hours, distance and a Google Maps link.
- Lookups are rate-limited per client (food and nightlife together) and never stored: Google's
  terms allow storing only place IDs.

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

## Cities and keeping them fresh
Sights come from Google Places Nearby Search (`scripts/ingest_places.py`), which costs about $35
per 1,000 requests and returns at most 20 places per request, so the search is **adaptive**:

- One request per cell asks for every sightseeing type at once. The search starts with a single
  cell over the whole city; a cell is split in four only while its 20 results are all popular
  enough to be among the city's 100 best found so far. If even the 20th falls short, nothing the
  cell didn't return can make the list, so it isn't searched further. Big cells go first, so the
  bar rises quickly.
- On the cached Paris and Istanbul data this finds nearly all of the 100-150 most popular sights
  with 45-60 requests instead of the fixed grid's 94 and 184; a pilot in Rome and Kyoto took 95
  and 75. The fixed grid over all 32 cities would have cost about $290 per pass.
- Cities abroad are found by name with free calls (Text Search returning only the place ID, then
  Place Details' Essentials fields) and searched within 12 km of that centre. Google's own city
  viewports proved unreliable (country-sized for one city, 200 m for another).
- A run can be given a request budget (`--max-requests`); a city whose search doesn't finish
  within it is not saved, so a half-searched city never loses its places.
- **Monthly refresh:** `--refresh` updates the cities with the oldest data (at least 25 days old)
  for as long as their last run's request count fits the budget. Run monthly with a budget of 900
  it stays inside the free 1,000 Nearby requests a month, and every city is refreshed every few
  months at no cost.

```bash
python -m scripts.ingest_places --city rome --city kyoto --max-requests 200
python -m scripts.ingest_places --refresh --max-requests 900
```

## Deployment
Every merge to `main` runs the GitHub Actions pipeline: lint, frontend build, tests against a
throwaway PostgreSQL, then deploy:

1. One Docker image is built with the API and the compiled web app (served from the same origin)
   and pushed to Artifact Registry.
2. Alembic migrations run as a Cloud Run job against Cloud SQL.
3. The new revision is deployed to Cloud Run and smoke-tested.

GitHub authenticates to Google Cloud with Workload Identity Federation (no stored keys);
secrets (database URL, Maps API key, JWT signing key) live in Secret Manager. POI ingestion is the
`noloroute-ingest` Cloud Run job: by default the monthly refresh above, or with its own arguments
for adding cities.

## Roadmap
- City insights (crowd levels, price analysis)
- Mobile app (React Native)
