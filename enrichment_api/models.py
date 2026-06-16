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

    @field_validator("force_refresh", mode="before")
    @classmethod
    def coerce_bool(cls, v) -> bool:
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes")
        return bool(v)


class EnrichRequest(ASINRequest):
    steps: list[str] = ["competitors", "keywords", "lqs", "enhance"]
