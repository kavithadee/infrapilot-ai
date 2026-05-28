import redis as redis_lib

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_redis_client: redis_lib.Redis | None = None
_redis_unavailable: bool = False  # set True on first connection failure; prevents retry-on-every-call


def get_redis() -> redis_lib.Redis | None:
    """
    Return the shared Redis client, or None if the connection failed.
    Callers must handle None gracefully (skip cache, log warning).

    After the first failed connection attempt _redis_unavailable is set to True
    and all subsequent calls return None immediately (no reconnect retry), avoiding
    the 2-4s socket timeout penalty on every cache operation when Redis is down.
    """
    global _redis_client, _redis_unavailable
    if _redis_unavailable:
        return None
    if _redis_client is None:
        try:
            client = redis_lib.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            client.ping()
            _redis_client = client
            logger.info("redis_connected", url=settings.redis_url)
        except Exception as e:
            logger.warning("redis_unavailable", error=str(e))
            _redis_unavailable = True
            return None
    return _redis_client


def redis_get(key: str) -> str | None:
    """Return cached value for key, or None on miss or Redis error."""
    client = get_redis()
    if client is None:
        return None
    try:
        return client.get(key)
    except Exception as e:
        logger.warning("redis_get_failed", key=key, error=str(e))
        return None


def redis_set(key: str, value: str, ttl: int) -> None:
    """Set key with TTL (seconds). Silently skips if Redis is unavailable."""
    client = get_redis()
    if client is None:
        return
    try:
        client.setex(key, ttl, value)
    except Exception as e:
        logger.warning("redis_set_failed", key=key, error=str(e))


def redis_delete(key: str) -> None:
    """Delete a key. Silently skips if Redis is unavailable."""
    client = get_redis()
    if client is None:
        return
    try:
        client.delete(key)
    except Exception as e:
        logger.warning("redis_delete_failed", key=key, error=str(e))
