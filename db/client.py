from motor.motor_asyncio import AsyncIOMotorClient

from core.config import MONGO_URI, MONGO_DB_NAME

_client = None


def get_db():
    """Returns the database handle, reusing the Mongo connection across
    warm serverless invocations instead of reconnecting every request."""
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(MONGO_URI)
    return _client[MONGO_DB_NAME]
