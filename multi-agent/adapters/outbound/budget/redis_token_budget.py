"""Redis-backed ``TokenBudgetStore``: the nodes of one turn run in different worker activities.

Keys: ``budget:tokens:{session}:{engine_handle}`` (INCRBY, TTL) and ``budget:announced:{...}`` (SET NX, TTL).
"""
from redis import ConnectionPool, Redis

from mas.elements.llms.common.token_budget import TokenBudgetStore

_PREFIX = "budget:tokens:"
_ANNOUNCED = "budget:announced:"
_TTL = 86_400


class RedisTokenBudgetStore(TokenBudgetStore):
    def __init__(self, redis_url: str, ttl: int = _TTL) -> None:
        self._pool = ConnectionPool.from_url(redis_url, socket_timeout=30)
        self._ttl = ttl

    def _redis(self) -> Redis:
        return Redis(connection_pool=self._pool)

    def add(self, turn_key: str, tokens: int) -> int:
        key, redis = f"{_PREFIX}{turn_key}", self._redis()
        total = int(redis.incrby(key, max(0, int(tokens))))
        redis.expire(key, self._ttl)
        return total

    def used(self, turn_key: str) -> int:
        raw = self._redis().get(f"{_PREFIX}{turn_key}")
        return int(raw) if raw is not None else 0

    def announce_once(self, turn_key: str) -> bool:
        return bool(self._redis().set(f"{_ANNOUNCED}{turn_key}", "1", nx=True, ex=self._ttl))
