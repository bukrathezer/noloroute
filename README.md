# NoloRoute — Personalized Travel Itinerary Planner

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
- **CI/CD:** GitHub Actions
- **Deployment:** Google Cloud Platform — Cloud Run + Cloud SQL

## Local Development
Requires Python 3.12+ and a running PostgreSQL instance.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows (use `source .venv/bin/activate` on macOS/Linux)
pip install -r requirements.txt
cp .env.example .env            # then fill in DATABASE_URL and GOOGLE_PLACES_API_KEY
uvicorn app.main:app --reload
```

Health check: `GET http://localhost:8000/health` · API docs: `http://localhost:8000/docs`

## Roadmap
- Weather-aware route suggestions
- City insights (crowd levels, price analysis)
- Mobile app (React Native)
