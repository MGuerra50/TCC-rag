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
EMBEDDING_TIMEOUT=int(os.getenv("EMBEDDING_TIMEOUT", "180"))
MAX_DEADLINE_RETRIES=int(os.getenv("MAX_DEADLINE_RETRIES", "2"))

class EmbeddingError(Exception):
    """Raised when embedding generation fails after retries."""

class EmbeddingModelNotFoundError(EmbeddingError):
    """Raised when embedding model returns HTTP 404 / NotFound."""

class EmbeddingCircuitOpenError(EmbeddingError):
    """Raised when too many consecutive 404s abort the pipeline."""

class EmbeddingQuotaExhaustedError(EmbeddingError):
    """Raised by the up-front probe when the account has no quota left."""

class EmbeddingBatchTooLargeError(EmbeddingError):
    """Raised when the batch is refused but a single item still succeeds."""

def _resumo(exc: BaseException)->str:
    partes: list[str]=[]
    atual: BaseException|None=exc
    vistos: set[int]=set()
    while atual is not None and id(atual) not in vistos:
        vistos.add(id(atual))
        texto=str(atual).strip().splitlines()
        primeira=texto[0] if texto else atual.__class__.__name__
        partes.append(f"{atual.__class__.__name__}: {primeira[:160]}")
        atual=atual.__cause__
    return " <- ".join(partes[:3])



def _env_int (name: str, default: int)->int:
    raw=os.getenv(name)
    if raw is None or raw.strip()=="":
        return default
    return int(raw)

_DAILY_QUOTA = re.compile(r"PerDay|RequestsPerDay", re.IGNORECASE)

def _is_daily_quota(exc: Exception)->bool:
    return bool(_DAILY_QUOTA.search(str(exc)))

