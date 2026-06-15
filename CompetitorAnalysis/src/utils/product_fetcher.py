from src.utils.cache import (
    get_cached_product,
    save_product_cache
)

from src.utils.html_cache import (
    save_html_cache
)


class ProductFetcher:

    def __init__(
        self,
        product_pipeline
    ):
        self.product_pipeline = (
            product_pipeline
        )

    def get_product(
        self,
        asin
    ):

        cached = (
            get_cached_product(
                asin
            )
        )

        if (
            cached
            and
            cached.get(
                "title"
            )
        ):

            print(
                f"[CACHE HIT] {asin}"
            )

            return cached

        print(
            f"[API CALL] {asin}"
        )

        product = (
            self.product_pipeline.run(
                asin
            )
        )

        save_product_cache(
            asin,
            product
        )

        try:

            url = (
                f"https://www.amazon.in/dp/"
                f"{asin}"
                f"?language=en_IN"
            )

            html = (
                self.product_pipeline.client
                .fetch_html(
                    url
                )
            )

            save_html_cache(
                asin,
                html
            )

            print(
                f"[HTML SAVED] {asin}"
            )

        except Exception as e:

            print(
                f"[HTML FAILED] {asin}"
            )

            print(e)

        return product