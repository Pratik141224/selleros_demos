from fastapi import FastAPI
from pydantic import BaseModel

from src.services.competitor_service import (
    find_competitors
)

app = FastAPI()


class CompetitorRequest(
    BaseModel
):
    asin: str


@app.get("/")
def health():

    return {
        "status": "healthy"
    }


@app.post(
    "/competitors"
)
def competitors(
    request: CompetitorRequest
):

    return find_competitors(
        request.asin
    )