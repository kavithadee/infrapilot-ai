import hashlib
import json
import time
from abc import ABC, abstractmethod
from typing import Type
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.redis_client import redis_get, redis_set
from app.db import repositories as repo

logger = get_logger(__name__)


class BaseTool(ABC):
    """
    Every infrastructure tool inherits from this class and only implements execute().

    The base run() method handles the full lifecycle:
      1. Build cache key
      2. Check Redis (miss → execute; hit → skip execute)
      3. Cache the result
      4. Log the tool call to Postgres with latency + cache_hit flag
      5. Return the result dict

    Redis failures degrade gracefully — redis_get/redis_set never raise,
    so a down Redis just means every call is a cache miss.
    """

    name: str
    description: str
    input_schema: Type[BaseModel]
    output_schema: Type[BaseModel]
    cache_ttl: int = 300  # seconds; 0 = no cache

    @abstractmethod
    def execute(self, input: BaseModel, db: Session) -> BaseModel:
        """Query the simulated DB and return a validated output_schema instance."""
        ...

    def _build_cache_key(self, raw_input: dict) -> str:
        """
        Default cache key: {tool_name}:{md5(sorted_input_json)}.
        Override in subclasses for human-readable keys (see plan cache key conventions).
        """
        stable = json.dumps(raw_input, sort_keys=True, default=str)
        digest = hashlib.md5(stable.encode()).hexdigest()
        return f"{self.name}:{digest}"

    def run(
        self,
        raw_input: dict,
        db: Session,
        run_id: UUID,
        sequence_num: int,
    ) -> dict:
        """
        Execute the tool with caching and DB logging.

        Args:
            raw_input:    The raw dict of tool arguments from the OpenAI tool call.
            db:           SQLAlchemy session (injected by the agent).
            run_id:       The InvestigationRun UUID — used to associate the log row.
            sequence_num: Ordered position of this call in the run (1-based).

        Returns:
            The tool result as a plain dict (JSON-serialisable).
        """
        start = time.time()

        # ------------------------------------------------------------------
        # 0. Validate input up-front (before cache check so cache hits are
        #    also gated on valid input — prevents stale results masking bad
        #    arguments when the cache key omits a field).
        # ------------------------------------------------------------------
        validated_input = self.input_schema(**raw_input)

        cache_key = self._build_cache_key(raw_input)
        cache_hit = False
        result: dict | None = None

        # ------------------------------------------------------------------
        # 1. Redis cache check
        # ------------------------------------------------------------------
        if self.cache_ttl > 0:
            cached = redis_get(cache_key)
            if cached is not None:
                try:
                    result = json.loads(cached)
                    cache_hit = True
                    logger.info("cache_hit", tool=self.name, key=cache_key)
                except json.JSONDecodeError:
                    # Corrupt cache entry — fall through and re-execute
                    result = None

        # ------------------------------------------------------------------
        # 2. Execute on cache miss
        # ------------------------------------------------------------------
        if not cache_hit:
            try:
                output = self.execute(validated_input, db)
                result = output.model_dump()
            except Exception as e:
                latency_ms = int((time.time() - start) * 1000)
                try:
                    repo.log_tool_call(
                        db,
                        run_id=run_id,
                        tool_name=self.name,
                        input_json=raw_input,
                        output_json=None,
                        latency_ms=latency_ms,
                        cache_hit=False,
                        sequence_num=sequence_num,
                        status="error",
                        error_message=str(e),
                    )
                except Exception as log_err:
                    # Never let a logging failure hide the original tool error.
                    logger.warning(
                        "tool_call_log_failed",
                        tool=self.name,
                        log_error=str(log_err),
                    )
                logger.error(
                    "tool_execute_failed",
                    tool=self.name,
                    sequence_num=sequence_num,
                    error=str(e),
                )
                raise

            # ------------------------------------------------------------------
            # 3. Cache the result
            # ------------------------------------------------------------------
            if self.cache_ttl > 0:
                redis_set(cache_key, json.dumps(result, default=str), self.cache_ttl)

        # ------------------------------------------------------------------
        # 4. Persist tool call to Postgres
        # ------------------------------------------------------------------
        latency_ms = int((time.time() - start) * 1000)
        repo.log_tool_call(
            db,
            run_id=run_id,
            tool_name=self.name,
            input_json=raw_input,
            output_json=result,
            latency_ms=latency_ms,
            cache_hit=cache_hit,
            sequence_num=sequence_num,
            status="success",
        )

        logger.info(
            "tool_call_complete",
            tool=self.name,
            latency_ms=latency_ms,
            cache_hit=cache_hit,
            sequence_num=sequence_num,
        )

        return result
