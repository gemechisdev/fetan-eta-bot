from datetime import timezone

from motor.motor_asyncio import AsyncIOMotorClient

from core.config import MONGO_URI, MONGO_DB_NAME, MONGO_TIMEOUT_MS

_client = None


def get_db():
    """Returns the database handle, reusing the Mongo connection across
    warm serverless invocations instead of reconnecting every request."""
    global _client
    if _client is None:
        # tz_aware=True (+ tzinfo=UTC) makes every BSON date PyMongo/Motor
        # decodes come back as an *aware* UTC datetime. Without this, dates
        # are decoded as naive datetimes while db/repository.py's utcnow()
        # writes timezone-aware ones — comparing the two (e.g. "is this
        # pending reservation older than the TTL cutoff?") then raises
        # "can't compare offset-naive and offset-aware datetimes", which was
        # being silently swallowed by callers' try/except, so pending
        # numbers never actually expired.
        _client = AsyncIOMotorClient(
            MONGO_URI,
            serverSelectionTimeoutMS=MONGO_TIMEOUT_MS,
            tz_aware=True,
            tzinfo=timezone.utc,
        )
    return _client[MONGO_DB_NAME]


async def ping_db():
    """Fails fast with a clear message if Mongo isn't reachable, instead of
    letting the first real query blow up deep inside a random handler."""
    await get_db().command("ping")