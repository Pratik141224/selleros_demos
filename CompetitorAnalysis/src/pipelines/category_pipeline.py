from src.clients.ingestion_client import IngestionClient as ZyteClient
from src.parsers.category_parser import CategoryParser


class CategoryPipeline:

    def run(self, url):

        client = ZyteClient()

        html = client.fetch_html(url)

        parser = CategoryParser(html)

        return parser.extract_categories()