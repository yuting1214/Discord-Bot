import os
from contextlib import contextmanager

import meilisearch


@contextmanager
def meilisearch_client():
    host: str = os.getenv("MEILI_HOST")
    api_key: str = os.getenv("MEILI_MASTER_KEY")
    client = meilisearch.Client(host, api_key)
    try:
        yield client
    finally:
        pass