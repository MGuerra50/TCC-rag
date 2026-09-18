from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.database import(
    ChunkRow,
    count_chunks,
    count_ingested_sources,
    delete_chunks_by_source,
    init_db,
    source_already_ingested,
)
from src.gemini_client import(
    EmbeddingCircuitOpenError,
    EmbeddingError,
    EmbeddingModelNotFoundError,
    GeminiEmbeddingClient,
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
        logger.info("Already ingested, skipping %s", source_path)
        return "skipped", 0

    chunks=extract_and_chunk(
        pdf_path=pdf_path,
        data_dir=data_dir,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    if not chunks:
        logger.warning(
            "No chunks produced for %s; skipping", pdf_path
        )
        return "skipped", 0

    source_path=chunks[0].source_path
    texts=[chunk.content for chunk in chunks]

    try: 
        embeddings=client.embed_texts(texts)
    except EmbeddingCircuitOpenError:
        raise
    except EmbeddingModelNotFoundError:
        logger.exception("Embedding model not found (404) for %s", source_path)
        return "error", 0
    except EmbeddingError:
        logger.exception("Embedding failed for %s", source_path)
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
        )
        for chunk, embedding in zip(chunks, embeddings, stric=True)
    ]

    delete_chunks_by_source(source_path)
    inserted=insert_chunks(rows)
    logger.info("Sucessfully ingested %s (%s chunks)", source_path, inserted)
    return "processed", inserted

def run()->int:
    load_dotenv()
    configure_logging()

    data_dir=Path(os.getenv("DATA_DIR", "/data"))
    chunk_size=_env_int("CHUNK_SIZE", 1000)
    chunk_overlap=_env_int("CHUNK_OVERLAP", 200)
    skip_ingested=_env_bool("SKIP_INGESTED", True)

    logger.info(
        "Starting RAG ingestion | data_dir=%s skip_ingested=%s",
        data_dir,
        skip_ingested,
    )
    init_db()
    logger.info(
        "Database status | sources=%s chunks=%s",
        count_ingested_sources(),
        count_chunks(),
    )

    try:
        client=GeminiEmbeddingClient()
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    pdfs=discover_pdfs(data_dir)
    if not pdfs:
        logger.warning("No PDF files found under %s", data_dir)
        return 0

    processed=0
    skipped=0
    errors=0
    total_chunks=0

    for index, pdf_path in enumerate(pdfs, start=1):
        logger.info("[%s/%s] Processing %s", index, len(pdfs), pdf_path)
        try:
            status, chunk_count=process_pdf(
                pdf_path=pdf_path,
                data_dir=data_dir,
                client=client,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                skip_ingested=skip_ingested,
            )

        except EmbeddingCircuitOpenError as exc:
            logger.error("Circuit break triggered: %s", exc)
            logger.info(
                "Ingestion aborted | processed=%s skipped=%s errors=%s total_chunks=%s",
                processed,
                skipped,
                errors+1,
                total_chunks,
            )
            return 1
        except Exception:
            logger.exception("Unhandled error while processing %s", pdf_path)
            errors+=1
            continue

        if status=="processed":
            processed+=1
            total_chunks+=chunk_count
        elif status == "skipped":
            skipped+=1
        else:
            errors+=1

    logger.info(
        "Ingestion finished | processed=%s skipped=%s errors=%s total_chunks=%s",
        processed,
        skipped,
        errors,
        total_chunks,
    )
    return 1 if errors else 0

if __name__ == "__main__":
    sys.exit(run())