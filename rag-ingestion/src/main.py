from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.database import(
    ChunkRow,
    count_cached,
    count_chunks,
    embedding_cache_key,
    get_cached_embeddings,
    put_cached_embeddings,
    count_ingested_sources,
    delete_chunks_by_source,
    init_db,
    insert_chunks,
    source_already_ingested,
)
from src.gemini_client import(
    EmbeddingCircuitOpenError,
    EmbeddingError,
    EmbeddingModelNotFoundError,
    EmbeddingQuotaExhaustedError,
    GeminiEmbeddingClient,
    _resumo,
)
from src.pdf_processor import discover_pdfs, extract_and_chunk

logger = logging.getLogger(__name__)

def configure_logging()->None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s |  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )

def _env_int(name:str, default:int)->int:
    raw=os.getenv(name)
    if raw is None or raw.strip()=="":
        return default
    return int(raw)

def _env_bool(name:str, default: bool)->bool:
    raw=os.getenv(name)
    if raw is None or raw.strip()=="":
        return default
    return raw.strip().lower() in {"1","true","yes","y","on"}

def _relative_source(pdf_path:Path, data_dir:Path)->str:
    return pdf_path.resolve().relative_to(data_dir.resolve()).as_posix()

def process_pdf(
        pdf_path:Path,
        data_dir:Path,
        client: GeminiEmbeddingClient,
        chunk_size:int,
        chunk_overlap:int,
        skip_ingested:bool,
)->tuple[str, int]:
    source_path=_relative_source(pdf_path, data_dir)
    if skip_ingested and source_already_ingested(source_path):
        logger.info("Arquivo já ingerido, pulando %s", source_path)
        return "skipped", 0

    chunks=extract_and_chunk(
        pdf_path=pdf_path,
        data_dir=data_dir,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    if not chunks:
        logger.warning(
            "Nenhum trecho gerado para %s; pulando", pdf_path
        )
        return "skipped", 0

    source_path=chunks[0].source_path
    texts=[chunk.content for chunk in chunks]
    model=client.model
    keys=[embedding_cache_key(text, model) for text in texts]
    cached=get_cached_embeddings(keys)
    faltando=[i for i, k in enumerate(keys) if k not in cached]
    if cached:
        logger.info(
            "Cache: %s de %s chunks ja embeddados; faltam %s",
            len(texts)-len(faltando), len(texts), len(faltando),
        )

    def __persistir(batch_texts, batch_vectors):
        put_cached_embeddings([
            (embedding_cache_key(bt, model), bv, model)
            for bt, bv in zip(batch_texts, batch_vectors, strict=True)
        ])

    try:
        if faltando:
            novos=client.embed_texts([texts[i] for i in faltando], on_batch=__persistir)
            for i, vec in zip(faltando, novos, strict=True):
                cached[keys[i]]=vec
        embeddings=[cached[k] for k in keys]
    except (EmbeddingCircuitOpenError, EmbeddingQuotaExhaustedError):
        raise
    except EmbeddingModelNotFoundError as exc:
        logger.error("Modelo de embedding nao encontrado (404) em %s | %s",
                     source_path, _resumo(exc))
        logger.debug("Traceback completo", exc_info=True)
        return "error", 0
    except EmbeddingError as exc:
        logger.error("Embedding falhou em %s -> %s", source_path, _resumo(exc))
        logger.debug("Traceback completo", exc_info=True)
        return "error", 0

    rows=[
        ChunkRow(
            content=chunk.content,
            embedding=embedding,
            company=chunk.company,
            year=chunk.year,
            quarter=chunk.quarter,
            doc_type=chunk.doc_type,
            page_number=chunk.page_number,
            source_path=chunk.source_path,
            section_title=chunk.section_title,
            scope=chunk.scope,
            scale=chunk.scale,
            currency=chunk.currency,
            scale_source=chunk.scale_source,
            printed_page_label=chunk.printed_page_label,
            content_type=chunk.content_type,
            context_header=chunk.context_header,
            chunk_index=chunk.chunk_index,
        )
        for chunk, embedding in zip(chunks, embeddings, strict=True)
    ]

    delete_chunks_by_source(source_path)
    inserted=insert_chunks(rows)
    logger.info("Ingestão concluída %s (%s chunks)", source_path, inserted)
    return "processed", inserted

def run()->int:
    load_dotenv()
    configure_logging()
    data_dir=Path(os.getenv("DATA_DIR", "/data"))
    chunk_size=_env_int("CHUNK_SIZE", 1000)
    chunk_overlap=_env_int("CHUNK_OVERLAP", 200)
    skip_ingested=_env_bool("SKIP_INGESTED", True)

    init_db()
    logger.info(
        "Situação do banco | arquivos=%s chunks=%s embeddings em cache=%s",
        count_ingested_sources(),
        count_chunks(),
        count_cached(),
    )

    try:
        client=GeminiEmbeddingClient()
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    pdfs=discover_pdfs(data_dir)
    only_source=os.getenv("ONLY_SOURCE", "").strip()
    if only_source:
        needle=only_source.lower()
        pdfs=[p for p in pdfs if needle in _relative_source(p, data_dir).lower()]
        logger.info("ONLY_SOURCE='%s' -> %s PDF(s) selecionado(s)", only_source, len(pdfs))

    if not pdfs:
        logger.warning("Nenhum arquivo PDF encontrado em %s", data_dir)
        return 0

    if _env_bool("QUOTA_PROBE", True):
        try:
            client.probe_quota()
        except EmbeddingQuotaExhaustedError as exc:
            logger.error("%s", exc)
            return 1
        except EmbeddingError:
            logger.exception("A verificação de cota falhou! (O problema não é falta de cota)")
            return 1

    processed=0
    skipped=0
    errors=0
    total_chunks=0
    consecutive_errors=0
    max_consecutive_errors=_env_int("MAX_CONSECUTIVE_ERRORS", 2)

    for index, pdf_path in enumerate(pdfs, start=1):
        logger.info("[%s/%s] Processando %s", index, len(pdfs), pdf_path)
        try:
            status, chunk_count=process_pdf(
                pdf_path=pdf_path,
                data_dir=data_dir,
                client=client,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                skip_ingested=skip_ingested,
            )
        except (EmbeddingCircuitOpenError, EmbeddingQuotaExhaustedError) as exc:
            logger.error("Interrupção de segurança: %s", exc)
            logger.info(
                "Ingestão interrompida | processados=%s pulados=%s erros=%s total_chunks=%s",
                processed,
                skipped,
                errors+1,
                total_chunks,
            )
            return 1
        except Exception as exc:
            logger.error("Erro nao tratado em %s -> %s", pdf_path, _resumo(exc))
            logger.debug("Traceback completo", exc_info=True)
            errors+=1
            continue

        if status=="processed":
            processed+=1
            total_chunks+=chunk_count
            consecutive_errors=0
        elif status == "skipped":
            skipped+=1
        else:
            errors+=1
            consecutive_errors+=1
            if consecutive_errors>=max_consecutive_errors:
                logger.error(
                    "Abortando: %s arquivos consecutivos falharam ao gerar embeddings. Verifique "
                    "a cota de uso. ",
                    consecutive_errors
                )
                logger.info(
                    "Ingestão interrompida | processados=%s pulados=%s erros=%s total_chunks=%s",
                    processed, skipped, errors, total_chunks,
                )
                return 1

    logger.info(
        "Ingestão interrompida | processados=%s pulados=%s erros=%s total_chunks=%s",
        processed, 
        skipped, 
        errors, 
        total_chunks,
    )
    return 1 if errors else 0

if __name__ == "__main__":
    sys.exit(run())
