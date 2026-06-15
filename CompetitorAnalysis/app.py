import re
import pandas as pd
import streamlit as st

from src.pipelines.bestseller_pipeline import (
    BestSellerPipeline
)

from src.pipelines.product_pipeline import (
    ProductPipeline
)

from src.utils.product_fetcher import (
    ProductFetcher
)

from src.matching.title_matcher import (
    TitleMatcher
)

from src.matching.deep_matcher import (
    DeepMatcher
)


# =====================================
# HELPERS
# =====================================

def extract_category_id(seed_product):

    breadcrumbs = (
        seed_product.get(
            "breadcrumbs",
            []
        )
    )

    if not breadcrumbs:
        return None

    url = (
        breadcrumbs[-1].get(
            "url",
            ""
        )
    )

    match = re.search(
        r"(?:node=|n%3A)(\d+)",
        url
    )

    if match:
        return match.group(1)

    return None


# =====================================
# STREAMLIT CONFIG
# =====================================

st.set_page_config(
    page_title="Amazon Competitor Discovery",
    layout="wide"
)

st.title(
    "Amazon Competitor Discovery Engine"
)

st.caption(
    "Enter an Amazon ASIN and discover the most semantically similar competitor products."
)

seed_asin = st.text_input(
    "Enter Amazon ASIN",
    value="B0DV951LZK"
)

run_btn = st.button(
    "Find Competitors"
)


# =====================================
# MAIN
# =====================================

if run_btn:

    with st.spinner(
        "Running competitor discovery pipeline..."
    ):

        # -------------------------
        # Product Fetcher
        # -------------------------

        product_pipeline = (
            ProductPipeline()
        )

        fetcher = ProductFetcher(
            product_pipeline
        )

        # -------------------------
        # Seed Product
        # -------------------------

        seed_product = (
            fetcher.get_product(
                seed_asin
            )
        )

        if not seed_product:

            st.error(
                "Unable to fetch seed product."
            )

            st.stop()

        seed_title = (
            seed_product.get(
                "title",
                ""
            )
        )

        if not seed_title:

            st.error(
                "Seed product title not found."
            )

            st.stop()

        # -------------------------
        # Category ID
        # -------------------------

        category_id = (
            extract_category_id(
                seed_product
            )
        )

        if not category_id:

            st.error(
                "Unable to determine category ID."
            )

            st.stop()

        st.success(
            f"Detected Category ID: {category_id}"
        )

        # -------------------------
        # Bestseller Products
        # -------------------------

        bestseller_pipeline = (
            BestSellerPipeline()
        )

        products = (
            bestseller_pipeline.run_two_pages(
                category_id
            )
        )

        # -------------------------
        # Title Matching
        # -------------------------

        title_matcher = (
            TitleMatcher()
        )

        title_results = (
            title_matcher.match(
                seed_title,
                products
            )
        )

        top_products = (
            title_results[:20]
        )

        # -------------------------
        # Product Detail Fetch
        # -------------------------

        candidate_products = []

        for product in top_products:

            try:

                detail = (
                    fetcher.get_product(
                        product["asin"]
                    )
                )

                candidate_products.append(
                    detail
                )

            except Exception:

                pass

        # -------------------------
        # Deep Matching
        # -------------------------

        deep_matcher = (
            DeepMatcher()
        )

        deep_results = (
            deep_matcher.match(
                seed_product,
                candidate_products
            )
        )

        # -------------------------
        # Filter Results
        # -------------------------

        seed_brand = (
            seed_product["brand"]
            .strip()
            .lower()
        )

        final_results = []

        for product in deep_results:

            if (
                product["asin"]
                ==
                seed_asin
            ):
                continue

            if (
                product["brand"]
                .strip()
                .lower()
                ==
                seed_brand
            ):
                continue

            final_results.append(
                product
            )

        final_results = (
            final_results[:10]
        )

    # =====================================
    # UI OUTPUT
    # =====================================

    st.success(
        "Analysis Complete"
    )

    st.subheader(
        "Seed Product"
    )

    st.image(
        seed_product.get(
            "main_image",
            ""
        ),
        width=250
    )

    st.write(
        f"**Title:** {seed_product['title']}"
    )

    st.write(
        f"**Brand:** {seed_product['brand']}"
    )

    st.write(
        f"**ASIN:** {seed_product['asin']}"
    )

    st.write(
        f"**Price:** ₹{seed_product.get('price')}"
    )

    st.write(
        f"**Rating:** {seed_product.get('rating')}"
    )

    st.write(
        f"**Reviews:** {seed_product.get('review_count')}"
    )

    st.write(
        seed_product.get(
            "product_url",
            ""
        )
    )

    # -------------------------
    # Competitor Table
    # -------------------------

    df = pd.DataFrame(
        [
            {
                "Rank":
                    idx + 1,

                "Brand":
                    p["brand"],

                "ASIN":
                    p["asin"],

                "Rating":
                    p.get(
                        "rating"
                    ),

                "Reviews":
                    p.get(
                        "review_count"
                    ),

                "Price":
                    p.get(
                        "price"
                    ),

                "Similarity":
                    round(
                        p["deep_score"],
                        4
                    ),

                "Title":
                    p["title"]
            }

            for idx, p in enumerate(
                final_results
            )
        ]
    )

    st.subheader(
        "Top Competitors"
    )

    st.dataframe(
        df,
        use_container_width=True
    )

    # -------------------------
    # Similarity Chart
    # -------------------------

    st.subheader(
        "Similarity Scores"
    )

    st.bar_chart(
        df.set_index(
            "Brand"
        )["Similarity"]
    )

    # -------------------------
    # Competitor Details
    # -------------------------

    st.subheader(
        "Competitor Details"
    )

    for p in final_results:

        with st.expander(
            f"{p['brand']} | Similarity {round(p['deep_score'],4)}"
        ):

            st.image(
                p.get(
                    "main_image",
                    ""
                ),
                width=250
            )

            st.write(
                f"**ASIN:** {p['asin']}"
            )

            st.write(
                f"**Brand:** {p['brand']}"
            )

            st.write(
                f"**Price:** ₹{p.get('price')}"
            )

            st.write(
                f"**Rating:** {p.get('rating')}"
            )

            st.write(
                f"**Reviews:** {p.get('review_count')}"
            )

            st.write(
                f"**Similarity:** {round(p['deep_score'],4)}"
            )

            st.write(
                f"**URL:** {p.get('product_url')}"
            )

            st.write(
                f"**Title:** {p['title']}"
            )

            st.write(
                p.get(
                    "description",
                    ""
                )[:1000]
            )