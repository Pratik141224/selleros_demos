from src.utils.s3_client import get_s3


def get_cached_product(asin):
    return get_s3().get_json(
        f"cache/products/{asin}.json"
    )


def save_product_cache(asin, product):
    get_s3().put_json(
        f"cache/products/{asin}.json",
        product
    )
