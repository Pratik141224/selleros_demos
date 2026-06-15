from bs4 import BeautifulSoup


class CategoryParser:

    def __init__(self, html):
        self.soup = BeautifulSoup(html, "lxml")

    def extract_categories(self):

        categories = []

        for a in self.soup.find_all("a", href=True):

            href = a["href"]
            name = a.get_text(strip=True)

            if not name:
                continue

            if "/gp/bestsellers/" in href:

                categories.append(
                    {
                        "category_name": name,
                        "category_url": href
                    }
                )

        return categories