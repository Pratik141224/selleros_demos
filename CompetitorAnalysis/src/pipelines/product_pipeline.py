from src.clients.ingestion_client import IngestionClient as ZyteClient


class ProductPipeline:

    def __init__(self):

        self.client = (
            ZyteClient()
        )

    def _map_response(self, product: dict) -> dict:
        """Map a raw Zyte product dict to our internal schema.

        Extracted from run() so competitor_service can reuse it for
        batch results without making an extra HTTP call per ASIN.
        """
        return {
            "asin":         product.get("sku"),
            "title":        product.get("name", ""),
            "brand":        product.get("brand", {}).get("name", ""),
            "price":        product.get("price"),
            "rating":       product.get("aggregateRating", {}).get("ratingValue"),
            "review_count": product.get("aggregateRating", {}).get("reviewCount"),
            "product_url":  product.get("canonicalUrl", ""),
            "main_image":   product.get("mainImage", {}).get("url", ""),
            "description":  product.get("description", ""),
            "bullet_points": product.get("features", []),
            "images":       [img.get("url", "") for img in product.get("images", [])],
            "breadcrumbs":  product.get("breadcrumbs", []),
            "raw":          product,
        }

    def run(
        self,
        asin
    ):

        response = (
            self.client.fetch_product(
                asin
            )
        )

        product = response[
            "product"
        ]

        print(
            "\nPRODUCT KEYS:"
        )

        print(
            product.keys()
        )

        print(
            "\nFEATURES COUNT:",
            len(
                product.get(
                    "features",
                    []
                )
            )
        )

        print(
            "\nDESCRIPTION LENGTH:",
            len(
                product.get(
                    "description",
                    ""
                )
            )
        )

        return self._map_response(product)
