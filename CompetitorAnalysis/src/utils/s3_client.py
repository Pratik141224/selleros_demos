import io
import json
import os

import s3fs
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
S3_BUCKET = os.getenv("S3_BUCKET")
S3_PREFIX = os.getenv("S3_RAW_PREFIX_CA", "competitor-analysis")


class S3Client:

    def __init__(self):

        self.fs = s3fs.S3FileSystem()
        self.bucket = S3_BUCKET
        self.prefix = S3_PREFIX.rstrip("/")

    def _key(self, path):
        return f"{self.bucket}/{self.prefix}/{path}"

    def exists(self, path):
        return self.fs.exists(self._key(path))

    def get_json(self, path):

        key = self._key(path)

        if not self.fs.exists(key):
            return None

        with self.fs.open(key, "rb") as f:
            return json.loads(f.read().decode("utf-8"))

    def put_json(self, path, data):

        content = json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        ).encode("utf-8")

        with self.fs.open(self._key(path), "wb") as f:
            f.write(content)

    def get_html(self, path):

        key = self._key(path)

        if not self.fs.exists(key):
            return None

        with self.fs.open(key, "rb") as f:
            return f.read().decode("utf-8", errors="replace")

    def put_html(self, path, html):

        with self.fs.open(self._key(path), "wb") as f:
            f.write(html.encode("utf-8"))

    def get_parquet(self, path):

        key = self._key(path)

        if not self.fs.exists(key):
            return None

        with self.fs.open(key, "rb") as f:

            return pd.read_parquet(
                io.BytesIO(f.read())
            )

    def put_parquet(self, path, df):

        buf = io.BytesIO()

        df.to_parquet(buf, index=False)

        buf.seek(0)

        with self.fs.open(self._key(path), "wb") as f:
            f.write(buf.getvalue())


_instance = None


def get_s3():

    global _instance

    if _instance is None:
        _instance = S3Client()

    return _instance
