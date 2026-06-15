from src.clients.ingestion_client import IngestionClient as ZyteClient
from src.parsers.listing_parser import ListingParser


class ListingPipeline:

    def run(self, url):

        client = ZyteClient()

        html = client.fetch_html(url)

        parser = ListingParser(html)

        return parser.extract_products()