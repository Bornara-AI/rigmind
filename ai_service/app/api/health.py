from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["ops"])


class HealthResponse(BaseModel):
    status: Literal["ok"]


@router.get("/health")
async def health() -> HealthResponse:
    return HealthResponse(status="ok")
