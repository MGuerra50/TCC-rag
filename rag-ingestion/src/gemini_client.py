from __future__ import annotations
import logging
import os
import re
import time
from collections import deque
from typing import Deque, Sequence

import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from src.database import EMBEDDING_DIMENSION

logger=logging.getLogger(__name__)

EMBEDDING_MODEL=os.getenv("EMBEDDING_MODEL", "models/gemini-embedding-001")
MAX_CONSECUTIVE_404=int(os.getenv("MAX_CONSECUTIVE_404", "5"))
MAX_EMBEDDING_PER_MINUTE=int(os.getenv("MAX_EMBEDDING_PER_MINUTE", "80"))
MAX_429_RETRIES=int(os.getenv("MAX_429_RETRIES", "10"))

class EmbeddingError(Exception):
    """Raised when embedding generation fails after retries."""

class EmbeddingModelNotFoundError(EmbeddingError):
    """Raised when embedding model returns HTTP 404 / NotFound."""

class EmbeddingCircuitOpenError(EmbeddingError):
    """Raised when too many consecutive 404s abort the pipeline."""

def _env_int (name: str, default: int)->int:
    raw=os.getenv(name)
    if raw is None or raw.strip()=="":
        return default
    return int(raw)

def _parse_retry_seconds(exc:Exception, default:float=60.0)->float:
    """Extract the API-suggested wait time from a 429 error message."""
    message=str(exc)
    match=re.search(r"retry in ([\d.]+)\s*s", message, re.IGNORECASE)
    if match:
        return max(float(match.group(1)), 1.0)
    match=re.search(r"retry_delay\s*{\s*seconds:\s*(\d+)", message)
    if match:
        return max(float(match.group(1)), 1.0)
    return default

class SlidingWindowRateLimiter:
    def __init__(self, max_per_minute:int)->None:
        if max_per_minute<1:
            raise ValueError("max_per_minute must be >= 1")
        self.max_per_minute=max_per_minute
        self._timestamps: Deque[float]=deque()

    def _prune(self, now:float)->None:
        while self._timestamps and now - self._timestamps[0]>=60.0:
            self._timestamps.popleft()

    def acquire(self, n: int)->None:
        if n < 1:
            return
        if n>self.max_per_minute:
            raise EmbeddingError(
                f"Batch size {n} exceeds MAX_EMBEDDING_PER_MINUTE="
                f"{self.max_per_minute}. Reduce EMBEDDING_BATCH_SIZE."
            )
        while True:
            now = time.monotonic()
            self._prune(now)
            used=len(self._timestamps)
            if used+n<=self.max_per_minute:
                stamp=time.monotonic()
                for _ in range(n):
                    self._timestamps.append(stamp)
                return

            release_index = used+n-self.max_per_minute-1
            release_index=min(max(release_index, 0), used-1)
            wait = 60.0 - (now - self._timestamps[release_index])+0.1
            wait = max(wait, 0.1)
            logger.info("Rate limit pause: waiting %.1fs (%s/%s embeddings in last 60s, need %s)",
                wait,
                used,
                self.max_per_minute,
                n,
            )
            time.sleep(wait)

