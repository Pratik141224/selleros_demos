"""
marketplaces/amazon/rufus_scorer.py

Rufus Readiness Scorer — Pass 2 (LLM evaluated).

Sends listing content + A9 flags to the LLM with the rubric from
shared/prompts/d1_rufus_lqs_v1.txt and parses the structured response.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from shared.llm_client import call_json

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent.parent / "shared" / "prompts" / "d1_rufus_lqs_v1.txt"

_RUFUS_SYSTEM: str = ""


def _load_system_prompt() -> str:
    global _RUFUS_SYSTEM
    if not _RUFUS_SYSTEM:
        _RUFUS_SYSTEM = _PROMPT_PATH.read_text(encoding="utf-8")
    return _RUFUS_SYSTEM


# ── result type ────────────────────────────────────────────────────────────────

@dataclass
class RufusResult:
    score: int
    breakdown: dict[str, int]  # dimension_name → 0-100 score
    fix_priority: list[dict] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


# ── input builder ──────────────────────────────────────────────────────────────

def _build_user_message(
    title: str,
    bullets: list[str],
    description: str,
    qa_pairs: list[dict],
    review_summary: dict,
    aplus_content: str,
    a9_flags: list[str],
) -> str:
    bullets_text = "\n".join(
        f"  {i + 1}. {b}" for i, b in enumerate(bullets) if b.strip()
    ) or "  (none)"

    qa_text = ""
    if qa_pairs:
        qa_lines = []
        for qa in qa_pairs[:10]:
            q = qa.get("question", "")
            a = qa.get("answer", "")
            if q:
                qa_lines.append(f"  Q: {q}")
                if a:
                    qa_lines.append(f"  A: {a}")
        qa_text = "\n".join(qa_lines)

    review_text = ""
    if review_summary:
        avg = review_summary.get("avg_rating", "N/A")
        cnt = review_summary.get("review_count", "N/A")
        negs = review_summary.get("top_negatives", [])
        neg_str = "; ".join(negs[:3]) if negs else "none provided"
        review_text = f"avg_rating={avg}, review_count={cnt}, top_negatives=[{neg_str}]"

    parts = [
        f'TITLE:\n"{title}"',
        f"BULLETS:\n{bullets_text}",
    ]
    if description.strip():
        parts.append(f"DESCRIPTION (first 500 chars):\n{description[:500]}")
    if aplus_content.strip():
        parts.append(f"A+ CONTENT (first 300 chars):\n{aplus_content[:300]}")
    if qa_text:
        parts.append(f"Q&A PAIRS:\n{qa_text}")
    if review_text:
        parts.append(f"REVIEW SUMMARY:\n{review_text}")
    else:
        parts.append("REVIEW SUMMARY: not provided — score review_alignment as 50")
    if a9_flags:
        parts.append(f"A9 FLAGS FROM PASS 1 (context only — do not re-score A9):\n{', '.join(a9_flags)}")

    return "\n\n".join(parts)


# ── response parser ────────────────────────────────────────────────────────────

_DIM_KEYS = [
    "intent_coverage",
    "use_case_specificity",
    "objection_handling",
    "persona_clarity",
    "faq_readiness",
    "semantic_depth",
    "review_alignment",
    "conversational_naturalness",
]

_DIM_WEIGHTS = {
    "intent_coverage":            0.20,
    "use_case_specificity":       0.15,
    "objection_handling":         0.15,
    "persona_clarity":            0.10,
    "faq_readiness":              0.15,
    "semantic_depth":             0.10,
    "review_alignment":           0.05,
    "conversational_naturalness": 0.10,
}


def _parse_response(raw: dict) -> RufusResult:
    dims_raw = raw.get("dimensions", {})

    breakdown: dict[str, int] = {}
    all_flags: list[str] = []
    for key in _DIM_KEYS:
        dim_data = dims_raw.get(key, {})
        score = int(dim_data.get("score", 0))
        breakdown[key] = max(0, min(100, score))
        all_flags.extend(dim_data.get("flags", []))

    # Recompute rufus_score from dimension scores using spec weights
    # (don't blindly trust the model's arithmetic)
    computed = sum(breakdown[k] * _DIM_WEIGHTS[k] for k in _DIM_KEYS)
    rufus_score = max(0, min(100, int(round(computed))))

    # Prefer the model's reported score if it's close; fall back to computed
    model_score = raw.get("rufus_score", -1)
    if isinstance(model_score, int) and abs(model_score - rufus_score) <= 3:
        rufus_score = model_score

    fix_priority = raw.get("fix_priority", [])
    if not isinstance(fix_priority, list):
        fix_priority = []

    seen: set[str] = set()
    flags = [f for f in all_flags if not (f in seen or seen.add(f))]  # type: ignore[func-returns-value]

    return RufusResult(
        score=rufus_score,
        breakdown=breakdown,
        fix_priority=fix_priority,
        flags=flags,
    )


# ── slim output override appended to user message ─────────────────────────────

_SLIM_OVERRIDE = (
    "\n\nOUTPUT OVERRIDE — scores only, no fix_priority, no flags, no top_fix:\n"
    '{"rufus_score":0,"dimensions":{'
    + ",".join(f'"{k}":{{"score":0}}' for k in _DIM_KEYS)
    + "}}"
)

_SLIM_MAX_TOKENS = 350  # 8 ints + keys + braces ≈ 200 tokens, 350 gives headroom


def _parse_slim_response(raw: dict) -> RufusResult:
    """Parse the condensed scores-only response from score_rufus_slim."""
    dims_raw = raw.get("dimensions", {})
    breakdown: dict[str, int] = {}
    for key in _DIM_KEYS:
        entry = dims_raw.get(key, {})
        score = int(entry.get("score", 0) if isinstance(entry, dict) else (entry or 0))
        breakdown[key] = max(0, min(100, score))

    computed = sum(breakdown[k] * _DIM_WEIGHTS[k] for k in _DIM_KEYS)
    rufus_score = max(0, min(100, int(round(computed))))

    model_score = raw.get("rufus_score", -1)
    if isinstance(model_score, int) and abs(model_score - rufus_score) <= 3:
        rufus_score = model_score

    return RufusResult(score=rufus_score, breakdown=breakdown, fix_priority=[], flags=[])


# ── public entry-points ────────────────────────────────────────────────────────

def score_rufus_slim(
    title: str,
    bullets: list[str],
    description: str = "",
    qa_pairs: list[dict] | None = None,
    review_summary: dict | None = None,
    aplus_content: str = "",
    a9_flags: list[str] | None = None,
) -> RufusResult:
    """
    Scores-only Rufus call — same rubric, condensed JSON output.
    Skips fix_priority, top_fix, and flags to save ~400 output tokens per call.
    Use for competitors where scores are needed but actionable fixes are not.
    """
    system = _load_system_prompt()
    user = _build_user_message(
        title=title, bullets=bullets, description=description,
        qa_pairs=qa_pairs or [], review_summary=review_summary or {},
        aplus_content=aplus_content, a9_flags=a9_flags or [],
    ) + _SLIM_OVERRIDE

    try:
        raw = call_json(system=system, user=user, max_tokens=_SLIM_MAX_TOKENS)
    except json.JSONDecodeError as exc:
        logger.error("Rufus slim scorer: LLM returned invalid JSON — %s", exc)
        raise ValueError(f"Rufus slim scorer received malformed JSON: {exc}") from exc

    return _parse_slim_response(raw)


def score_rufus(
    title: str,
    bullets: list[str],
    description: str = "",
    qa_pairs: list[dict] | None = None,
    review_summary: dict | None = None,
    aplus_content: str = "",
    a9_flags: list[str] | None = None,
) -> RufusResult:
    """
    Call the LLM with the Rufus rubric and return a RufusResult.

    a9_flags — flags from Pass 1 injected as context; the LLM does NOT re-score A9.
    """
    system = _load_system_prompt()
    user = _build_user_message(
        title=title,
        bullets=bullets,
        description=description,
        qa_pairs=qa_pairs or [],
        review_summary=review_summary or {},
        aplus_content=aplus_content,
        a9_flags=a9_flags or [],
    )

    try:
        raw = call_json(system=system, user=user, max_tokens=2500)
    except json.JSONDecodeError as exc:
        logger.error("Rufus scorer: LLM returned invalid JSON — %s", exc)
        raise ValueError(f"Rufus scorer received malformed JSON from LLM: {exc}") from exc

    return _parse_response(raw)
