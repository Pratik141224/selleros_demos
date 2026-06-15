from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed
)

from src.clients.ingestion_client import IngestionClient as ZyteClient

import re


class BestSellerPipeline:

    def run_page(
        self,
        url
    ):

        client = (
            ZyteClient()
        )

        response = (
            client.fetch_product_list(
                url
            )
        )

        products = []

        items = (
            response
            .get(
                "productList",
                {}
            )
            .get(
                "products",
                []
            )
        )

        for item in items:

            product_url = item.get(
                "url",
                ""
            )

            match = re.search(
                r"/dp/([A-Z0-9]{10})",
                product_url
            )

            if not match:
                continue

            asin = (
                match.group(1)
            )

            products.append(
                {
                    "asin":
                        asin,

                    "title":
                        item.get(
                            "name",
                            ""
                        ),

                    "price":
                        item.get(
                            "price"
                        ),

                    "image":
                        item.get(
                            "mainImage",
                            {}
                        ).get(
                            "url",
                            ""
                        ),

                    "url":
                        product_url
                }
            )

        return products

    def run_two_pages(
        self,
        category_id
    ):

        page_1_url = (
            f"https://www.amazon.in/gp/bestsellers/"
            f"hpc/{category_id}"
            f"?language=en_IN"
        )

        page_2_url = (
            f"https://www.amazon.in/gp/bestsellers/"
            f"hpc/{category_id}/ref=zg_bs_pg_2_hpc"
            f"?ie=UTF8&pg=2&language=en_IN"
        )

        urls = [
            page_1_url,
            page_2_url
        ]

        all_products = []

        seen = set()

        with ThreadPoolExecutor(
            max_workers=2
        ) as executor:

            futures = {

                executor.submit(
                    self.run_page,
                    url
                ): url

                for url in urls
            }

            for future in as_completed(
                futures
            ):

                url = futures[
                    future
                ]

                try:

                    products = (
                        future.result()
                    )

                    print(
                        f"\nFound {len(products)} products from:"
                    )

                    print(url)

                    for product in products:

                        asin = product[
                            "asin"
                        ]

                        if asin in seen:
                            continue

                        seen.add(
                            asin
                        )

                        all_products.append(
                            product
                        )

                except Exception as e:

                    print(
                        f"\nFAILED: {url}"
                    )

                    print(e)

        return all_products