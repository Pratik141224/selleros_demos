import re

from sentence_transformers import (
    SentenceTransformer
)

from sklearn.metrics.pairwise import (
    cosine_similarity
)


class DeepMatcher:

    def __init__(self):

        self.model = SentenceTransformer(
            "BAAI/bge-small-en-v1.5"
        )

    def clean_text(
        self,
        text
    ):

        if not text:
            return ""

        text = text.lower()

        text = re.sub(
            r"\s+",
            " ",
            text
        )

        return text.strip()

    def build_text(
        self,
        product
    ):

        title = self.clean_text(
            product.get(
                "title",
                ""
            )
        )

        description = (
            self.clean_text(
                product.get(
                    "description",
                    ""
                )
            )
        )

        features = " ".join(

            self.clean_text(
                feature
            )

            for feature in product.get(
                "features",
                []
            )
        )

        return f"""
        {title}

        {description}

        {features}
        """

    def match(
        self,
        seed_product,
        candidate_products
    ):

        seed_text = (
            self.build_text(
                seed_product
            )
        )

        candidate_texts = [

            self.build_text(
                product
            )

            for product in (
                candidate_products
            )
        ]

        seed_embedding = (
            self.model.encode(
                [seed_text],
                normalize_embeddings=True
            )
        )

        candidate_embeddings = (
            self.model.encode(
                candidate_texts,
                normalize_embeddings=True
            )
        )

        scores = (
            cosine_similarity(
                seed_embedding,
                candidate_embeddings
            )[0]
        )

        results = []

        for product, score in zip(
            candidate_products,
            scores
        ):

            results.append(
                {
                    **product,

                    "deep_score":
                        float(score)
                }
            )

        results.sort(
            key=lambda x:
            x["deep_score"],
            reverse=True
        )

        return results