class GeminiEmbeddingClient:

    def __init__(
        self,
        api_key:str|None= None,
        batch_size:int|None=None,
        model:str|None=None,
        max_consecutive_404:int|None=None,
        max_per_minute:int|None=None,
        )->None:
        key=(
            api_key
            or os.getenv("GeminiAPIKeyRAG")
            or os.getenv("GOOGLE_API_KEY") 
        )
        if not key or key == "your_gemini_api_key_here":
            raise ValueError(
                "API key not set. Define GeminiAPIKeyRAG (or GOOGLE_API_KEY)"
                "in the environment / .env."
            )
        genai.configure(api_key=key)
        self.model=model or EMBEDDING_MODEL
        configured_batch=batch_size or _env_int("EMBEDDING_BATCH_SIZE", 40)
        self.max_per_minute=max_per_minute or _env_int(
            "MAX_EMBEDDING_PER_MINUTE", MAX_EMBEDDING_PER_MINUTE
        )
        self.batch_size=min(configured_batch, self.max_per_minute)
        self.max_consecutive_404 = (
            max_consecutive_404
            if max_consecutive_404 is not None
            else _env_int("MAX_CONSECUTIVE_404", MAX_CONSECUTIVE_404)
        )
        self._consecutive_404=0
        self._rate_limiter=SlidingWindowRateLimiter(self.max_per_minute)
        logger.info(
            "Gemini embeddings ready | model=%s dim=%s batch_size=%s max_per_minute=%s",
            self.model,
            EMBEDDING_DIMENSION,
            self.batch_size,
            self.max_per_minute,
        )

    def _register_404(self, exc:Exception)->EmbeddingModelNotFoundError:
        self._consecutive_404 += 1
        logger.error(
            "Embedding 404 (%s/%s): %s",
            self._consecutive_404,
            self.max_consecutive_404,
            exc,
        )
        if self._consecutive_404>=self.max_consecutive_404:
            raise EmbeddingCircuitOpenError(
                f"Aborting after {self._consecutive_404} consecutive 404 erros " 
                f"for model '{self.model}'. Check EMBEDDING_MODEL / API access."
            ) from exc
        return EmbeddingModelNotFoundError(str(exc))

    def _register_sucess(self)->None:
        self._consecutive_404=0

    def _embed_batch_once(self, texts: Sequence[str])->list[list[float]]:
        result=genai.embed_content(
            model=self.model,
            content=list(texts),
            task_type="retrieval_document",
            output_dimensionality=EMBEDDING_DIMENSION,
        )

        embeddings=result.get("embedding")
        if embeddings is None:
            raise EmbeddingError(f"Unexpected embed_context response: {result}")
        if embeddings and isinstance(embeddings[0], (int, float)):
            vectors = [list(embeddings)]
        else:
            vectors=[list(vec) for vec in embeddings]

        for idx, vector in enumerate(vectors):
            if len(vector) != EMBEDDING_DIMENSION:
                raise EmbeddingError(
                    f"Embedding dim mismatch at batch index {idx}: "
                    f"expected {EMBEDDING_DIMENSION}, got {len(vector)}"
                )
            return vectors
        def _embed_batch_with_retries(self, texts: Sequence[str])->list[list[float]]:
            attempts=0
            while True:
                try:
                    return self._embed_batch_once(texts)
                except google_exceptions.ResourceExhausted as exc:
                    attempts+=1
                    delay=_parse_retry_seconds(exc)+1.0
                    if attempts>MAX_429_RETRIES:
                        raise EmbeddingError(
                            f"Rate limit persisted after {attempts} attempts: {exc}"
                        ) from exc
                    logger.warning(
                        "429 quota exceeded (attempt %s/%s); sleeping %.1fs as suggested by API",
                        attempts,
                        MAX_429_RETRIES,
                        delay,
                    )
                    time.sleep(delay)
                except(
                    google_exceptions.ServiceUnvailable,
                    google_exceptions.InternalServerError,
                    google_exceptions.DeadlineExceeded,
                    ConnectionError,
                    TimeoutError,
                ) as exc:
                    attempts += 1
                    delay=min(2**attempts, 60)
                    if attempts > MAX_429_RETRIES:
                        raise EmbeddingError(
                            f"Transient embedding error after {attempts} attempts: {exc}"
                        ) from exc
                    logger.warning(
                        "Transient embedding error (attempts %s/%s); sleeping %.1fs: %s",
                        attempts,
                        MAX_429_RETRIES,
                        delay,
                        exc,
                    )
                    time.sleep(delay)

    def embed_texts(self, texts: Sequence[str])->list[list[float]]:
        if not texts:
            return []

        all_embeddings: list[list[float]]=[]
        total=len(texts)
        total_batches=(total+self.batch_size-1)//self.batch_size

        for batch_idx in range(total_batches):
            start=batch_idx*self.batch_size
            end=min(start+self.batch_size, total)
            batch=texts[start:end]
            logger.info(
                "Embedding batch %s/%s (%s texts)",
                batch_idx + 1,
                total_batches,
                len(batch),
            )
            self._rate_limiter.acquire(len(batch))
            try:
                vectors=self._embed_batch_with_retries(batch)
            except google_exceptions.NotFound as exc:
                raise self._register_404(exc) from exc
            except EmbeddingCircuitOpenError:
                raise
            except EmbeddingError:
                raise
            except Exception as exc:
                message=str(exc)
                if "404" in message or "not found" in message.lower():
                    raise self._register_404(exc) from exc
                logger.error(
                    "Failed to embed batch %s/%s: %s",
                    batch_idx+1,
                    total_batches,
                    exc,
                )
                raise EmbeddingError(str(exc)) from exc

            if len(vectors) != len(batch):
                raise EmbeddingError(
                    f"Batch size mismatch: sent {len(batch)}, got {len(vectors)}"
                )
            all_embeddings.extend(vectors)
            self._register_sucess()

        logger.info("Generated %s embeddings", len(all_embeddings))
        return all_embeddings