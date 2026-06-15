from bs4 import BeautifulSoup
import re


class BestSellerParser:

    def __init__(self, html):

        self.soup = BeautifulSoup(
            html,
            "lxml"
        )

    def extract_products(self):

        products = []
        seen = set()

        # Amazon bestseller page product links
        for a in self.soup.find_all("a", href=True):

            href = a.get("href", "")

            match = re.search(
                r"/dp/([A-Z0-9]{10})",
                href
            )

            if not match:
                continue

            asin = match.group(1)

            if asin in seen:
                continue

            title = a.get_text(
                " ",
                strip=True
            )

            if len(title) < 5:
                continue

            if href.startswith("/"):
                full_url = (
                    "https://www.amazon.in"
                    + href
                )
            else:
                full_url = href

            seen.add(asin)

            products.append(
                {
                    "asin": asin,
                    "title": title,
                    "url": full_url
                }
            )

        return products