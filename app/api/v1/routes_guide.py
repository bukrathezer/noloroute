from typing import Literal

from fastapi import APIRouter, Response

from app.schemas.guide import BestMonthOut, BestPickOut, GuideCityOut, GuideOut
from app.services.travel_guide import CONTINENTS, load_guide

router = APIRouter(prefix="/guide", tags=["guide"])


@router.get("", response_model=GuideOut)
def get_guide(response: Response, lang: Literal["tr", "en"] = "en") -> GuideOut:
    """The travel guide in one language: each city month by month, and each month's best cities.

    The texts change only with a new release, so browsers may keep them for an hour.
    """
    guide = load_guide(lang)
    response.headers["Cache-Control"] = "public, max-age=3600"
    return GuideOut(
        lang=lang,
        continents=list(CONTINENTS),
        cities=[
            GuideCityOut(
                id=c.id, country_code=c.country_code, continent=c.continent, months=list(c.months), note=c.note
            )
            for c in guide.cities
        ],
        best=[
            BestMonthOut(month=month, picks=[BestPickOut(city_id=p.city_id, text=p.text) for p in picks])
            for month, picks in enumerate(guide.best, start=1)
        ],
    )
