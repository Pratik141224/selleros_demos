"""
shared/llm_router.py
Multi-provider LLM router. Provider selected by DEMO_LLM_PROVIDER env var.
Default: openrouter (free tier — no credits needed).
"""

import os
import json
import re
import time
import logging
from dataclasses import dataclass
from enum import Enum

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class TaskType(str, Enum):
    CREATIVE   = "creative"
    STRUCTURED = "structured"
    SCORING    = "scoring"
    FALLBACK   = "fallback"


@dataclass
class LLMResponse:
    content:  dict
    cost_usd: float


# ── Model routing tables ──────────────────────────────────────────────────────

_ROUTE: dict[str, dict[TaskType, str]] = {
    "openrouter": {
        TaskType.CREATIVE:   "qwen/qwen3-235b-a22b:free",
        TaskType.STRUCTURED: "meta-llama/llama-3.3-70b-instruct:free",
        TaskType.SCORING:    "meta-llama/llama-3.3-70b-instruct:free",
        TaskType.FALLBACK:   "mistralai/mistral-small-3.1-24b-instruct:free",
    },
    "anthropic": {
        TaskType.CREATIVE:   "claude-sonnet-4-6",
        TaskType.STRUCTURED: "claude-sonnet-4-6",
        TaskType.SCORING:    "claude-sonnet-4-6",
        TaskType.FALLBACK:   "claude-sonnet-4-6",
    },
    "openai": {
        TaskType.CREATIVE:   "gpt-4o-mini",
        TaskType.STRUCTURED: "gpt-4o-mini",
        TaskType.SCORING:    "gpt-4o-mini",
        TaskType.FALLBACK:   "gpt-4o-mini",
    },
    "groq": {
        TaskType.CREATIVE:   "llama-3.3-70b-versatile",
        TaskType.STRUCTURED: "llama-3.3-70b-versatile",
        TaskType.SCORING:    "llama-3.3-70b-versatile",
        TaskType.FALLBACK:   "llama-3.3-70b-versatile",
    },
}

# Informational cost rates (USD per million tokens)
_COST_PER_MTok: dict[str, dict[str, float]] = {
    "openrouter": {"in": 0.0,  "out": 0.0},    # free tier
    "anthropic":  {"in": 3.0,  "out": 15.0},   # claude-sonnet-4 approximate
    "openai":     {"in": 0.15, "out": 0.6},    # gpt-4o-mini approximate
    "groq":       {"in": 0.05, "out": 0.08},   # llama3.3 approximate
}


# ── Human voice rules — auto-injected into every system prompt ───────────────
# See .claude/agents/human_voice.md for the full rationale and update instructions.

_HUMAN_VOICE_SUFFIX = """
VOICE AND STYLE — apply to every text field in your output:

NEVER use these patterns:
  Filler transitions : "In summary", "Overall", "To summarize", "It's worth noting",
                       "Importantly", "Furthermore", "Moreover", "Additionally" as openers
  Hedge language     : "It's important to note that", "Please keep in mind",
                       "It should be noted", "Keep in mind that"
  Intensifiers       : "incredibly", "extremely", "highly", "truly", "really", "very"
                       before adjectives; "perfect", "amazing", "excellent" as standalone descriptors
  Vague power-verbs  : "leverage" (→ use), "utilize" (→ use), "facilitate" (→ help),
                       "enable" (→ let/allow), "delve into", "dive into", "unpack", "explore"
                       as rhetorical openers
  Structural tells   : **Bold label:** followed by explanation on the same bullet line;
                       bullets ending with "and more!" or "!";
                       em-dash (—) mid-sentence used purely for rhetorical pause;
                       rhetorical questions mid-copy ("But what does this mean for you?");
                       "Whether you're X or Y..." constructions;
                       closing summary paragraphs that restate what was just said
  AI markers         : "Certainly!", "Absolutely!", "Of course!", "Great question!";
                       "As a large language model", "I was trained to"

INSTEAD write like this:
  Short, direct sentences — specific subject, active verb, no padding.
  Numbers beat adjectives: "4mm sole" is stronger than "thin, comfortable, supportive sole".
  Contractions are fine: "it won't" not "it does not".
  Every word must earn its place. If removing it loses no meaning, remove it."""


