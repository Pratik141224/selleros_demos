import os
import requests
from dotenv import load_dotenv

load_dotenv()
ZYTE_API_KEY = os.getenv("ZYTE_API_KEY")


class ZyteClient:

    def __init__(self):

        self.api_key = (
            ZYTE_API_KEY
        )

        self.base_url = (
            "https://api.zyte.com/v1/extract"
        )

    def fetch_html(
        self,
        url
    ):

        if "language=en_IN" not in url:

            separator = (
                "&"
                if "?"
                in url
                else "?"
            )

            url += (
                f"{separator}language=en_IN"
            )

        payload = {
            "url": url,
            "browserHtml": True
        }

        response = requests.post(
            self.base_url,
            auth=(
                self.api_key,
                ""
            ),
            json=payload
        )

        response.raise_for_status()

        return response.json()[
            "browserHtml"
        ]

    def fetch_product(
        self,
        asin
    ):

        url = (
            f"https://www.amazon.in/dp/"
            f"{asin}"
            f"?language=en_IN"
        )

        payload = {
            "url": url,
            "product": True
        }

        response = requests.post(
            self.base_url,
            auth=(
                self.api_key,
                ""
            ),
            json=payload
        )

        response.raise_for_status()

        return response.json()

    def fetch_product_list(
        self,
        url
    ):

        if "language=en_IN" not in url:

            separator = (
                "&"
                if "?"
                in url
                else "?"
            )

            url += (
                f"{separator}language=en_IN"
            )

        payload = {
            "url": url,
            "productList": True
        }

        response = requests.post(
            self.base_url,
            auth=(
                self.api_key,
                ""
            ),
            json=payload
        )

        response.raise_for_status()

        return response.json()