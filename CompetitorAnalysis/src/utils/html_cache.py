from src.utils.s3_client import get_s3


def save_html_cache(asin, html):
    get_s3().put_html(
        f"raw/html/{asin}.html",
        html
    )