def _parse_retry_seconds(exc:Exception, default:float=60.0)->float:
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
            raise ValueError("max_per_minute deve ser >= 1")
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
                f"O lote de {n} itens excede MAX_EMBEDDING_PER_MINUTE="
                f"{self.max_per_minute}. Reduza EMBEDDING_BATCH_SIZE."
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
            logger.info("Pausa por limite de requisição: aguardando %.1fs (%s/%s embeddings nos últimos 60s, necessários %s)",
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
            or os.getenv("GEMINI_API_KEY") 
            or os.getenv("GOOGLE_API_KEY") 
        )
        if not key or key == "your_gemini_api_key_here":
            raise ValueError(
                "A chave da API não definida. Defina GeminiAPIKeyRAG ou GEMINI_API_KEY ou GOOGLE_API_KEY"
                "no ambiente ou no arquivo .env."
            )
        genai.configure(api_key=key)
        self.model=model or EMBEDDING_MODEL
        configured_batch=batch_size or _env_int("EMBEDDING_BATCH_SIZE", 40)
        self.max_per_minute=max_per_minute or _env_int(
            "MAX_EMBEDDING_PER_MINUTE", MAX_EMBEDDING_PER_MINUTE
        )
        self.batch_size=min(configured_batch, self.max_per_minute)
        self.min_batch=max(1, _env_int("EMBEDDING_MIN_BATCH", 20))
        self.min_batch=min(self.min_batch, self.batch_size)
        self.max_consecutive_404 = (
            max_consecutive_404
            if max_consecutive_404 is not None
            else _env_int("MAX_CONSECUTIVE_404", MAX_CONSECUTIVE_404)
        )
        self._consecutive_404=0
        self._rate_limiter=SlidingWindowRateLimiter(self.max_per_minute)
        logger.info(
            "Gemini embeddings prontos | modelo=%s dimensão=%s tamanho_lote=%s max_por_minuto=%s",
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
                f"Abortando após {self._consecutive_404} consecutivo erros 404 " 
                f"para o modelo '{self.model}'. Verifique EMBEDDING_MODEL e o acesso da API."
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
            request_options={"timeout": EMBEDDING_TIMEOUT},
        )

        embeddings=result.get("embedding")
        if embeddings is None:
            raise EmbeddingError(f"Resposta inesperada do embed_context: {result}")
        if embeddings and isinstance(embeddings[0], (int, float)):
            vectors = [list(embeddings)]
        else:
            vectors=[list(vec) for vec in embeddings]

        for idx, vector in enumerate(vectors):
            if len(vector) != EMBEDDING_DIMENSION:
                raise EmbeddingError(
                    f"Dimensão do Embedding incorreta no indice {idx}: "
                    f"do lote {EMBEDDING_DIMENSION}, recebido {len(vector)}"
                )
        return vectors
    def _embed_batch_with_retries(self, texts: Sequence[str])->list[list[float]]:
        attempts=0
        while True:
            try:
                return self._embed_batch_once(texts)
            except google_exceptions.ResourceExhausted as exc:
                if _is_daily_quota(exc):
                    raise EmebeddingQuotaExhaustedError(
                        "A cota diária do serviço de embedding foi atingida. "
                        "Detalhe: %s" % exc
                    ) from exc    
                attempts+=1
                delay=min(max(_parse_retry_seconds(exc), 60.0) * attempts, 300.0)
                if attempts>MAX_429_RETRIES:
                    try:
                        self._embed_batch_once(["verificacao de cota"])
                    except google_exceptions.ResourceExhausted:
                        raise EmbeddingQuotaExhaustedError(
                            "A cota de uso do serviço de embeddings da API utilizada foi atingida "
                            "(recusada após %s tentativas)" % attempts
                        ) from exc
                    raise EmbeddingBatchLargeError(
                        f"Lote de {len(texts)} itens recusados após {attempts} "
                        f"tentativas. Detalhes: {exc}"
                    ) from exc 
                logger.warning(
                    "[ 429 ] Cota excedida (tentativas %s/%s); aguardando %.1fs como sugerido pela API",
                    attempts,
                    MAX_429_RETRIES,
                    delay,
                )
                time.sleep(delay)
            except(
                google_exceptions.ServiceUnavailable,
                google_exceptions.InternalServerError,
                google_exceptions.DeadlineExceeded,
                ConnectionError,
                TimeoutError,
            ) as exc:
                    attempts += 1
            if (
                isinstance(exc, google_exceptions.DeadlineExceeded)
                and attempts >= MAX_DEADLINE_RETRIES
                and len(texts) > self.min_batch
            ):
                raise EmbeddingBatchLargeError(
                    f"Lote de {len(texts)} itens excedeu o tempo limit {attempts}x seguidas "
                    f"({EMBEDDING_TIMEOUT}s cada). "
                ) from exc
            delay=min(2**attempts, 60)
            if attempts>MAX_429_RETRIES:
                raise EmbeddingError(
                    f"Erro transitório de embeddings após {attempts} tentativas: {exc}"
                ) from exc
            logger.warning(
                "Erro transitório de embedding (tentativas %s/%s); aguardando %.1fs: %s",
                attempts,
                MAX_429_RETRIES,
                delay,
                _resumo(exc),
            )
            time.sleep(delay)

    def probe_quota(self)->None:
        try:
            self._embed_batch_once(["verificacao de cota"])
        except google_exceptions.ResourceExhausted as exc:
            raise EmbeddingQuotaExhaustedError(
                "A cota de embeddings dessa chave API está esgotada."
            ) from exc 
        logger.info("Verificação de cota está OK, os embeddings estão sendo aceitos.")

    def embed_group(self, texts: Sequence[str])->list[list[float]]:
        try:
            return self._embed_batch_with_retries(texts)
        except EmbeddingBatchTooLargeError:
            if len(texts) <= self.min_batch:
                raise EmbeddingQuotaExhaustedError(
                    f"Lote de {len(texts)} itens recusados, mesmo no tamanho mínimo "
                    f"({self.min_batch})."
                )
            half=max(self.min_batch, len(texts)//2)
            logger.warning(
                "Lote de %s itens recusados; dividindo em %s + %s e tentando novamente",
                len(texts), half, len(texts)-half,
            )
            self.batch_size=max(self.min_batch, min(self.batch_size, half))
            out=self._embed_group(texts[:half])
            out.extend(self.embed_group(texts[half:]))
            return out


    def embed_texts(self, texts: Sequence[str], on_batch=None)->list[list[float]]:
        if not texts:
            return []

        all_embeddings: list[list[float]]=[]
        total=len(texts)
        cursor=0
        batch_no=0

        while cursor < total:
            size=max(1, self.batch_size)
            batch=texts[cursor:cursor+size]
            batch_no+=1
            logger.info(
                "Lote de embedding %s (%s textos) | %s/%s concluidos",
                batch_no,
                len(batch),
                cursor,
                total,
            )
            self._rate_limiter.acquire(len(batch))
            try:
                vectors=self._embed_group(batch)
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
                logger.error("Falha ao gerar embeddings do lote %s: %s", batch_no, exc)
                raise EmbeddingError(str(exc)) from exc

            if len(vectors) != len(batch):
                raise EmbeddingError(
                    f"Tamanho do lote divergente: enviados {len(batch)}, recebidos {len(vectors)}"
                )
            all_embeddings.extend(vectors)

            if on_batch is not None:
                on_batch(list(batch), vectors)
            cursor+=len(batch)
            self._register_sucess()

        if len(all_embeddings) != total:
            raise EmbeddingError(
                f"Foram gerados {len(all_embeddings)} embeddings para {total} textos"
            )

        logger.info("%s embeddings gerados", len(all_embeddings))
        return all_embeddings