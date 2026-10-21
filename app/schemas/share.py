from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.route import RoutePlanResponse


class ShareRequest(BaseModel):
    plan: RoutePlanResponse = Field(description="A plan as returned by POST /routes/plan.")
    lang: Literal["tr", "en"] = Field(default="en", description="The language of the link preview.")


class ShareOut(BaseModel):
    id: str
    path: str = Field(description='Where the shared plan opens, e.g. "/p/aB3dE9xQ".')


class SharedPlanOut(BaseModel):
    id: str
    created_at: datetime
    plan: RoutePlanResponse
