"""
shared/s3_cache.py

S3 result cache for selleros_demos modules (keyword_gap, abd_optimizer).

Layout inside s3://{S3_BUCKET}/:

  {prefix}/{namespace}/latest.json          ← TTL check key (overwritten each run)
  {prefix}/{namespace}/history/{ts}.json    ← append-only snapshot (never overwritten)

TTL: 15 days. All S3 / parse errors silently become cache misses so callers
are never broken.

Public API
----------
get(prefix, namespace) -> dict | None
put(prefix, namespace, result)  -> None
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import s3fs

logger = logging.getLogger(__name__)

_BUCKET   = os.getenv("S3_BUCKET", "opsell")
_TTL_DAYS = 14

_fs: s3fs.S3FileSystem | None = None


def _get_fs() -> s3fs.S3FileSystem:
    global _fs
    if _fs is None:
        _fs = s3fs.S3FileSystem()
    return _fs


# ── Public API ────────────────────────────────────────────────────────────────

def get(prefix: str, namespace: str) -> dict | None:
    """
    Return the cached payload if it exists and is within the 15-day TTL, else None.

    prefix    — S3 sub-folder, e.g. "KeywordGap" or "TextEnhancement"
    namespace — unique key within the prefix, e.g. an ASIN like "B0XXXXXXXX"
    """
    path = f"{_BUCKET}/{prefix}/{namespace}/latest.json"
    try:
        fs = _get_fs()
        if not fs.exists(path):
            logger.debug("s3_cache MISS (not found): %s/%s", prefix, namespace)
            return None

        with fs.open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        raw_ts = data.get("cached_at")
        if not raw_ts:
            logger.debug("s3_cache MISS (no cached_at): %s/%s", prefix, namespace)
            return None

        cached_at = datetime.fromisoformat(raw_ts)
        age = datetime.now(timezone.utc) - cached_at
        if age > timedelta(days=_TTL_DAYS):
            logger.debug("s3_cache MISS (TTL expired, age=%s): %s/%s", age, prefix, namespace)
            return None

        logger.info("s3_cache HIT: %s/%s (age=%dd %dh)", prefix, namespace,
                    age.days, age.seconds // 3600)
        return data

    except Exception as exc:
        logger.warning("s3_cache read error %s/%s — %s", prefix, namespace, exc)
        return None


def put(prefix: str, namespace: str, result: dict) -> None:
    """
    Write result to S3:
      • latest.json        — always overwritten (TTL check key)
      • history/{ts}.json  — append-only snapshot for trend tracking

    Errors are logged as warnings and swallowed so callers are never broken.
    """
    ts      = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    payload = {**result, "cached_at": datetime.now(timezone.utc).isoformat()}
    body    = json.dumps(payload, default=str, ensure_ascii=False)

    try:
        fs = _get_fs()
        for path in [
            f"{_BUCKET}/{prefix}/{namespace}/latest.json",
            f"{_BUCKET}/{prefix}/{namespace}/history/{ts}.json",
        ]:
            with fs.open(path, "w", encoding="utf-8") as f:
                f.write(body)
        logger.info("s3_cache WRITE: %s/%s", prefix, namespace)

    except Exception as exc:
        logger.warning("s3_cache write error %s/%s — %s", prefix, namespace, exc)
