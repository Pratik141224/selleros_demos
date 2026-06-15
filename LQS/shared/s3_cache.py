"""
S3-based result cache for all LQS endpoints.

S3 layout inside s3://{S3_BUCKET}/{S3_RAW_PREFIX_LQS}/:

  marketplace/{MARKETPLACE}/{ASIN}/latest.json          ← /analyze-listing
  marketplace/{MARKETPLACE}/{ASIN}/history/{ts}.json    ← historical snapshots

  pipeline/{mode}/{identifier}/latest.json              ← /analyze
  pipeline/{mode}/{identifier}/history/{ts}.json

  text_score/{hash}/latest.json                         ← /listing-score
  text_score/{hash}/history/{ts}.json

Every cached file includes a `cached_at` ISO-8601 UTC timestamp written at
store time. TTL is 15 days. Cache reads and writes fail gracefully — any S3
error is logged as a warning and treated as a cache miss so the main pipeline
always runs.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import s3fs

logger = logging.getLogger(__name__)

_BUCKET   = os.getenv("S3_BUCKET",     "opsell")
_PREFIX   = os.getenv("S3_RAW_PREFIX_LQS", "LQS")
_TTL_DAYS = 15

_fs: s3fs.S3FileSystem | None = None


def _get_fs() -> s3fs.S3FileSystem:
    global _fs
    if _fs is None:
        _fs = s3fs.S3FileSystem()
    return _fs


def _latest_path(namespace: str) -> str:
    return f"{_BUCKET}/{_PREFIX}/{namespace}/latest.json"


def _history_path(namespace: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    return f"{_BUCKET}/{_PREFIX}/{namespace}/history/{ts}.json"


# ── Public API ────────────────────────────────────────────────────────────────

def get(namespace: str) -> dict | None:
    """
    Return the cached payload if it exists and is within the 15-day TTL.

    namespace  — slash-separated S3 sub-path, e.g. "marketplace/IN/B0G2MM7VH9"
    Returns None on miss, TTL expiry, or any S3/parse error.
    """
    path = _latest_path(namespace)
    try:
        fs = _get_fs()
        if not fs.exists(path):
            logger.debug("s3_cache MISS (not found): %s", namespace)
            return None

        with fs.open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        raw_ts = data.get("cached_at")
        if not raw_ts:
            logger.debug("s3_cache MISS (no cached_at): %s", namespace)
            return None

        cached_at = datetime.fromisoformat(raw_ts)
        age = datetime.now(timezone.utc) - cached_at
        if age > timedelta(days=_TTL_DAYS):
            logger.debug("s3_cache MISS (TTL expired, age=%s): %s", age, namespace)
            return None

        logger.info("s3_cache HIT: %s (age=%dd %dh)", namespace, age.days, age.seconds // 3600)
        return data

    except Exception as exc:
        logger.warning("s3_cache read error for %s — %s", namespace, exc)
        return None


def put(namespace: str, result: dict) -> None:
    """
    Write result to S3:
      • latest.json  — always overwritten (TTL check key)
      • history/{ts}.json — append-only snapshot for trend tracking

    namespace  — slash-separated S3 sub-path, e.g. "marketplace/IN/B0G2MM7VH9"
    Errors are logged as warnings and swallowed so callers are never broken.
    """
    payload = {**result, "cached_at": datetime.now(timezone.utc).isoformat()}
    body    = json.dumps(payload, default=str, ensure_ascii=False)

    try:
        fs      = _get_fs()
        latest  = _latest_path(namespace)
        history = _history_path(namespace)

        with fs.open(latest, "w", encoding="utf-8") as f:
            f.write(body)
        with fs.open(history, "w", encoding="utf-8") as f:
            f.write(body)

        logger.info("s3_cache WRITE: %s", namespace)

    except Exception as exc:
        logger.warning("s3_cache write error for %s — %s", namespace, exc)
