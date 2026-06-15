"""
marketplaces/base_lqs.py

Shared contracts for all marketplace-specific LQS scorers.
Future marketplace scorers (flipkart, myntra, meesho) implement BaseLQSScorer
and return LQSOutput — no other code in the system needs to change.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ListingInput:
    """Normalised listing payload accepted by every marketplace scorer."""

    # Core content — title is the only hard requirement
    title: str
    description: str = ""
    bullets: list[str] = field(default_factory=list)
    backend_keywords: str = ""
    browse_node: str = ""
    brand: str = ""
    category: str = ""
    platform: str = "amazon"
    aplus_content: str = ""
    images: list[dict] = field(default_factory=list)
    attributes: dict = field(default_factory=dict)
    qa_pairs: list[dict] = field(default_factory=list)
    review_summary: dict = field(default_factory=dict)

    # Keyword signals — if absent, the scorer will auto-extract from title/backend_kw
    primary_keyword: str = ""
    secondary_keywords: list[str] = field(default_factory=list)

    # Optional bridge from the existing Python ML pipeline (pipeline.py → predict_lqs).
    # When provided, this value is used directly as lqs_score in the output.
    # When absent, the scorer falls back to a content-quality heuristic.
    lqs_score_override: int | None = None

    def validate(self) -> None:
        if not self.title or len(self.title.strip()) < 2:
            raise ValueError("ListingInput.title must be at least 2 characters")


@dataclass
class LQSOutput:
    """Standard output from any marketplace LQS scorer."""

    scores: dict           # a9_compliance, rufus_readiness, lqs_score, overall
    dimension_breakdown: dict  # {"a9": {...}, "rufus": {...}}
    flags: list[str]
    fix_priority: list[dict]   # [{issue, dimension, impact_score, fix_suggestion}]
    projected_ctr_range: str   # e.g. "2.8–4.2%"
    gmv_impact_inr: str        # e.g. "₹13,875–₹18,354/month"

    def to_dict(self) -> dict:
        return {
            "scores": self.scores,
            "dimension_breakdown": self.dimension_breakdown,
            "flags": self.flags,
            "fix_priority": self.fix_priority,
            "projected_ctr_range": self.projected_ctr_range,
            "gmv_impact_inr": self.gmv_impact_inr,
        }


class BaseLQSScorer(ABC):
    """
    Abstract base for all marketplace-specific LQS scorers.

    Contract:
        scorer = ConcreteMarketplaceLQSScorer()
        output: LQSOutput = scorer.score(listing_input)

    Each marketplace subclass runs its own Pass 1 (deterministic) and
    Pass 2 (LLM) under the hood; the output schema is always LQSOutput.
    """

    platform: str = ""

    @abstractmethod
    def score(self, listing: ListingInput) -> LQSOutput:
        """Score a listing and return a fully-populated LQSOutput."""
        ...
