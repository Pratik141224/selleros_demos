from __future__ import annotations

from pydantic import BaseModel, field_validator


class ASINRequest(BaseModel):
    asin: str
    marketplace: str = "amazon"
    country: str = "IN"
    force_refresh: bool = False

    @field_validator("asin")
    @classmethod
    def normalise_asin(cls, v: str) -> str:
        return v.strip().upper()


class EnrichRequest(ASINRequest):
    steps: list[str] = ["competitors", "keywords", "lqs", "enhance"]
