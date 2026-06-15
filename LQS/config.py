"""Global configuration — values can be overridden via environment variables."""
import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


@dataclass
class Config:
    # API — Zyte-based EC2 scraping service (no auth key required)
    zyte_base_url: str  = field(default_factory=lambda: _env("ZYTE_BASE_URL", "http://54.197.215.125:4001"))
    country_code : str  = field(default_factory=lambda: _env("OPSELL_COUNTRY_CODE", "IN"))
    timeout_s    : int  = 90
    allow_origins: str  = field(default_factory=lambda: _env("ALLOW_ORIGINS", "*"))

    # Model
    model_path   : Path = field(default_factory=lambda: Path(_env("MODEL_PATH", "DataStore/models/lqs_model.pkl")))

    # Scoring
    lqs_min       : float = 65.0
    lqs_max       : float = 95.0
    grade_a_cut   : float = 88.0
    grade_b_cut   : float = 75.0
    blend_model_w : float = 0.4

    # Competitor selection
    top_n_competitors : int             = 10
    buried_pages      : tuple[int, ...] = (2, 3, 4, 5, 6, 7)
    min_comp_rating   : float           = 0.0
    min_comp_reviews  : int             = 0




CFG = Config()

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "laptop"   : ["laptop","notebook","chromebook","macbook","vivobook","ideapad",
                  "inspiron","pavilion","aspire","zenbook","thinkpad","elitebook",
                  "probook","gram","swift","ryzen","core i3","core i5","core i7"],
    "phone"    : ["phone","smartphone","iphone","galaxy","redmi","poco","oneplus",
                  "realme","vivo","oppo","pixel","mobile"],
    "headphone": ["headphone","earphone","earbuds","tws","airpods","headset","neckband"],
    "tv"       : ["tv","television","smart tv","qled","oled","led tv"],
    "tablet"   : ["tablet","ipad","fire hd"],
}

BRAND_VOCAB: set[str] = {
    "hp","dell","lenovo","asus","acer","apple","samsung","msi","lg","sony",
    "xiaomi","realme","oneplus","redmi","infinix","boat","jbl","sennheiser",
    "bose","noise","mi","iphone","macbook","thomson","toshiba","huawei",
}