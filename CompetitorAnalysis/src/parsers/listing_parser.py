from bs4 import BeautifulSoup
import re


class ListingParser:

    def __init__(self, html):
        self.soup = BeautifulSoup(html, "lxml")

    def extract_products(self):

        products = []
        seen = set()

        for a in self.soup.find_all("a", href=True):

            href = a["href"]

            match = re.search(
                r"/dp/([A-Z0-9]{10})",
                href
            )

            if not match:
                continue

            asin = match.group(1)

            if asin in seen:
                continue

            seen.add(asin)

            products.append(
                {
                    "asin": asin,
                    "url": href
                }
            )

        return products