from src.clients.ingestion_client import IngestionClient as ZyteClient
from src.parsers.hierarchy_parser import HierarchyParser


class HierarchyPipeline:

    def run(self, url):

        client = ZyteClient()

        html = client.fetch_html(url)

        parser = HierarchyParser(html)

        return parser.extract_leaf_categories()
    