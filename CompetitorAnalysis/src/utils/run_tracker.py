from src.utils.s3_client import get_s3


def _safe_brand(brand):
    return (
        brand
        .replace(" ", "_")
        .replace("/", "_")
    )


def _run_prefix(seed_asin, seed_brand):
    return f"runs/{seed_asin}_{_safe_brand(seed_brand)}"


def save_seed_product(seed_product, seed_html):

    s3 = get_s3()
    prefix = _run_prefix(
        seed_product["asin"],
        seed_product["brand"]
    )

    s3.put_json(
        f"{prefix}/seed_product.json",
        seed_product
    )

    s3.put_html(
        f"{prefix}/seed_product.html",
        seed_html
    )


def save_competitor_product(seed_product, competitor):

    s3 = get_s3()
    prefix = _run_prefix(
        seed_product["asin"],
        seed_product["brand"]
    )

    s3.put_json(
        f"{prefix}/products/{competitor['asin']}.json",
        competitor
    )


def save_competitor_html(seed_product, competitor_asin, html):

    s3 = get_s3()
    prefix = _run_prefix(
        seed_product["asin"],
        seed_product["brand"]
    )

    s3.put_html(
        f"{prefix}/html/{competitor_asin}.html",
        html
    )