# ── JSON helpers ──────────────────────────────────────────────────────────────

def _strip_fences(text: str) -> str:
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip()
    return re.sub(r"```\s*$", "", cleaned).strip()


def _parse_json(raw: str) -> dict:
    cleaned = _strip_fences(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"LLM returned non-JSON.\nError: {e}\nRaw (first 500 chars):\n{raw[:500]}"
        )


# ── Provider callers — each returns (text, in_tokens, out_tokens) ─────────────

def _call_openrouter(model: str, system: str, user: str, max_tokens: int) -> tuple[str, int, int]:
    from openai import OpenAI
    client = OpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": "https://selleros.app",
            "X-Title": "SellerOS Demos",
        },
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    text  = resp.choices[0].message.content or ""
    usage = resp.usage
    return text, usage.prompt_tokens, usage.completion_tokens


def _call_anthropic(model: str, system: str, user: str, max_tokens: int) -> tuple[str, int, int]:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in msg.content if hasattr(b, "text"))
    return text, msg.usage.input_tokens, msg.usage.output_tokens


def _call_openai(model: str, system: str, user: str, max_tokens: int) -> tuple[str, int, int]:
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    text  = resp.choices[0].message.content or ""
    usage = resp.usage
    return text, usage.prompt_tokens, usage.completion_tokens


def _call_groq(model: str, system: str, user: str, max_tokens: int) -> tuple[str, int, int]:
    from groq import Groq
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    text  = resp.choices[0].message.content or ""
    usage = resp.usage
    return text, usage.prompt_tokens, usage.completion_tokens


_PROVIDER_CALLERS = {
    "openrouter": _call_openrouter,
    "anthropic":  _call_anthropic,
    "openai":     _call_openai,
    "groq":       _call_groq,
}


# ── Rate-limit detection ──────────────────────────────────────────────────────

def _is_rate_limit(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "rate limit" in msg or "quota" in msg


# ── Cost estimation ───────────────────────────────────────────────────────────

def _estimate_cost(provider: str, in_tok: int, out_tok: int) -> float:
    rates = _COST_PER_MTok.get(provider, {"in": 0.0, "out": 0.0})
    return (in_tok * rates["in"] + out_tok * rates["out"]) / 1_000_000


# ── Public interface ──────────────────────────────────────────────────────────

def call(
    task_type: TaskType,
    system: str,
    user: str,
    max_tokens: int = 2048,
) -> LLMResponse:
    """
    Route an LLM call to the configured provider.

    Provider is read from DEMO_LLM_PROVIDER env var (default: openrouter).
    On OpenRouter HTTP 429, sleeps 3s and retries once with the FALLBACK model.
    Always returns LLMResponse with .content (parsed dict) and .cost_usd (float).
    """
    provider = os.getenv("DEMO_LLM_PROVIDER", "openrouter").lower()
    if provider not in _ROUTE:
        raise ValueError(
            f"Unknown DEMO_LLM_PROVIDER={provider!r}. "
            f"Valid options: {list(_ROUTE.keys())}"
        )

    route  = _ROUTE[provider]
    caller = _PROVIDER_CALLERS[provider]
    model  = route[task_type]
    system = f"{system}{_HUMAN_VOICE_SUFFIX}"

    logger.info("[llm_router] provider=%s task=%s model=%s", provider, task_type, model)

    try:
        raw, in_tok, out_tok = caller(model, system, user, max_tokens)

    except Exception as exc:
        if provider == "openrouter" and _is_rate_limit(exc):
            fallback_model = route[TaskType.FALLBACK]
            logger.warning(
                "[llm_router] 429 on %s — sleeping 3s, retrying with %s",
                model, fallback_model,
            )
            time.sleep(3)
            try:
                raw, in_tok, out_tok = caller(fallback_model, system, user, max_tokens)
            except Exception as fb_exc:
                raise ValueError("OpenRouter quota exhausted") from fb_exc
        else:
            raise

    return LLMResponse(
        content=_parse_json(raw),
        cost_usd=_estimate_cost(provider, in_tok, out_tok),
    )
