import os
from dotenv import load_dotenv

load_dotenv()

ZYTE_API_KEY = os.getenv("ZYTE_API_KEY")

if not ZYTE_API_KEY:
    raise ValueError("ZYTE_API_KEY not found in .env")

S3_BUCKET = os.getenv("S3_BUCKET")
S3_PREFIX = os.getenv("S3_RAW_PREFIX_CA", "competitor-analysis")

if not S3_BUCKET:
    raise ValueError("S3_BUCKET not found in .env")

