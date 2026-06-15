import re

from sentence_transformers import (
    SentenceTransformer
)

from sklearn.metrics.pairwise import (
    cosine_similarity
)


class TitleMatcher:

    def __init__(self):

        self.model = SentenceTransformer(
            "BAAI/bge-small-en-v1.5"
        )

    def clean_title(self, title):

        title = title.lower()

        remove_phrases = [
            "buy",
            "amazon.in",
            "online at low prices in india"
        ]

        for phrase in remove_phrases:

            title = title.replace(
                phrase,
                ""
            )

        title = re.sub(
            r"\s+",
            " ",
            title
        )

        return title.strip()

    def match(
        self,
        seed_title,
        products
    ):

        seed_title = self.clean_title(
            seed_title
        )

        candidate_titles = [
            self.clean_title(
                p["title"]
            )
            for p in products
        ]

        seed_embedding = self.model.encode(
            [seed_title],
            normalize_embeddings=True
        )

        candidate_embeddings = self.model.encode(
            candidate_titles,
            normalize_embeddings=True
        )

        scores = cosine_similarity(
            seed_embedding,
            candidate_embeddings
        )[0]

        results = []

        for product, score in zip(
            products,
            scores
        ):

            results.append(
                {
                    **product,
                    "similarity_score": float(score)
                }
            )

        results.sort(
            key=lambda x: x["similarity_score"],
            reverse=True
        )

        return results