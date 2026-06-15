import re

from src.clients.ingestion_client import IngestionClient as ZyteClient
from src.parsers.category_page_parser import CategoryPageParser
from src.utils.helpers import make_absolute_url


class CategoryIntelligencePipeline:

    def run(self, category_url):

        node_match = re.search(
            r"node=(\d+)",
            category_url
        )

        node_id = None

        if node_match:
            node_id = node_match.group(1)

        client = ZyteClient()

        html = client.fetch_html(category_url)

        parser = CategoryPageParser(html)

        best_seller_url = None

        if node_id:
            best_seller_url = parser.extract_best_seller_url(
                node_id
            )

        return {
            "node_id": node_id,
            "best_seller_url": make_absolute_url(
                best_seller_url
            ),
            "top_rated_url": make_absolute_url(
                parser.extract_top_rated_url()
            ),
            "new_release_url": make_absolute_url(
                parser.extract_new_release_url()
            )
        }