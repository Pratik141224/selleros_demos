from bs4 import BeautifulSoup


class HierarchyParser:

    def __init__(self, html):
        self.soup = BeautifulSoup(html, "lxml")

    def extract_leaf_categories(self):

        leaf_categories = []

        for a in self.soup.find_all("a", href=True):

            href = a["href"]
            name = a.get_text(strip=True)

            if not name:
                continue

            if "/gp/bestsellers/" in href:

                leaf_categories.append(
                    {
                        "category_name": name,
                        "category_url": href
                    }
                )

        return leaf_categories