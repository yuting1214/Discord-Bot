"""Query and document embeddings.

Uses the same provider client as the chat layer. Embedding failures are not
fatal: search degrades to keyword-only rather than taking the command down with
it, which is the behaviour a chat bot wants.
"""

import logging

from src.config import bot_config

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = bot_config.embeddings.model

# text-embedding-3-small. Changing the model means changing this and rebuilding
# every stored embedding: the column is fixed-width and distances between
# vectors from different models are meaningless.
EMBEDDING_DIM = bot_config.embeddings.dimensions


async def embed(text: str) -> list[float] | None:
    """Return the embedding for ``text``, or None if it could not be produced."""
    if not text.strip():
        return None
    try:
        from src.llm.client import get_async_client

        response = await get_async_client("openai").embeddings.create(
            model=EMBEDDING_MODEL, input=text
        )
        return response.data[0].embedding
    except Exception:
        logger.warning("Embedding failed; falling back to keyword search", exc_info=True)
        return None
