import re

from src.utils.result_cache import (
    load_cached_results
)

from src.utils.run_tracker import (
    save_seed_product,
    save_competitor_product,
    save_competitor_html
)

from src.utils.parquet_writer import (
    save_competitors_parquet
)

from src.pipelines.bestseller_pipeline import (
    BestSellerPipeline
)

from src.matching.title_matcher import (
    TitleMatcher
)

from src.matching.deep_matcher import (
    DeepMatcher
)

from src.pipelines.product_pipeline import (
    ProductPipeline
)

from src.utils.product_fetcher import (
    ProductFetcher
)


def extract_category_id(seed_product):
    """Extract Amazon node ID from breadcrumb URLs.

    Iterates from leaf to root and tries both "url" and "link" keys since
    the RawIngestionService raw Zyte endpoint may use either depending on
    the product page layout.
    """
    for crumb in reversed(seed_product.get("breadcrumbs", [])):
        url = crumb.get("url") or crumb.get("link") or ""
        match = re.search(r"(?:node=|n%3A)(\d+)", url)
        if match:
            return match.group(1)
    return None


def find_competitors(
    seed_asin: str
):

    cached_df = (
        load_cached_results(
            seed_asin
        )
    )

    if cached_df is not None:

        return {
            "seed_asin": seed_asin,
            "source": "cache",
            "competitor_count": len(cached_df),
            "competitors": cached_df.to_dict(
                orient="records"
            )
        }

    product_pipeline = (
        ProductPipeline()
    )

    fetcher = ProductFetcher(
        product_pipeline
    )

    seed_product = (
        fetcher.get_product(
            seed_asin
        )
    )

    seed_html = (
        product_pipeline.client.fetch_html(
            f"https://www.amazon.in/dp/{seed_asin}?language=en_IN"
        )
    )

    save_seed_product(
        seed_product,
        seed_html
    )

    if not seed_product:

        raise Exception(
            "Unable to fetch seed product"
        )

    seed_title = (
        seed_product["title"]
    )

    category_id = (
        extract_category_id(
            seed_product
        )
    )

    if not category_id:

        raise Exception(
            "Unable to determine category id"
        )

    bestseller_pipeline = (
        BestSellerPipeline()
    )

    products = (
        bestseller_pipeline.run_two_pages(
            category_id
        )
    )

    title_matcher = (
        TitleMatcher()
    )

    title_results = (
        title_matcher.match(
            seed_title,
            products
        )
    )

    top_products = (
        title_results[:20]
    )

    candidate_products = []

    # Fetch all competitor details in one batch call.
    # The RawIngestionService fans out with ZYTE_MAX_CONCURRENCY=5 internally:
    # 20 ASINs → ~2 waves of 5 → ~2× single-ASIN latency instead of 20×.
    batch_asins = [p["asin"] for p in top_products]
    batch_data = product_pipeline.client.fetch_products_batch(batch_asins)

    print(f"\n[SellerOS] Batch fetched {len(batch_data)}/{len(batch_asins)} competitor products")

    for asin, wrapped in batch_data.items():
        try:
            detail = product_pipeline._map_response(wrapped["product"])
            save_competitor_product(seed_product, detail)
            html = product_pipeline.client.fetch_html(
                f"https://www.amazon.in/dp/{asin}?language=en_IN"
            )
            save_competitor_html(seed_product, asin, html)
            candidate_products.append(detail)
        except Exception:
            pass

    deep_matcher = (
        DeepMatcher()
    )

    deep_results = (
        deep_matcher.match(
            seed_product,
            candidate_products
        )
    )

    seed_brand = (
        seed_product["brand"]
        .strip()
        .lower()
    )

    final_results = []

    for product in deep_results:

        product_brand = (
            product["brand"]
            .strip()
            .lower()
        )

        if (
            product["asin"]
            ==
            seed_asin
        ):
            continue

        if (
            product_brand
            ==
            seed_brand
        ):
            continue

        final_results.append(
            product
        )

    final_results = sorted(
        final_results,
        key=lambda x: x[
            "deep_score"
        ],
        reverse=True
    )

    final_results = (
        final_results[:10]
    )

    save_competitors_parquet(
        seed_asin,
        final_results
    )

    return {
        "seed_asin": seed_asin,
        "source": "fresh",
        "competitor_count": len(
            final_results
        ),
        "competitors": final_results
    }
