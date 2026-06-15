"""
marketplaces/amazon/zyte_mapper.py

Maps a Zyte /extract/product response dict to a ListingInput.
All field mappings are driven by field_map.yaml — no field names are
hardcoded here. To handle a Zyte schema change, edit the YAML only.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

import yaml

from marketplaces.base_lqs import ListingInput

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent / "field_map.yaml"
_config: dict | None = None


def _load_config() -> dict:
    global _config
    if _config is None:
        _config = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8"))
        logger.debug("zyte_mapper: loaded field_map.yaml v%s", _config.get("version", "?"))
    return _config


def reload_config() -> None:
    """Force a reload of field_map.yaml — useful when the file is edited at runtime."""
    global _config
    _config = None
    _load_config()


# ── named transform functions ──────────────────────────────────────────────────

def _category_hierarchy_to_browse_node(value: Any) -> str:
    hierarchy = value or []
    parts = [node.get("name", "") for node in hierarchy if node.get("name")]
    return " > ".join(parts)


def _leaf_category_name(value: Any) -> str:
    hierarchy = value or []
    for node in reversed(hierarchy):
        name = node.get("name", "")
        if name:
            return name
    return ""


def _urls_to_image_dicts(value: Any) -> list[dict]:
    urls = value or []
    return [
        {
            "url":      url,
            "alt_text": "",
            "role":     "main" if i == 0 else "additional",
        }
        for i, url in enumerate(urls)
        if url
    ]


def _build_review_summary(product: dict, sources: dict) -> dict:
    avg_field   = sources.get("avg_rating",   "rating")
    count_field = sources.get("review_count", "review_count")
    return {
        "avg_rating":    product.get(avg_field),
        "review_count":  product.get(count_field),
        "top_negatives": [],
    }


# Registry: transform name (from YAML) → callable
# To add a new transform: add the function above, then register it here.
_TRANSFORMS: dict[str, Callable] = {
    "category_hierarchy_to_browse_node": _category_hierarchy_to_browse_node,
    "leaf_category_name":                _leaf_category_name,
    "urls_to_image_dicts":               _urls_to_image_dicts,
}

# build_review_summary is handled separately because it needs the full product dict
_COMPOSITE_TRANSFORMS = {"build_review_summary"}


# ── mapper ─────────────────────────────────────────────────────────────────────

def map_zyte_to_listing_input(product: dict) -> ListingInput:
    """
    Map a single Zyte /extract/product dict to a ListingInput.
    All field names come from field_map.yaml — zero hardcoded field names here.
    """
    cfg = _load_config()
    kwargs: dict[str, Any] = {}

    # ── direct mappings ────────────────────────────────────────────────────
    for lqs_field, zyte_field in (cfg.get("direct") or {}).items():
        val = product.get(zyte_field)
        if val is not None:
            kwargs[lqs_field] = val

    # ── derived mappings ───────────────────────────────────────────────────
    for lqs_field, spec in (cfg.get("derived") or {}).items():
        transform_name = spec.get("transform", "")

        if transform_name in _COMPOSITE_TRANSFORMS:
            # composite: needs the whole product dict + sources sub-map
            if transform_name == "build_review_summary":
                kwargs[lqs_field] = _build_review_summary(
                    product, spec.get("sources", {})
                )

        elif transform_name in _TRANSFORMS:
            source_field = spec.get("source")
            raw_value = product.get(source_field) if source_field else None
            kwargs[lqs_field] = _TRANSFORMS[transform_name](raw_value)

        else:
            logger.warning(
                "zyte_mapper: unknown transform %r for field %r — skipping",
                transform_name, lqs_field,
            )

    # ── unavailable fields: already at ListingInput defaults, no action needed ─

    return ListingInput(**kwargs)
