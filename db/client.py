from motor.motor_asyncio import AsyncIOMotorClient

from core.config import MONGO_URI, MONGO_DB_NAME, MONGO_TIMEOUT_MS

_client = None


def get_db():
    """Returns the database handle, reusing the Mongo connection across
    warm serverless invocations instead of reconnecting every request."""
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=MONGO_TIMEOUT_MS)
    return _client[MONGO_DB_NAME]


async def ping_db():
    """Fails fast with a clear message if Mongo isn't reachable, instead of
    letting the first real query blow up deep inside a random handler."""
    await get_db().command("ping")