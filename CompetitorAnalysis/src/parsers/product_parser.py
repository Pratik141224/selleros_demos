from bs4 import BeautifulSoup


class ProductParser:

    def __init__(self, html):
        self.soup = BeautifulSoup(
            html,
            "lxml"
        )

    def extract_title(self):

        title = self.soup.find(
            id="productTitle"
        )

        if title:
            return title.get_text(
                strip=True
            )

        return None

    def extract_brand(self):

        brand = self.soup.find(
            id="bylineInfo"
        )

        if brand:
            return brand.get_text(
                strip=True
            )

        return None

    def extract_rating(self):

        rating = self.soup.find(
            "span",
            class_="a-icon-alt"
        )

        if rating:
            return rating.get_text(
                strip=True
            )

        return None

    def extract_bullets(self):

        bullets = []

        feature_div = self.soup.find(
            id="feature-bullets"
        )

        if not feature_div:
            return bullets

        for li in feature_div.find_all(
            "li"
        ):

            text = li.get_text(
                strip=True
            )

            if text:
                bullets.append(
                    text
                )

        return bullets

    def extract_description(self):

        desc = self.soup.find(
            id="productDescription"
        )

        if desc:

            return desc.get_text(
                " ",
                strip=True
            )

        return ""

    def extract_aplus(self):

        aplus = self.soup.find(
            id="aplus"
        )

        if aplus:

            return aplus.get_text(
                " ",
                strip=True
            )

        return ""

    def extract_breadcrumbs(self):

        breadcrumbs = []

        nav = self.soup.find(
            id="wayfinding-breadcrumbs_feature_div"
        )

        if not nav:
            return breadcrumbs

        for a in nav.find_all(
            "a",
            href=True
        ):

            breadcrumbs.append(
                {
                    "name": a.get_text(
                        strip=True
                    ),
                    "url": a["href"]
                }
            )

        return breadcrumbs

    def extract_last_category(self):

        breadcrumbs = (
            self.extract_breadcrumbs()
        )

        if not breadcrumbs:
            return None

        return breadcrumbs[-1]

    def extract_product_data(self):

        return {

            "title":
                self.extract_title(),

            "brand":
                self.extract_brand(),

            "rating":
                self.extract_rating(),

            "bullets":
                self.extract_bullets(),

            "description":
                self.extract_description(),

            "aplus":
                self.extract_aplus(),

            "breadcrumbs":
                self.extract_breadcrumbs(),

            "last_category":
                self.extract_last_category()
        }