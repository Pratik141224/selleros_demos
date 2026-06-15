from src.services.competitor_service import (
    find_competitors
)

seed_asin = input(
    "\nEnter ASIN: "
).strip()

result = (
    find_competitors(
        seed_asin
    )
)

print(result)