from bs4 import BeautifulSoup
import re


class CategoryPageParser:

    def __init__(self, html):
        self.soup = BeautifulSoup(html, "lxml")

    def extract_best_seller_url(self, node_id):

        for a in self.soup.find_all("a", href=True):

            href = a.get("href", "")

            if (
                "/gp/bestsellers/" in href
                and node_id in href
            ):
                return href

        return None

    def extract_top_rated_url(self):

        for a in self.soup.find_all("a", href=True):

            href = a.get("href", "")
            text = a.get_text(" ", strip=True)

            if (
                "टॉप रेटिंग" in text
                or "top rated" in text.lower()
            ):
                return href

        return None

    def extract_new_release_url(self):

        for a in self.soup.find_all("a", href=True):

            href = a.get("href", "")
            text = a.get_text(" ", strip=True)

            if (
                "नए रिलीज़" in text
                or "new release" in text.lower()
            ):
                return href

        return None