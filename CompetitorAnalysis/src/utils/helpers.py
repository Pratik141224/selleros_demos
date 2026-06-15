BASE_URL = "https://www.amazon.in"


def make_absolute_url(url):

    if not url:
        return None

    # remove Hindi locale URLs
    url = url.replace("/-/hi/", "/")

    if url.startswith("http"):
        full_url = url
    else:
        full_url = BASE_URL + url

    # force English
    if "language=en_IN" not in full_url:

        separator = "&" if "?" in full_url else "?"

        full_url += f"{separator}language=en_IN"

    return full_url